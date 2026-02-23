"""
Structured authentication event logging.
JSON-formatted logs for security monitoring and auditing.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from src.utils.logging_config import logger, get_trace_id


class AuthEvent:
    """Standard auth event types."""
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILED = "auth.login.failed"
    REFRESH_SUCCESS = "auth.refresh.success"
    REFRESH_FAILED = "auth.refresh.failed"
    BOOTSTRAP_CREATED = "auth.bootstrap.created"
    SESSION_REVOKED = "auth.session.revoked"
    TOKEN_REVOKED = "auth.token.revoked"
    LOGOUT = "auth.logout"
    SUSPICIOUS_ACTIVITY = "auth.suspicious"


def extract_client_ip(request) -> str:
    """Extract client IP from FastAPI request.

    Only trusts X-Forwarded-For when TRUSTED_PROXY_DEPTH > 0 to prevent
    IP spoofing attacks against rate limiting and audit logging.
    """
    if request is None:
        return "unknown"
    from backend.src.config import settings
    if settings.TRUSTED_PROXY_DEPTH > 0:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",")]
            idx = max(0, len(parts) - settings.TRUSTED_PROXY_DEPTH)
            return parts[idx]
    return request.client.host if request.client else "unknown"


def extract_device_info(user_agent: Optional[str]) -> str:
    """Parse user agent into human-readable device info without external libraries."""
    if not user_agent:
        return "Unknown Device"

    # Extract browser
    browser = "Unknown"
    if match := re.search(r"(Chrome|Firefox|Safari|Edge|Opera)[/ ]([\d.]+)", user_agent):
        browser = f"{match.group(1)} {match.group(2)}"
    elif "MSIE" in user_agent or "Trident" in user_agent:
        browser = "Internet Explorer"

    # Extract OS
    os_name = "Unknown OS"
    if "Windows" in user_agent:
        os_name = "Windows"
    elif "Mac OS X" in user_agent:
        os_name = "macOS"
    elif "Linux" in user_agent:
        os_name = "Linux"
    elif "Android" in user_agent:
        os_name = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        os_name = "iOS"

    return f"{browser} on {os_name}"


def hash_token(token: str) -> str:
    """Hash a token (refresh token) for secure storage. SHA-256 one-way."""
    return hashlib.sha256(token.encode()).hexdigest()


def log_auth_event(
    event: str,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    reason: Optional[str] = None,
    request=None,
    extra_data: Optional[dict] = None,
):
    """
    Log a structured authentication event as JSON.

    Args:
        event: Event type (use AuthEvent constants)
        user_email: User email (if known)
        user_id: User ID (if known)
        ip: Client IP address (extracted from request if not provided)
        user_agent: User agent string (extracted from request if not provided)
        reason: Reason for event (e.g., "invalid_password", "token_expired")
        request: FastAPI Request object (extracts IP/UA if provided)
        extra_data: Additional context data
    """
    if request:
        if not ip:
            ip = extract_client_ip(request)
        if not user_agent:
            user_agent = request.headers.get("User-Agent", "unknown")

    event_data = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": get_trace_id(),
        "user_email": user_email,
        "user_id": user_id,
        "ip": ip,
        "user_agent": user_agent,
        "reason": reason,
    }

    if extra_data:
        event_data["extra"] = extra_data

    # Remove None values for cleaner output
    event_data = {k: v for k, v in event_data.items() if v is not None}

    logger.bind(trace_id=get_trace_id()).info(f"AUTH_EVENT | {json.dumps(event_data)}")
