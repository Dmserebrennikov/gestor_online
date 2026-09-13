# Online Spanish Gestor

Async FastAPI backend: Telegram forum-topic messages → LangChain LLM reply in the same topic, with durable Postgres memory.

## Current stages

- **Stage 1** — webhook + normalize to `InboundMessage` / `MediaAttachment`
- **Stage 2** — inbound files downloaded into `var/media/<kind>/`; 👀 reaction on the user message
- **Stage 3** — persist every turn in Postgres; last N messages of the **whole topic** (speaker-labeled) go to LangChain (DeepSeek V4 Flash by default); reply in the same topic

Endpoints:

- `POST /telegram/webhook` — validates `X-Telegram-Bot-Api-Secret-Token`, maps the Update, returns `{"ok": true}` immediately, then in a background task waits for sibling updates of the same send, downloads attachments, and generates the LLM reply
- `GET /health` — liveness check

Attachments (photo, video, document, audio, voice, static sticker, animation) are saved under `var/media/<kind>/` (override with `MEDIA_DIR`). Voice and audio files are transcribed with the OpenAI transcription API (`gpt-4o-mini-transcribe` by default, needs `OPENAI_API_KEY`); the transcript is stored with the turn and the model reads it as spoken text. Raster images on the **current** user turn — including image documents, HEIC/AVIF/BMP/TIFF (converted to JPEG), static stickers, and GIF animations — are sent to the model as pixels. Older photo turns stay as text notes. Telegram albums (`media_group_id`) are coalesced into one turn. The default `deepseek/deepseek-flash` model has native vision; set `LLM_VISION_MODEL` only to force a different model on image turns.

### Memory (Stage 3 vs later)

Working memory is a query, not a RAM cache. Restarting uvicorn does not wipe conversations.

| Path | What it stores | When |
|---|---|---|
| Identity | Speaker (`telegram_user_id`) + display name | **Stage 3** |
| Topic conversation | Every turn in that forum topic / chat, all speakers | **Stage 3** |
| Working memory | Last `LLM_HISTORY_MAX_MESSAGES` (default 20) of the whole topic, labeled `Name: …` | **Stage 3** |
| History backdoor | Older turns via FTS, then embeddings | Later |
| User portfolio | NIF, invoices, expenses, cases per user | Later |
| Domain knowledge (RAG) | Laws, AEAT texts, modelo templates in `pgvector` | Later |

The interface for now is the private family workspace topic. You and another family member both talk there; the bot loads **all speakers** in that topic, not only the person who just wrote.

### Env and Postgres (Docker)

One **repo-root** `.env` (gitignored) is the source of truth. [docker-compose.yml](docker-compose.yml) requires `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `POSTGRES_PORT` from that file (no defaults in the YAML). FastAPI `Settings` reads the same file; it still has code defaults if a key is omitted there.

`.env` is never committed. Copy the example:

```bash
copy .env.example .env   # or: cp .env.example .env
```

Isolated Linux Postgres via [Docker Compose](https://docs.docker.com/compose/). Host port **5433** so a Windows Postgres install can keep **5432**. On a server, put the real password only in `.env`; do not edit secrets into the YAML.

From the repo root (requires [Docker Desktop](https://docs.docker.com/desktop/)):

```bash
docker compose up -d    # start in the background
docker compose ps       # confirm db is running / healthy
```

Check that the app can log in (same host/port/user as `.env`). From the repo root:

```bash
uv run --directory backend python scripts/check_db.py
```

You should see `OK` and the Postgres version. Apply schema migrations from `backend/`:

```bash
uv run --directory backend alembic upgrade head
```

Then:

```bash
docker compose down     # stop; data stays in the pgdata volume
```

### Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
copy .env.example .env   # repo root — Compose + app
cd backend
uv sync
uv run alembic upgrade head
```

Edit the **root** `.env`:

- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_WEBHOOK_SECRET` — long random string; must match the `secret_token` you pass to `setWebhook`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` — required for `docker compose` (copy from `.env.example`). `POSTGRES_ENGINE` / `POSTGRES_HOST` are for the app only.
- `TELEGRAM_ALLOWED_CHAT_IDS` — comma-separated chat ids the bot will serve. Empty means deny all chats.
- `TELEGRAM_ALLOWED_USER_IDS` — optional. Empty means any user inside an allowed chat; otherwise only listed users.
- `MEDIA_DIR` — attachment archive root (default `<repo>/var/media`).
- `LLM_MODEL` — `provider/model` (default `deepseek/deepseek-flash`). Prefixes: `deepseek/`, `openai/`, `anthropic/`, `google/` (maps to LangChain `google_genai`), `ollama/`
- `LLM_VISION_MODEL` — optional. Used when a turn includes images. Unset: reuse `LLM_MODEL` (DeepSeek Flash has native vision).
- `DEEPSEEK_API_KEY` — required for the default model. Other providers: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (uncomment in `.env.example`). These stay out of `Settings`; the app loads `.env` into the process environment so LangChain can read them.
- `LLM_HISTORY_MAX_MESSAGES` — working-memory window (default 20)
- `LLM_REQUEST_TIMEOUT` — optional override (seconds)
- `STT_MODEL` — OpenAI transcription model for voice/audio notes (default `gpt-4o-mini-transcribe`). Requires `OPENAI_API_KEY`.
- `STT_LANGUAGE` — fallback language hint (ISO-639-1, default `es`) when Telegram sends no `language_code`. Empty: no hint.
- `STT_TIMEOUT` — transcription request timeout (seconds, default 60)

