from app.config import settings


def inbound_is_allowed(*, chat_id: int, user_id: int) -> bool:
    """Fail closed on chats; users are unrestricted unless a user allowlist is set."""
    if chat_id not in settings.telegram_allowed_chat_ids:
        return False
    allowed_users = settings.telegram_allowed_user_ids
    if allowed_users and user_id not in allowed_users:
        return False
    return True
