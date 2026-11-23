# Telegram agent bot

Agent loop (Agnes) + Gemini vision, file/web/shell tools, skills, self-made tools, uploads.

## Run
1. `cp .env.example .env` and fill `TELEGRAM_TOKEN`, `AGNES_API_KEYS`, `GEMINI_API_KEYS`
2. `pip install -r requirements.txt`
3. `python bot.py`

## CLI tools (ffmpeg, git, curl, ...)
- Replit: `.replit` already lists them under nix packages (nothing to download at runtime).
- Elsewhere: install them with your OS package manager. If `ffmpeg` is missing the bot installs a bundled static
  build via pip (`imageio-ffmpeg`) into `bin/` on startup (disable with `AUTO_SETUP_TOOLS=0`).
- `python scripts/setup_tools.py` prints what is available and what is missing. `bin/` is first on the agent's PATH,
  so you can drop any static binary there.

## Talking to the user from shell scripts
Inside any shell command the agent can run `say "ffmpeg found, converting"` (or `echo "::say:: ..."`;
Python: `print("::say:: ...")`). Those lines are sent to the chat immediately while the command runs
(max 10 per command) and removed from the output the model sees.

## Safety
`agent/guard.py` blocks sudo, system package managers, curl|sh, scanners, etc., and requires `confirmed=true`
for `git push` / risky `rm -r`. It is a seatbelt, not a sandbox: run the bot in a container for real isolation.
The prompt rules live in `agent/prompt.py`.

## Cost control (Agnes has no auto model switching, so the bot does it)
Agnes picks the model strictly by ID and limits are per *request* (free: ~30 RPM public / ~20 effective), and every agent
step is a request that re-sends the system prompt + all tool schemas + history. So:
- Simple messages (short, no URL/file/search/action words) go to `AGNES_FAST_MODEL` (default `agnes-1.5-flash`) with
  no tools and a tiny prompt: 1 request. If it needs tools it replies `ESCALATE` and the full agent (`AGNES_MODEL`)
  takes over. If the fast model errors, routing pauses for 10 minutes and everything uses the full agent.
- `/agent <text>` always uses the full agent. `AGNES_ROUTER=0` turns routing off. `/tools` shows routing counters.
- Tool outputs from earlier turns are shortened before being re-sent (stored history stays intact).

## Several API keys / fewer 429s
- `AGNES_API_KEYS=k1,k2,k3`: keys are used round-robin. A 429 puts that key on cooldown (Retry-After if given) and the
  request moves to the next key; 401/403 disables a key; 5xx is retried; if every key is briefly cooling it waits.
- Gemini vision: `GEMINI_VISION_MODELS` is a fallback chain (default `gemini-2.5-flash, gemini-3.5-flash-lite,
  gemini-3.1-flash-lite`). A model that returns 429 / 404 / 5xx is skipped for a while; every model has its own quota.
  Identical file+question pairs are cached so they are never sent twice. Google counts limits per *project*, so
  extra `GEMINI_API_KEYS` only help if they come from different Google Cloud projects.

## Deploy on Render (recommended: Docker + paid Background Worker + disk)
1. Push this folder to a Git repo. 2. Render: New > Blueprint > pick the repo (uses `render.yaml`).
3. Fill the secret env vars when prompted. The disk is mounted at `/data` (`DATA_DIR`): chat memory, workspaces and
   tools made by the agent survive deploys. Free web services lose all local files when they spin down/redeploy.
- Docker is used so the CLI tools (ffmpeg, git, curl, poppler, qpdf, tesseract...) are installed, and so the bot can run
  agent shell commands as an unprivileged user (`SANDBOX_UID`). Without that, a shell command can read the bot's API keys
  from `/proc/<pid>/environ`. All chats share that one sandbox user.
- Set `PORT` only if you deploy as a *web service*; a tiny health endpoint is then started.