The system prompt is **not** in `.env`. Edit [`backend/app/llm/prompts.py`](backend/app/llm/prompts.py).

`uv sync` installs runtime dependencies and the `dev` group (Ruff). For a runtime-only env: `uv sync --no-dev`.

### Lint

Line length is 120 characters (`[tool.ruff]` in `pyproject.toml`). From `backend/`:

```bash
uv run ruff check .      # fails on lines longer than 120
uv run ruff format .     # rewrites code to fit 120
```

### Add a new Alembic migration

Alembic is the schema-versioning CLI (SQLAlchemy’s equivalent of Django `makemigrations` / `migrate`). It is **not** a Docker service and FastAPI does **not** run it on startup. Postgres must already be up (`docker compose up -d`).

Two different jobs:

| When | Command | What it does |
|---|---|---|
| Setup, new machine, after `git pull`, fresh Docker volume | `alembic upgrade head` | Apply revision files that already exist |
| You changed SQLAlchemy models | `alembic revision --autogenerate` | Write a **new** file under `backend/alembic/versions/` |

Only the person changing the schema runs autogenerate — once per change — then commits that file. Everyone else only runs `upgrade head`.

#### Author a revision

1. Edit the models in [`backend/app/db/models.py`](backend/app/db/models.py) (add/rename a column, table, index, constraint, …). Do **not** hand-edit Postgres and then autogenerate; the models are the source of truth.

2. With Postgres running, generate a draft from the diff between `Base.metadata` and the live database. From the repo root:

```bash
uv run --directory backend alembic revision --autogenerate -m "add user locale"
```

Or from `backend/`: `uv run alembic revision --autogenerate -m "add user locale"`.

Use a short imperative message (`add …`, `drop …`). Alembic names the file from a revision id plus that slug.

3. Open the new file in `backend/alembic/versions/` and check `upgrade()` / `downgrade()`. Autogenerate is a draft: it can miss or mis-state things (this project’s `UNIQUE NULLS NOT DISTINCT` on `conversations` had to be raw SQL). Fix the file before applying.

For a blank script instead of a diff (data migrations, raw SQL):

```bash
uv run --directory backend alembic revision -m "backfill display names"
```

4. Apply it to your database:

```bash
uv run --directory backend alembic upgrade head
```

5. Commit the model change **and** the new revision together. After that, teammates and deploys only need `upgrade head`.

#### Rules of thumb

- Never edit a revision that has already been applied to a shared database (your Docker volume, a teammate, production). Add another revision instead.
- Do not rerun autogenerate on an unchanged schema; it will create an empty or duplicate revision.
- `docker compose down` keeps data. `docker compose down -v` wipes the volume — the next `upgrade head` recreates tables from scratch.

Useful inspect/undo commands (repo root):

```bash
uv run --directory backend alembic current     # revision applied to this database
uv run --directory backend alembic history     # chain of files in the repo
uv run --directory backend alembic downgrade -1  # undo the last revision (dev only)
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

1. Start Postgres from the repo root:
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

3. Apply migrations if needed:
```bash
uv run --directory backend alembic upgrade head
```

This only **applies** existing files under `backend/alembic/versions/`. To **create** a new file after changing models, see [Add a new Alembic migration](#add-a-new-alembic-migration).

#### 2. Run backend from (!) `backend/` (!) directory:
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
3. The bot should show typing, then reply in the same topic with the model (not a canned ack).
4. A second person in the same topic asks a follow-up that depends on the first message — the bot should use the shared window.
5. Restart uvicorn, send another follow-up — it should still remember (history is in Postgres).
6. Attachments should appear under `var/media/photo/`, `video/`, `document/`, `audio/`, or `voice/` (or `$MEDIA_DIR/<kind>/`).

### Project layout

```
.env.example
docker-compose.yml
backend/
  alembic.ini
  alembic/
    env.py
    versions/
  app/
    main.py
    config.py
    api/telegram.py
    telegram/adapter.py
    telegram/allowlist.py
    telegram/dedupe.py
    telegram/http.py
    telegram/media.py
    telegram/sender.py
    domain/identity.py
    domain/models.py
    db/models.py
    db/session.py
    db/crud.py
    llm/client.py
    llm/prompts.py
    llm/pipeline.py
    llm/images.py
  scripts/check_db.py
  pyproject.toml
  uv.lock
```
