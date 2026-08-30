from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Application settings from the environment and `.env` files."""

    model_config = SettingsConfigDict(
        # Root .env is the source of truth (Compose + app). backend/.env is a fallback.
        env_file=(str(_BACKEND_ROOT / ".env"), str(_REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Env names are the field names uppercased (TELEGRAM_BOT_TOKEN, POSTGRES_USER, …).
    telegram_bot_token: str = Field(min_length=1)
    telegram_webhook_secret: str = Field(min_length=1)

    postgres_engine: str = "postgresql+asyncpg"
    postgres_db: str = "gestor"
    postgres_user: str = "gestor"
    postgres_password: str = "gestor"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL built from the Postgres fields above."""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"{self.postgres_engine}://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
