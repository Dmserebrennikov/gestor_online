"""In-memory update_id LRU so Telegram retries do not create duplicate turns.

Sub-plan 02 replaces this with the durable ``inbound_events`` table. Keep
``seen_update`` as the webhook entry point so that swap is one call site.
"""

import threading
import time
from collections import OrderedDict

_TTL_SECONDS = 5 * 60
_MAX_ENTRIES = 2000

_seen: OrderedDict[int, float] = OrderedDict()
_lock = threading.Lock()


def seen_update(update_id: int, *, now: float | None = None) -> bool:
    """Return True if ``update_id`` was already recorded (duplicate)."""
    clock = time.monotonic() if now is None else now
    with _lock:
        _evict(clock)
        if update_id in _seen:
            return True
        _seen[update_id] = clock
        if len(_seen) > _MAX_ENTRIES:
            _seen.popitem(last=False)
        return False


def reset_seen() -> None:
    """Drop the cache. Tests only."""
    with _lock:
        _seen.clear()


def _evict(now: float) -> None:
    cutoff = now - _TTL_SECONDS
    while _seen:
        _oldest_id, timestamp = next(iter(_seen.items()))
        if timestamp > cutoff:
            break
        _seen.popitem(last=False)
