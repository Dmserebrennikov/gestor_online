"""Telegram Bot API HTTP. Logs and errors use method names, never the token URL."""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import httpx

from app.config import settings

TG_BASE_URL = "https://api.telegram.org"


class TelegramAPIError(RuntimeError):
    """A Bot API call failed. The message must not include the bot-token URL."""


def hide_token_url(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Replace httpx errors (which embed the bot-token URL) with a method-only message."""

    @wraps(fn)
    async def wrapper(label: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(label, *args, **kwargs)
        except httpx.HTTPError as exc:
            raise TelegramAPIError(f"Telegram {label} request failed ({type(exc).__name__})") from None

    return wrapper


def _method_url(method: str) -> str:
    return f"{TG_BASE_URL}/bot{settings.telegram_bot_token}/{method}"


def _file_url(file_path: str) -> str:
    return f"{TG_BASE_URL}/file/bot{settings.telegram_bot_token}/{file_path}"


def _result_or_raise(method: str, response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.is_error or not (isinstance(data, dict) and data.get("ok")):
        detail = data if data is not None else response.text[:200]
        raise TelegramAPIError(f"Telegram {method} HTTP {response.status_code}: {detail}")
    return data


@hide_token_url
async def _request(label: str, timeout: float, http_method: str, url: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(http_method, url, **kwargs)


async def post_method(method: str, payload: dict[str, object], timeout: float) -> dict:
    response = await _request(method, timeout, "POST", _method_url(method), json=payload)
    return _result_or_raise(method, response)


async def get_method(method: str, params: dict[str, object], timeout: float) -> dict:
    response = await _request(method, timeout, "GET", _method_url(method), params=params)
    return _result_or_raise(method, response)


async def download_file(file_path: str, timeout: float) -> bytes:
    response = await _request("file download", timeout, "GET", _file_url(file_path))
    if response.is_error:
        raise TelegramAPIError(f"Telegram file download HTTP {response.status_code}")
    return response.content
