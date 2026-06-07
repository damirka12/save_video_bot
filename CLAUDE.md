# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (`@SaveVideoFreee_bot`) that downloads videos from YouTube, Instagram, TikTok, RuTube, VK, and Twitter/X via `yt-dlp`, then sends them back to the user. Built on **aiogram 3.x** (async). UI text is in Russian. Ships with a separate **FastAPI web admin** (`web/app.py`) for editing all bot texts.

## Deployment & commands

Production runs **on a server via Docker**, not locally. The user owns all git and server operations — Claude only makes code changes and hands the user the exact commands to run (do not run `git push/pull/commit` or `docker compose` yourself). See the `deploy-workflow` memory.

Two services in `docker-compose.yml`, both built from the same `Dockerfile` (which installs `ffmpeg`):
- `bot` — runs `python bot.py` (long-polling)
- `admin` — runs `uvicorn web.app:app` on port 8080 (text editor UI)

```bash
docker compose up -d --build      # build & run both services
docker compose logs -f            # follow logs
git pull && docker compose up -d --build   # update on server

# Local dev without Docker (deps must be installed + ffmpeg on PATH):
pip install -r requirements.txt
python bot.py
uvicorn web.app:app --reload      # admin UI at http://localhost:8000
```

No test suite or linter. Syntax-check with `python3 -m py_compile <files>`. `ffmpeg`/`ffprobe` are required (subprocess) and now come from the Docker image.

## Configuration

`config.py` and `db_service.py` read from **environment variables** (loaded from `.env` via docker-compose `env_file`), with hardcoded fallbacks so local `python bot.py` still works. `.env` is gitignored — `.env.example` is the template. Vars: `BOT_TOKEN`, `ADMIN_ID`, `DB_PATH`, `ADMIN_PANEL_USER`/`ADMIN_PANEL_PASSWORD` (Basic-Auth for the admin UI), `ADMIN_PORT`.

- `USE_LOCAL_SERVER` (still in `config.py`) — when `True`, routes through a self-hosted Telegram Bot API server at `LOCAL_SERVER_URL`, raising the upload limit. This single flag also flips `TELEGRAM_LIMIT_MB` between **50 MB** (cloud) and **2000 MB** (local). Change the limit via this flag, not the number.
- **The SQLite DB lives in `data/users.db`** (env `DB_PATH`), and `data/` is bind-mounted into *both* containers so they share one DB file. This matters: SQLite is in WAL mode with `busy_timeout`, and the `-wal`/`-shm` sidecar files must be in a shared directory — never split the DB across separate single-file mounts.

## Architecture

Entry point `bot.py` calls `init_db()`, then registers three routers **in this order** — order is load-bearing:

1. `admin_router` — matches exact button texts (`📊 Статистика`, `📢 Рассылка`) and `/stats`, `/broadcast`. Admin-gated by `message.from_user.id == ADMIN_ID`. Broadcast uses an FSM state (`BroadcastState.waiting`) and `message.copy_to` per user.
2. `start_router` — `/start`, `/help`, and `📥 Как пользоваться`. Picks `ADMIN_KEYBOARD` vs `KEYBOARD` based on `ADMIN_ID`.
3. `download_router` — the catch-all. `handle_url` triggers on **any** message matching `https?://`, so it must come last or it would swallow button presses.

State storage is `MemoryStorage` (in-process). Restarting the bot loses all FSM and the URL cache.

### Download flow (`handlers/download.py` → `services/downloader.py`)

1. User sends a URL → `handle_url` detects the platform, caches the URL under a numeric `url_key` (`abs(hash(url)) % 10**9`) in the in-memory `_url_cache` dict, and shows a quality keyboard. **Because the cache is in-memory, after a restart old buttons return "ссылка устарела".**
2. The keyboard differs by platform: `SIMPLE_PLATFORMS = {"TikTok", "Instagram"}` get only Видео/Аудио; everything else gets 360p/720p/1080p/Аудио. The callback data format is `q:{url_key}:{quality}`.
3. `download_selected` reads back the URL, downloads via `download_video`, then enforces the size limit (see below), then uploads as `answer_video` or `answer_audio` and **deletes the local file in a `finally` block** (downloads are not retained).

