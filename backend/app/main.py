import logging

from fastapi import FastAPI

from app.api.telegram import router as telegram_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="Gestor Online", version="0.1.0")
app.include_router(telegram_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Hello from local server / starting page!"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the API process."""
    return {"status": "ok"}
