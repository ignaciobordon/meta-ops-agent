"""Global configuration for the Web Intelligence Engine."""
from pydantic import BaseModel


class CrawlerConfig(BaseModel):
    """Top-level config for crawl runs."""

    max_pages_per_domain: int = 50
    max_depth: int = 3
    request_timeout: float = 15.0
    max_retries: int = 2
    retry_backoff: float = 1.0
    concurrency_per_domain: int = 3
    global_concurrency: int = 10
    min_delay: float = 1.0
    max_delay: float = 3.0
    respect_robots: bool = True
    default_user_agent: str = (
        "Mozilla/5.0 (compatible; MetaOpsBot/1.0; +https://metaops.dev/bot)"
    )
    # Content limits
    max_response_bytes: int = 5 * 1024 * 1024  # 5 MB
    allowed_content_types: list[str] = [
        "text/html",
        "application/xhtml+xml",
    ]


DEFAULT_CONFIG = CrawlerConfig()
