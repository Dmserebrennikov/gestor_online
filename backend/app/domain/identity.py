def compose_display_name(first_name: str | None, last_name: str | None) -> str | None:
    """Join first and last name; None when Telegram sent neither."""
    parts = [part.strip() for part in (first_name, last_name) if part and part.strip()]
    return " ".join(parts) if parts else None


def display_label(
    *,
    name: str | None,
    username: str | None,
    telegram_user_id: int | None,
) -> str:
    """Speaker label: ``Ana García (@anag) id:123``, omitting missing pieces."""
    who = (name or "").strip()
    handle = f"(@{username})" if username else None
    ident = f"id:{telegram_user_id}" if telegram_user_id is not None else None
    parts = [part for part in (who or None, handle, ident) if part]
    return " ".join(parts) if parts else "User"
