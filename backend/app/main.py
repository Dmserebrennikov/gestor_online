import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.telegram import router as telegram_router
from app.db.session import close_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# httpx INFO logs the full request URL; Telegram puts the bot token in that path.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_db()


app = FastAPI(title="Gestor Online", version="0.1.0", lifespan=lifespan)
app.include_router(telegram_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Hello from local server / starting page!"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the API process."""
    return {"status": "ok"}
