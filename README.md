# Online Spanish Gestor

Async FastAPI backend that receives Telegram forum-topic messages and acknowledges them.

## Current stages

- **Stage 1** — webhook + normalize to `InboundMessage` / `MediaAttachment`
- **Stage 2** — auto-reply ack in the same forum topic; inbound files are downloaded into `backend/media/<kind>/`

Endpoints:

- `POST /telegram/webhook` — validates `X-Telegram-Bot-Api-Secret-Token`, maps the Update, logs it, sends an ack reply, returns `{"ok": true}`
- `GET /health` — liveness check

Attachments (photo, video, document, audio, voice) are saved under `backend/media/<kind>/`. No LLM yet.

### Env and Postgres (Docker)

One **repo-root** `.env` (gitignored) is the source of truth. [docker-compose.yml](docker-compose.yml) requires `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `POSTGRES_PORT` from that file (no defaults in the YAML). FastAPI `Settings` reads the same file; it still has code defaults if a key is omitted there.

`.env` is never committed. Copy the example:

```bash
copy .env.example .env   # or: cp .env.example .env
```

`backend/.env` still works as a fallback if you already have one. Prefer moving Telegram tokens into the root `.env`.

Isolated Linux Postgres via [Docker Compose](https://docs.docker.com/compose/). Host port **5433** so a Windows Postgres install can keep **5432**. On a server, put the real password only in `.env`; do not edit secrets into the YAML. Alembic and SQLAlchemy are not wired yet — this only runs the database process.

From the repo root (requires [Docker Desktop](https://docs.docker.com/desktop/)):

```bash
docker compose up -d    # start in the background
docker compose ps       # confirm db is running / healthy
```

Check that the app can log in (same host/port/user as `.env`). From the repo root:

```bash
uv run --directory backend python scripts/check_db.py
```

Or `cd backend` and then `uv run python scripts/check_db.py`.

You should see `OK` and the Postgres version. Then:

```bash
docker compose down     # stop; data stays in the pgdata volume
```

### Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
copy .env.example .env   # repo root — Compose + app
cd backend
uv sync
```

Edit the **root** `.env`:

- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather) (required for ack replies)
- `TELEGRAM_WEBHOOK_SECRET` — long random string; must match the `secret_token` you pass to `setWebhook`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` — required for `docker compose` (copy from `.env.example`). `POSTGRES_ENGINE` / `POSTGRES_HOST` are for the app only.

`uv sync` installs runtime dependencies and the `dev` group (Ruff). For a runtime-only env: `uv sync --no-dev`.

### Lint

Line length is 120 characters (`[tool.ruff]` in `pyproject.toml`). From `backend/`:

```bash
uv run ruff check .      # fails on lines longer than 120
uv run ruff format .     # rewrites code to fit 120
```

### Run locally

From the `backend/` directory:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Telegram requires **HTTPS** for webhooks. In another terminal, expose the port (example with ngrok):

```bash
ngrok http 8000
```

Register the webhook (replace placeholders):

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" ^
  -d "url=https://<NGROK_HOST>/telegram/webhook" ^
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

On macOS/Linux use `\` instead of `^` for line continuations, or a single line:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<NGROK_HOST>/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

Check webhook status:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

### Start

#### 1. Run the database

1. Start Postgres database from the repo root:
```bash
docker compose up -d    # start in the background
```

2. Ensure the database is accessible through the app:
```bash
uv run --directory backend python scripts/check_db.py
```
You should see `OK` and the Postgres version.

Some additional functionality you may need later:
```bash
docker compose ps       # confirm db is running / healthy
docker compose down     # stop; data stays in the pgdata volume
```


#### 2. Run backend from `backend/` directory:
```
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 3. Run cloudflared:
```
cloudflared tunnel run telegram
```


### Verify

1. Add the bot to a forum group and send a message in a topic (text, photo, or PDF).
2. Server logs should show a structured `InboundMessage` with `chat_id`, `thread_id`, text preview, and attachment metadata (`file_id`, kind, mime).
3. The bot should reply in the same topic with the acknowledgement message.
4. Attachments should appear under `backend/media/photo/`, `video/`, `document/`, `audio/`, or `voice/`.

### Project layout

```
.env.example
docker-compose.yml
backend/
  app/
    main.py
    config.py
    api/telegram.py
    telegram/adapter.py
    telegram/media.py
    telegram/sender.py
    domain/models.py
  scripts/check_db.py
  pyproject.toml
  uv.lock
```
