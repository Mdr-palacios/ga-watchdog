"""Per-IP rate limiting.

ADR-0005 decision 5: 100 requests per minute per IP, returning 429 with
a `Retry-After` header. The limit is generous because researchers and
journalists should not need permission; it exists to make sustained
extraction visible, not to gate access.

The implementation is a fixed-window in-memory counter, keyed by hashed
IP (see `_logging.hash_ip`). On Vercel serverless, in-memory state is
per-function-instance, which means the limit is best-effort across
instances. That is acceptable for v1: the goal is to surface obvious
abuse, not to perfectly throttle distributed traffic. When sustained
traffic requires a stronger guarantee, we move to Vercel KV (deferred,
not in this PR).
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 100

_state_lock = Lock()
# {ip_hash: (window_start_epoch, count)}
_state: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))


def check(ip_hash: str, now: float | None = None) -> tuple[bool, int]:
    """Record a request from `ip_hash`, return `(allowed, retry_after)`.

    `retry_after` is seconds until the window resets; it is only
    meaningful when `allowed` is False.
    """
    current = time.time() if now is None else now
    with _state_lock:
        window_start, count = _state[ip_hash]
        if current - window_start >= WINDOW_SECONDS:
            # New window.
            _state[ip_hash] = (current, 1)
            return True, 0
        if count >= MAX_REQUESTS_PER_WINDOW:
            retry_after = max(1, int(WINDOW_SECONDS - (current - window_start)))
            return False, retry_after
        _state[ip_hash] = (window_start, count + 1)
        return True, 0


def reset() -> None:
    """Test helper. Not for production use."""
    with _state_lock:
        _state.clear()
