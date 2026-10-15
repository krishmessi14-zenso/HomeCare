"""Open-redirect protection and an in-memory login rate limiter."""
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse


def is_safe_redirect(target):
    """Only allow same-site relative paths such as /customer/dashboard."""
    if not target or not isinstance(target, str):
        return False
    if "\\" in target or any(ord(c) < 32 for c in target):
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/") and not target.startswith("//")


class RateLimiter:
    """Sliding-window failed-attempt counter (per process).

    Limitation: state is in memory, so it resets on restart and is not shared
    between multiple worker processes. See docs/ARCHITECTURE.md for the
    production plan (Redis / Flask-Limiter).
    """

    def __init__(self, max_attempts=5, window_seconds=900):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, now):
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, key):
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_attempts

    def record_failure(self, key):
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)
