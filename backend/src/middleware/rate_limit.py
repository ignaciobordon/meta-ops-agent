"""
FASE 3.1: API Rate Limiting Middleware
Implements token bucket algorithm for request rate limiting.
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Any, Dict, Tuple
from time import time
import asyncio


class RateLimiter:
    """
    Token bucket rate limiter.

    Limits requests per client using IP address or API key.
    Default: 100 requests per minute per client.
    """

    def __init__(self, rate: int = 100, window: int = 60):
        """
        Args:
            rate: Maximum requests allowed in window
            window: Time window in seconds
        """
        self.rate = rate
        self.window = window
        # Storage: {client_id: (tokens, last_refill_time)}
        self.clients: Dict[str, Tuple[float, float]] = {}
        self.lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed for client.

        Returns:
            (is_allowed, headers) where headers contains rate limit info
        """
        async with self.lock:
            now = time()

            # Cleanup stale clients (not seen in 2x window)
            stale_threshold = now - (self.window * 2)
            stale_keys = [k for k, (_, last) in self.clients.items() if last < stale_threshold]
            for k in stale_keys:
                del self.clients[k]

            if client_id not in self.clients:
                # New client - give full bucket
                self.clients[client_id] = (self.rate - 1, now)
                return True, self._get_headers(self.rate - 1, now)

            tokens, last_refill = self.clients[client_id]

            # Refill tokens based on time elapsed
            time_passed = now - last_refill
            refill_amount = (time_passed / self.window) * self.rate
            tokens = min(self.rate, tokens + refill_amount)

            if tokens >= 1:
                # Allow request and consume token
                self.clients[client_id] = (tokens - 1, now)
                return True, self._get_headers(int(tokens - 1), now)
            else:
                # Rate limit exceeded
                self.clients[client_id] = (tokens, last_refill)
                return False, self._get_headers(0, now, retry_after=max(1, int(self.window - time_passed)))

    def _get_headers(self, remaining: int, now: float, retry_after: int = None) -> Dict[str, str]:
        """Generate rate limit headers for response."""
        headers = {
            "X-RateLimit-Limit": str(self.rate),
            "X-RateLimit-Remaining": str(max(0, remaining)),
            "X-RateLimit-Reset": str(int(now + self.window))
        }
        if retry_after:
            headers["Retry-After"] = str(retry_after)
        return headers


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.

    Usage:
        app.add_middleware(RateLimitMiddleware, rate=100, window=60)
    """

    def __init__(self, app, rate: int = 100, window: int = 60, exclude_paths: list = None):
        super().__init__(app)
        self.limiter = RateLimiter(rate, window)
        self.exclude_paths = exclude_paths or ["/api/health", "/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for excluded paths (prefix match)
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # Identify client (prefer API key, fallback to IP)
        client_id = self._get_client_id(request)

        # Check rate limit
        is_allowed, rate_headers = await self.limiter.is_allowed(client_id)

        if not is_allowed:
            # Rate limit exceeded
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {self.limiter.rate} requests per {self.limiter.window} seconds",
                    "retry_after": rate_headers.get("Retry-After", self.limiter.window)
                },
                headers=rate_headers
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers to response
        for header, value in rate_headers.items():
            response.headers[header] = value

        return response

    def _get_client_id(self, request: Request) -> str:
        """Extract client identifier from request.

        Priority: authenticated user > API key > IP address.
        Authenticated users are rate-limited by user_id+org_id, not IP.
        """
        # Priority 1: Authenticated user from JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from backend.src.middleware.auth import decode_token
                payload = decode_token(auth_header[7:])
                user_id = payload.get("sub", "")
                org_id = payload.get("org_id", "")
                if user_id:
                    return f"user:{org_id}:{user_id}"
            except Exception:
                pass  # Fall through to IP-based identification

        # Priority 2: API key from header (hash for privacy)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            import hashlib
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return f"key:{key_hash}"

        # Priority 3: Client IP address (respects TRUSTED_PROXY_DEPTH)
        from backend.src.utils.auth_events import extract_client_ip
        client_ip = extract_client_ip(request)

        return f"ip:{client_ip}"


class LoginRateLimiter:
    """
    Dedicated rate limiter for login attempts.
    Per-IP, 5 attempts per 300 seconds (5 minutes).
    Resets on successful login.
    """

    def __init__(self, max_attempts: int = 5, window: int = 300):
        self.max_attempts = max_attempts
        self.window = window
        self.attempts: Dict[str, list] = {}
        self.lock = asyncio.Lock()

    async def is_allowed(self, ip: str) -> Tuple[bool, Dict[str, str]]:
        """Check if login attempt is allowed for this IP."""
        async with self.lock:
            now = time()
            cutoff = now - self.window

            if ip in self.attempts:
                self.attempts[ip] = [t for t in self.attempts[ip] if t > cutoff]
            else:
                self.attempts[ip] = []

            if len(self.attempts[ip]) >= self.max_attempts:
                oldest = self.attempts[ip][0]
                retry_after = int(oldest + self.window - now)
                return False, {
                    "X-RateLimit-Limit": str(self.max_attempts),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(max(1, retry_after)),
                }

            self.attempts[ip].append(now)
            remaining = self.max_attempts - len(self.attempts[ip])
            return True, {
                "X-RateLimit-Limit": str(self.max_attempts),
                "X-RateLimit-Remaining": str(remaining),
            }

    async def reset(self, ip: str):
        """Reset attempts for IP after successful login."""
        async with self.lock:
            self.attempts.pop(ip, None)


# Singleton for login rate limiting
login_limiter = LoginRateLimiter()