### Download guards (handlers/download.py, config.py)

Several protections layer onto the flow, all tunable via env (`config.py`): `_url_cache` is a `_TTLCache` (TTL + max size, so it can't leak); `handle_url` rejects videos longer than `MAX_VIDEO_DURATION` before downloading; `download_selected` enforces **one download per user** (`_active_users`) and a global `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)` (shows a "queued" message when full). The actual work lives in `_do_download`, wrapped by the semaphore. On startup, `bot.py` calls `cleanup_downloads()` to remove orphan files left by a mid-process crash. ffmpeg re-encodes use `-preset veryfast` to cap CPU.

### `services/downloader.py` — the core logic

- All `yt-dlp` and `ffmpeg` work runs in `asyncio.to_thread` to avoid blocking the event loop. Download progress is pushed back to the async handler from a sync `yt-dlp` hook via `asyncio.run_coroutine_threadsafe`.
- **Format selection is per-quality** (`bestvideo[height<=N]+bestaudio` etc.). TikTok/Instagram deliberately download the pre-muxed `best[ext=mp4]` to preserve the original 9:16 without a re-mux.
- **`crop_portrait`** runs only for TikTok/Instagram video: it probes SAR; if the display is portrait but SAR is non-square it applies `setsar=1`; otherwise it uses `ffmpeg cropdetect` (accepting a crop only if the result is portrait) and falls back to a forced center crop to 9:16. This exists to undo letterboxing/padding these platforms add.
- **`compress_video`** is the size-limit fallback: it computes a target bitrate from duration to hit `TELEGRAM_LIMIT_MB`, re-encodes with libx264/aac, and returns `None` if the math would drop video below 80 kbps. The caller then asks the user to pick a lower quality.
- YouTube uses `player_client: ["ios"]` and optionally a `youtube_cookies.txt` file in the repo root (used automatically if present) to get around extraction blocks.

### Persistence (`services/db_service.py`)

SQLite via `aiosqlite`, opened through the `_db()` context manager (sets `busy_timeout`). Two tables: `users` (every interaction calls `add_user`, an upsert refreshing `last_seen` — doubles as activity tracking for `/stats`) and `texts` (text overrides, see below).

### Editable texts (`services/texts.py` + `web/app.py`)

**All user-facing strings are externalized** — there are no hardcoded message strings left in the handlers. The flow:

- `services/texts.py` holds `REGISTRY`: every text with a `key`, `group`, `label`, allowed `placeholders`, and `default`. `DEFAULTS` is derived from it.
- Overrides are stored in the `texts` DB table. `txt(key, **kwargs)` returns the override-or-default with `{placeholder}` substitution; `raw(key)` returns it un-formatted (for button captions). Substitution uses a `_SafeDict` so missing/extra placeholders never crash.
- The bot caches all texts in-process with a **5-second TTL** (`_TTL`), so edits made in the admin UI appear within ~5s without a restart. The admin runs in a *separate process/container*, which is exactly why it's a TTL cache and not an in-memory reload signal.
- The web admin (`web/app.py`, Basic-Auth) lists every text grouped by `REGISTRY` order with textareas; saving writes to the `texts` table, or deletes the row when the value equals the default (so "reset" = no override).

**When adding a new user-facing message:** add an entry to `REGISTRY` and reference it via `txt()`/`raw()` — do not inline strings. **Reply-keyboard button captions** (`btn.help`, `btn.stats`, `btn.broadcast`) are matched at runtime by `TextEquals` (`services/filters.py`), which compares against the *current* caption — this is what lets button labels be edited without breaking the handlers. Inline-button captions are safe to edit freely because the action lives in `callback_data`, not the label. The corresponding `/start`, `/help`, `/stats`, `/broadcast` slash commands are always-working fallbacks.

## Conventions

- All user-facing messages are HTML-formatted (`parse_mode="HTML"`) and in Russian, heavy on emoji.
- Handlers swallow download/extraction errors and surface them to the user as a message rather than raising.
