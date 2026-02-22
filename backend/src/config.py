"""
Sprint 3 – BLOQUE 1: Centralized Configuration
All settings loaded from environment variables via pydantic-settings.
No os.getenv() anywhere else in the codebase — import `settings` from here.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """
    Single source of truth for all application configuration.
    pydantic-settings reads from env vars (and .env file) automatically.
    """

    # ── Environment ────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    APP_VERSION: str = "1.0.0"

    # ── API Keys ───────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    META_APP_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    META_TOKEN_ENCRYPTION_KEY: Optional[str] = None
    META_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/meta/oauth/callback"
    META_OAUTH_SCOPES: str = "ads_read"

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./meta_ops.db"

    # ── JWT Authentication ─────────────────────────────────────────────────
    # Unified: auth.py used JWT_SECRET, config.py used JWT_SECRET_KEY.
    # Now both names resolve to the same field via alias.
    JWT_SECRET: str = Field(
        default="dev-secret-change-in-production",
        alias="JWT_SECRET",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MINUTES: int = 60
    JWT_REFRESH_TTL_DAYS: int = 7
    JWT_EXPIRATION_HOURS: int = 24  # kept for backwards compat

    # ── Password ───────────────────────────────────────────────────────────
    PASSWORD_SALT: str = "meta-ops-salt-v1"

    # ── Bootstrap ──────────────────────────────────────────────────────────
    BOOTSTRAP_ENABLED: bool = True

    # ── Stripe Billing ──────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRO_PRICE_ID: str = ""

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Celery ────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = ""  # Defaults to REDIS_URL if empty
    CELERY_RESULT_BACKEND: str = ""  # Defaults to REDIS_URL if empty

    # ── API Rate Limiting ──────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 100

    # ── Operator Safety ────────────────────────────────────────────────────
    OPERATOR_ARMED: bool = False

    # ── ChromaDB ───────────────────────────────────────────────────────────
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_data"

    # ── Embedding Model ────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # ── CORS ──────────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:5173"

    # ── LLM Router ────────────────────────────────────────────────────────
    LLM_DEFAULT_PROVIDER: str = ""            # anthropic | openai (auto-detected if empty)
    LLM_FALLBACK_PROVIDER: str = "openai"     # fallback when primary fails
    LLM_TIMEOUT_SECONDS: int = 120
    LLM_PROVIDER: str = ""                    # Legacy compat (Sprint <=8)

    # ── CI AutoLoop ────────────────────────────────────────────────────────
    CI_AUTOLOOP_ENABLED: bool = True
    CI_INGEST_INTERVAL_MINUTES_TRIAL: int = 1440   # daily
    CI_INGEST_INTERVAL_MINUTES_PRO: int = 180      # 3 hours
    CI_DETECT_INTERVAL_MINUTES_TRIAL: int = 1440   # daily
    CI_DETECT_INTERVAL_MINUTES_PRO: int = 60       # 1 hour
    CI_MAX_COMPETITORS_TRIAL: int = 20
    CI_MAX_COMPETITORS_PRO: int = 50
    CI_MAX_ITEMS_PER_RUN_TRIAL: int = 500
    CI_MAX_ITEMS_PER_RUN_PRO: int = 2000

    # ── CI Source Feature Flags ──────────────────────────────────────────────
    # Only Nivel A (ads library) + Nivel B (web crawl) enabled for P0.
    # Social scraping stays behind feature flag OFF until Nivel C criteria met.
    CI_SOURCE_WEB_ENABLED: bool = True          # Nivel B: landing page crawling
    CI_SOURCE_META_ADS_ENABLED: bool = True      # Nivel A: Meta Ads Library
    CI_SOURCE_GOOGLE_ADS_ENABLED: bool = False   # Nivel A: Google Ads Transparency
    CI_SOURCE_TIKTOK_ENABLED: bool = False       # Nivel C: TikTok Creative Center
    CI_SOURCE_INSTAGRAM_ENABLED: bool = False    # Nivel C: requires partner/proxy
    CI_SOURCE_SOCIAL_SCRAPING_ENABLED: bool = False  # Nivel C: aggressive social

    # ── Meta Ad Library ────────────────────────────────────────────────────
    META_AD_LIBRARY_ACCESS_TOKEN: str = ""  # Graph API token for Ad Library (ads_read permission)

    # ── Logging ────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        populate_by_name=True,
    )

    def validate_production_secrets(self):
        """Fail-fast if critical secrets are missing in production."""
        if self.ENVIRONMENT != "production":
            return

        missing = []

        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if not self.META_APP_ID:
            missing.append("META_APP_ID")
        if not self.META_APP_SECRET:
            missing.append("META_APP_SECRET")
        if not self.META_TOKEN_ENCRYPTION_KEY:
            missing.append("META_TOKEN_ENCRYPTION_KEY")
        if self.JWT_SECRET == "dev-secret-change-in-production":
            missing.append("JWT_SECRET (using dev default)")
        if self.PASSWORD_SALT == "meta-ops-salt-v1":
            missing.append("PASSWORD_SALT (using dev default)")

        if missing:
            raise ValueError(
                f"Missing required secrets for production: {', '.join(missing)}. "
                "Set these environment variables before deploying."
            )


# Global settings instance
settings = Settings()

# ── Legacy LLM_PROVIDER compat ──────────────────────────────────────────
# If LLM_DEFAULT_PROVIDER is empty, fall back to legacy LLM_PROVIDER env var.
if not settings.LLM_DEFAULT_PROVIDER:
    if settings.LLM_PROVIDER:
        import logging as _logging
        _logging.getLogger("meta_ops.config").warning(
            "deprecated_env: LLM_PROVIDER is deprecated, use LLM_DEFAULT_PROVIDER instead. "
            "Falling back to LLM_PROVIDER=%s", settings.LLM_PROVIDER,
        )
        settings.LLM_DEFAULT_PROVIDER = settings.LLM_PROVIDER
    elif settings.ANTHROPIC_API_KEY:
        settings.LLM_DEFAULT_PROVIDER = "anthropic"
    elif settings.OPENAI_API_KEY:
        settings.LLM_DEFAULT_PROVIDER = "openai"
    else:
        settings.LLM_DEFAULT_PROVIDER = "anthropic"  # safe default

# Validate on import if in production
if settings.ENVIRONMENT == "production":
    settings.validate_production_secrets()
