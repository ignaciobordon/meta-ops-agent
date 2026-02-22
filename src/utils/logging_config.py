import functools
import os
import re
import sys
import uuid
from contextvars import ContextVar
from loguru import logger

# ContextVar for global trace_id propagation
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system-init")

# Patterns for secret masking in logs
_SECRET_PATTERNS = [
    (re.compile(r'(Bearer\s+)[A-Za-z0-9\-_\.]+'), r'\1[REDACTED]'),
    (re.compile(r'(api[_-]?key["\s:=]+)[A-Za-z0-9\-_\.]{8,}', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(secret["\s:=]+)[A-Za-z0-9\-_\.]{8,}', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(password["\s:=]+)[^\s,}"]+', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(token["\s:=]+)[A-Za-z0-9\-_\.]{8,}', re.IGNORECASE), r'\1[REDACTED]'),
]


def _mask_secrets(message: str) -> str:
    """Mask sensitive values in log messages."""
    for pattern, replacement in _SECRET_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


def set_trace_id(trace_id: str = None):
    """Sets a new trace_id for the current context."""
    new_id = trace_id or str(uuid.uuid4())
    trace_id_var.set(new_id)
    return new_id

def get_trace_id():
    """Returns the current trace_id from the context."""
    return trace_id_var.get()


def _secret_filter(record):
    """Loguru filter that masks secrets in log messages."""
    record["message"] = _mask_secrets(record["message"])
    return True


def setup_logging(log_level="INFO", json_format=None):
    """Configures loguru to include trace_id in all logs.

    Args:
        log_level: Minimum log level.
        json_format: If True, output JSON-serialized logs. Auto-detects production if None.
    """
    if json_format is None:
        json_format = os.environ.get("ENVIRONMENT", "development") == "production"
    logger.remove()

    if json_format:
        # JSON mode for production — structured log aggregation
        logger.add(
            sys.stdout,
            serialize=True,
            level=log_level,
            filter=_secret_filter,
        )
    else:
        # Human-readable format for development
        log_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>trace_id={extra[trace_id]}</cyan> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )

        logger.add(
            sys.stdout,
            format=log_format,
            level=log_level,
            colorize=True,
            filter=_secret_filter,
        )

    os.makedirs("logs", exist_ok=True)
    logger.add(
        "logs/system.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "trace_id={extra[trace_id]} | "
            "{name}:{function}:{line} - {message}"
        ),
        level=log_level,
        rotation="10 MB",
        filter=_secret_filter,
    )

# Inject trace_id into all log records dynamically
# Note: Do NOT bind at module level - trace_id must be resolved at runtime
# Use logger.bind(trace_id=get_trace_id()) in your code, or use @with_trace decorator

# Middleware-like wrapper to inject trace_id into context
def with_trace(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not get_trace_id() or get_trace_id() == "system-init":
            set_trace_id()
        # Bind the current trace_id to the logger for this execution
        bound_logger = logger.bind(trace_id=get_trace_id())
        return func(bound_logger, *args, **kwargs)
    return wrapper

if __name__ == "__main__":
    setup_logging()
    set_trace_id("test-trace-123")
    logger.info("Logging system initialized with trace_id")
