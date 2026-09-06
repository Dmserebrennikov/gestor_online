from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Export .env into os.environ so LangChain can read DEEPSEEK_API_KEY etc.
load_dotenv(_REPO_ROOT / ".env")


class Settings(BaseSettings):
    """Application settings from the environment and the repo-root `.env`."""

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
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

    # "provider/model"; a bare name lets LangChain infer the provider.
    llm_model: str = "deepseek/deepseek-v4-flash"
    # When a turn includes images. Empty: DeepSeek Flash auto-routes to its vision model.
    llm_vision_model: str | None = None
    llm_history_max_messages: int = 20
    llm_request_timeout: float = 60.0

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL built from the Postgres fields above."""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"{self.postgres_engine}://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
