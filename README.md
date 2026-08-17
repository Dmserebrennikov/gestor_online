# Online Spanish Gestor

Async FastAPI backend that receives Telegram forum-topic messages and acknowledges them.

## Current stages

- **Stage 1** — webhook + normalize to `InboundMessage` / `MediaAttachment`
- **Stage 2** — auto-reply ack in the same forum topic; inbound files are downloaded into `backend/media/<kind>/`

Endpoints:

- `POST /telegram/webhook` — validates `X-Telegram-Bot-Api-Secret-Token`, maps the Update, logs it, sends an ack reply, returns `{"ok": true}`
- `GET /health` — liveness check

Attachments (photo, video, document, audio, voice) are saved under `backend/media/<kind>/`. No LLM yet.

### Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync
copy .env.example .env   # or: cp .env.example .env
```

Edit `.env`:

- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather) (required for ack replies)
- `TELEGRAM_WEBHOOK_SECRET` — long random string; must match the `secret_token` you pass to `setWebhook`

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

#### 1. Run backend from `backend/` directory:
```
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 2. Run cloudflared:
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
backend/
  app/
    main.py
    config.py
    api/telegram.py
    telegram/adapter.py
    telegram/media.py
    telegram/sender.py
    domain/models.py
  pyproject.toml
  uv.lock
  .env.example
```
