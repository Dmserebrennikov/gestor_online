import logging
import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)

# LangChain's Gemini provider id is google_genai, not google.
# This is only used when LLM_MODEL starts with "google/"; default is DeepSeek Flash.
_PROVIDER_ALIASES = {"google": "google_genai"}
_PROVIDER_API_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}

_DEFAULT_DEEPSEEK_VISION = "deepseek/deepseek-v4-flash-vision-exp"
_chat_models: dict[str, BaseChatModel] = {}


def parse_llm_model(value: str) -> tuple[str | None, str]:
    """Split `provider/model`. Bare names have no provider (LangChain infers)."""
    if "/" not in value:
        return None, value
    provider, model = value.split("/", 1)
    return _PROVIDER_ALIASES.get(provider, provider), model


def resolve_llm_model(*, vision: bool = False) -> str:
    """Pick the text model, or a vision-capable one when the request has images."""
    if vision:
        configured = (settings.llm_vision_model or "").strip()
        if configured:
            return configured
        _, model = parse_llm_model(settings.llm_model)
        if model == "deepseek-v4-flash":
            return _DEFAULT_DEEPSEEK_VISION
    return settings.llm_model


def get_chat_model(*, vision: bool = False) -> BaseChatModel:
    """Lazy singleton per resolved model spec so provider/model is logged once."""
    spec = resolve_llm_model(vision=vision)
    cached = _chat_models.get(spec)
    if cached is None:
        cached = _build_chat_model(spec)
        _chat_models[spec] = cached
    return cached


def _build_chat_model(spec: str) -> BaseChatModel:
    provider, model = parse_llm_model(spec)
    logger.info(f"Initializing LLM provider={provider} | model={model}")
    env_key = _PROVIDER_API_KEYS.get(provider or "")
    if env_key and not os.getenv(env_key):
        raise RuntimeError(
            f"{env_key} is not set. Add it to the repo-root .env (or export it) "
            f"so LangChain can authenticate with {provider}."
        )
    if provider:
        return init_chat_model(
            model,
            model_provider=provider,
            timeout=settings.llm_request_timeout,
        )
    return init_chat_model(model, timeout=settings.llm_request_timeout)
