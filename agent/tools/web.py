import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

from agent.workspace import rel, resolve, share_upwards

from .base import schema

UA = {"User-Agent": "Mozilla/5.0 (compatible; TelegramAgent/1.0)"}
MAX_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD = 25 * 1024 * 1024


def _check_public(url: str):
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http(s) URLs are allowed")
    for info in socket.getaddrinfo(parts.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Refusing to fetch private/internal addresses")


def _get(url: str, limit: int):
    """GET with per-hop SSRF checks, manual redirects and a size cap."""
    for _ in range(6):
        _check_public(url)
        r = requests.get(url, headers=UA, timeout=20, stream=True, allow_redirects=False)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            continue
        chunks, size = [], 0
        for chunk in r.iter_content(65536):
            size += len(chunk)
            if size > limit:
                break
            chunks.append(chunk)
        return r, b"".join(chunks), size > limit
    raise ValueError("Too many redirects")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    text = html.unescape("".join(p.out))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def web_fetch(args):
    try:
        r, body, cut = _get(args["url"], MAX_BYTES)
    except Exception as e:
        return {"error": str(e)}
    ctype = r.headers.get("Content-Type", "")
    if "html" in ctype or body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        text = html_to_text(body.decode(r.encoding or "utf-8", errors="replace"))
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        text = body.decode(r.encoding or "utf-8", errors="replace")
    else:
        return {"status": r.status_code, "content_type": ctype,
                "note": "Binary content. Use download_file to save it into the workspace."}
    max_chars = max(500, min(int(args.get("max_chars") or 12000), 30000))
    return {"status": r.status_code, "url": args["url"], "truncated": cut or len(text) > max_chars,
            "content": text[:max_chars]}


def download_file(args):
    try:
        r, body, cut = _get(args["url"], MAX_DOWNLOAD)
        if cut:
            return {"error": "File larger than 25 MB"}
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}"}
        path = resolve(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        share_upwards(path)
        return {"ok": True, "path": rel(path), "bytes": len(body),
                "content_type": r.headers.get("Content-Type", "")}
    except Exception as e:
        return {"error": str(e)}


_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|\Z)', re.S)
_SNIP = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def parse_ddg(page: str, n: int):
    results = []
    for href, title, rest in _RESULT.findall(page):
        if href.startswith("//"):
            href = "https:" + href
        qs = parse_qs(urlparse(href).query)
        url = unquote(qs["uddg"][0]) if "uddg" in qs else href
        snip = _SNIP.search(rest)
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
        results.append({"title": clean(title), "url": url, "snippet": clean(snip.group(1)) if snip else ""})
        if len(results) >= n:
            break
    return results


def web_search(args):
    n = max(1, min(int(args.get("max_results") or 6), 10))
    try:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": args["query"]},
                          headers=UA, timeout=20)
        results = parse_ddg(r.text, n)
    except Exception as e:
        return {"error": f"Search failed: {e}"}
    return {"query": args["query"], "results": results} if results else {"error": "No results (or search blocked)"}


TOOLS = {
    "web_search": (schema("web_search", "Search the web (DuckDuckGo). Returns titles, URLs and snippets; "
                          "follow up with web_fetch to read a page. Use for anything recent or unknown.",
                          {"query": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"]), web_search),
    "web_fetch": (schema("web_fetch", "Fetch a public web page and return readable text (HTML is stripped).",
                         {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"]), web_fetch),
    "download_file": (schema("download_file", "Download a public URL (PDF, image, CSV...) into the workspace (max 25 MB).",
                             {"url": {"type": "string"}, "path": {"type": "string", "description": "Destination path in workspace"}},
                             ["url", "path"]), download_file),
}
