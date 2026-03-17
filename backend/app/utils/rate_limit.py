import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, DefaultDict

from fastapi import HTTPException, Request

from ..config import get_settings

settings = get_settings()


class SlidingWindowRateLimiter:
    """
    In-memory sliding window rate limiter keyed by requester identity.
    This avoids an extra Redis dependency while providing coarse protection
    for the public FastAPI endpoints.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.time()
        with self._lock:
            window = self._hits[key]
            while window and now - window[0] > self.window_seconds:
                window.popleft()
            if len(window) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Please wait a moment and try again.",
                )
            window.append(now)


_rate_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


async def enforce_rate_limit(request: Request) -> None:
    """
    FastAPI dependency that enforces per-path rate limits keyed by the caller IP.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{request.url.path}"
    _rate_limiter.check(key)
