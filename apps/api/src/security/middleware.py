"""Security middleware — rate limiting, CSRF, security headers."""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable

import structlog
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger(__name__)


class RateLimiter:
    """Token bucket rate limiter — in-memory (use Redis in multi-process prod)."""

    def __init__(self, requests_per_minute: int = 60) -> None:
        self._rpm = requests_per_minute
        self._window = 60.0
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        bucket = self._buckets[key]

        # Remove timestamps outside the window
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()

        if len(bucket) >= self._rpm:
            oldest = bucket[0]
            retry_after = int(self._window - (now - oldest)) + 1
            return False, retry_after

        bucket.append(now)
        return True, 0


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response."""

    _SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        response = await call_next(request)
        for header, value in self._SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP + per-user rate limiting."""

    def __init__(
        self,
        app: object,
        global_rpm: int = 300,
        api_rpm: int = 60,
        auth_rpm: int = 10,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._global = RateLimiter(global_rpm)
        self._api = RateLimiter(api_rpm)
        self._auth = RateLimiter(auth_rpm)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Stricter limits on auth endpoints
        if "/auth/" in path or "/login" in path:
            allowed, retry_after = self._auth.is_allowed(client_ip)
        elif path.startswith("/api/"):
            allowed, retry_after = self._api.is_allowed(client_ip)
        else:
            allowed, retry_after = self._global.is_allowed(client_ip)

        if not allowed:
            log.warning("rate_limit_exceeded", ip=client_ip, path=path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        return response


def generate_csrf_token(secret: str, user_id: str) -> str:
    """Generate a CSRF token tied to a user session."""
    nonce = secrets.token_hex(16)
    sig = hmac.new(
        secret.encode(),
        f"{user_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{sig}"


def verify_csrf_token(secret: str, user_id: str, token: str) -> bool:
    """Verify a CSRF token."""
    try:
        nonce, sig = token.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{user_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)
