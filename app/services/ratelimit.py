from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Tiny in-memory sliding-window limiter, keyed by an arbitrary string (user id)."""

    def __init__(self, limit: int, window_seconds: float = 3600.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True
