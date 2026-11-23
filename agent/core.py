import json
import threading
import time
from collections import defaultdict

import openai
from openai import OpenAI

from agent import memory, router
from agent.keypool import AllKeysUnavailable, KeyPool
from agent.prompt import build_system_prompt
from agent.tools import execute, schemas
from context import current_chat_id
from settings import (AGNES_API_KEYS, AGNES_BASE_URL, AGNES_FAST_MODEL, AGNES_MODEL, AGNES_ROUTER, MAX_STEPS,
                      MAX_TOOL_CHARS)

_pool: KeyPool | None = None
_clients: dict[str, OpenAI] = {}
_pool_lock = threading.Lock()
_chat_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()
DEFAULT_429_COOLDOWN = 30     # seconds, when the API gives no Retry-After
MAX_WAIT_FOR_KEY = 20         # if every key is cooling for less than this, wait instead of failing
ROUTER_ENABLED = AGNES_ROUTER and bool(AGNES_FAST_MODEL)
ROUTER_RETRY_AFTER = 600      # if the fast model errors, stop probing it for this many seconds
STATS = {"fast": 0, "escalated": 0, "full": 0}
_fast_off_until = 0.0


def _get_pool() -> KeyPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = KeyPool(AGNES_API_KEYS, "agnes")
        return _pool


def _client_for(key: str) -> OpenAI:
    with _pool_lock:
        if key not in _clients:
            # max_retries=0: retries/rotation are handled here, across keys
            _clients[key] = OpenAI(api_key=key, base_url=AGNES_BASE_URL, max_retries=0, timeout=90)
        return _clients[key]


def _chat_lock(chat_id) -> threading.Lock:
    with _locks_guard:
        return _chat_locks[str(chat_id)]


def _retry_after(e) -> float:
    try:
        return max(1.0, min(float(e.response.headers.get("retry-after")), 600.0))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_429_COOLDOWN


def _call_model(messages: list[dict], tools: list[dict] | None, model: str | None = None, patient: bool = True):
    """One chat completion with key rotation: 429 -> cool that key down and use the next one,
    401/403 -> disable that key, 5xx/network -> short pause and retry (next key).
    patient=False (cheap probes): never sleep or retry on errors, just rotate on 429/401 and raise otherwise."""
    pool, last, transient = _get_pool(), None, 0
    kwargs = {"model": model or AGNES_MODEL, "messages": messages}
    if tools:  # never send an empty tools list / tool_choice to a model that has no tools
        kwargs.update(tools=tools, tool_choice="auto")
    for _ in range(len(pool.keys) * 3 + 3 if patient else len(pool.keys)):
        try:
            index, key = pool.acquire()
        except AllKeysUnavailable as e:
            if e.wait is None:
                raise RuntimeError("Every API key was rejected. Check AGNES_API_KEYS.") from last
            if not patient or e.wait > MAX_WAIT_FOR_KEY:
                raise RuntimeError(f"All API keys are rate limited; try again in about {int(e.wait)}s.") from last
            time.sleep(e.wait + 0.2)
            continue
        try:
            res = _client_for(key).chat.completions.create(**kwargs)
            return res.choices[0].message
        except openai.RateLimitError as e:
            pool.cooldown(index, _retry_after(e))
            last = e
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            pool.disable(index)
            last = e
        except openai.BadRequestError:
            raise  # our request is wrong; another key won't help
        except (openai.APIStatusError, openai.APIConnectionError, openai.APITimeoutError) as e:
            if not patient:
                raise
            transient += 1
            last = e
            print(f"MODEL ERROR (key #{index + 1}): {type(e).__name__}")
            if transient > 3:
                break
            time.sleep(1.5 * transient)
    raise RuntimeError(f"Model unreachable: {type(last).__name__ if last else 'unknown error'}")


def _try_fast(query: str, history: list[dict]) -> str | None:
    """Answer a simple message with the cheap tool-less model. None = escalate to the full agent."""
    global _fast_off_until
    if time.monotonic() < _fast_off_until:
        return None
    msgs = [{"role": "system", "content": router.short_prompt()}] + router.plain_history(history) + [{"role": "user", "content": query}]
    try:
        msg = _call_model(msgs, None, model=AGNES_FAST_MODEL, patient=False)
    except Exception as e:
        print(f"[router] fast model failed ({type(e).__name__}); using the full agent for the next {ROUTER_RETRY_AFTER}s")
        _fast_off_until = time.monotonic() + ROUTER_RETRY_AFTER
        return None
    text = (msg.content or "").strip()
    if not text or text.upper().startswith(router.ESCALATE):
        STATS["escalated"] += 1
        return None
    STATS["fast"] += 1
    return text


def _as_dict(msg) -> dict:
    """Plain, minimal assistant message (safe to store as JSON and send back to the API)."""
    d = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
            for tc in msg.tool_calls
        ]
    return d


def _brief(name: str, args: dict) -> str:
    hint = args.get("command") or args.get("path") or args.get("query") or args.get("url") or args.get("name") or ""
    return f"{name}: {str(hint)[:60]}" if hint else name


def _run_tool(tc, on_event) -> dict:
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        if on_event:
            on_event(f"⚙️ {_brief(name, args)}")
        result = execute(name, args)
    except PermissionError as e:  # sandbox refusal: model must report it, not route around it
        result = {"blocked": True, "reason": str(e),
                  "instruction": "Do NOT retry or work around this. Tell the user what was blocked."}
    except Exception as e:  # every tool call MUST get a result or the history becomes invalid
        print(f"TOOL ERROR {name}: {e!r}")
        result = {"error": f"{type(e).__name__}: {e}"}
    content = json.dumps(result, default=str, ensure_ascii=False)
    if len(content) > MAX_TOOL_CHARS:
        content = content[:MAX_TOOL_CHARS] + '..."[truncated]"'
    return {"role": "tool", "tool_call_id": tc.id, "content": content}


def agent(query: str, chat_id, display_name: str | None = None, on_event=None, route: bool = True) -> str:
    """Run one user turn to completion. Thread-safe; turns for the same chat are serialised."""
    ctx_token = current_chat_id.set(chat_id)
    try:
        with _chat_lock(chat_id):
            history = memory.load(chat_id)
            new = [{"role": "user", "content": f"{display_name}: {query}" if display_name else query}]
            reply = None
            if route and ROUTER_ENABLED and router.is_simple(query, history):
                fast = _try_fast(new[0]["content"], history)
                if fast is not None:
                    memory.append_many(chat_id, new + [{"role": "assistant", "content": fast}])
                    return fast
            STATS["full"] += 1
            history = router.compact(history)
            try:
                for _ in range(MAX_STEPS):
                    msgs = [{"role": "system", "content": build_system_prompt()}] + history + new
                    msg = _call_model(msgs, schemas())  # schemas() re-read: picks up freshly created tools
                    new.append(_as_dict(msg))
                    if not msg.tool_calls:
                        reply = (msg.content or "").strip() or "✅ Done."
                        break
                    for tc in msg.tool_calls:
                        new.append(_run_tool(tc, on_event))
                else:
                    reply = "I hit my step limit before finishing. Say 'continue' and I'll pick up where I left off."
                    new.append({"role": "assistant", "content": reply})
            except Exception as e:
                reply = f"⚠️ I couldn't complete that: {e}"
                if new[-1].get("role") == "assistant" and new[-1].get("tool_calls"):
                    new.pop()
                new.append({"role": "assistant", "content": reply})
            finally:
                memory.append_many(chat_id, new)
            return reply
    finally:
        current_chat_id.reset(ctx_token)
