import json
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_MEDIA_DIR = _REPO_ROOT / "var" / "media"

# Export .env into os.environ so LangChain can read DEEPSEEK_API_KEY etc.
load_dotenv(_REPO_ROOT / ".env")


def _parse_id_list(value: object) -> list[int]:
    """Accept a comma-separated string, a JSON array, or an already-parsed list."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            return [int(item) for item in parsed]
        return [int(part) for part in text.split(",") if part.strip()]
    return [int(value)]


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
    # Empty chat list denies every chat (fail closed). Empty user list allows any
    # speaker inside an allowed chat.
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)

    postgres_engine: str = "postgresql+asyncpg"
    postgres_db: str = "gestor"
    postgres_user: str = "gestor"
    postgres_password: str = "gestor"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # "provider/model"; a bare name lets LangChain infer the provider.
    llm_model: str = "deepseek/deepseek-flash"
    # Optional override when a turn includes images. Empty: reuse llm_model (Flash has native vision).
    llm_vision_model: str | None = None
    llm_history_max_messages: int = 20
    llm_request_timeout: float = 60.0

    # Speech-to-text for voice/audio turns (OpenAI transcription API, OPENAI_API_KEY).
    stt_model: str = "gpt-4o-mini-transcribe"
    # Fallback language hint (ISO-639-1) when Telegram sends no language_code. Empty: no hint.
    stt_language: str | None = "es"
    stt_timeout: float = 60.0

    media_dir: Path = _DEFAULT_MEDIA_DIR

    @field_validator("telegram_allowed_chat_ids", "telegram_allowed_user_ids", mode="before")
    @classmethod
    def _split_id_list(cls, value: object) -> list[int]:
        return _parse_id_list(value)

    @field_validator("media_dir", mode="before")
    @classmethod
    def _empty_media_dir(cls, value: object) -> Path:
        if value is None or value == "":
            return _DEFAULT_MEDIA_DIR
        return Path(value)

    @field_validator("llm_vision_model", mode="before")
    @classmethod
    def _empty_vision_model(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("stt_language", mode="before")
    @classmethod
    def _empty_stt_language(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL built from the Postgres fields above."""
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"{self.postgres_engine}://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
