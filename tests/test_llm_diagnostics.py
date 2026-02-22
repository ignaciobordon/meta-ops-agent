"""
Sprint 10 -- LLM Diagnostics Endpoint Tests.
Tests the admin-only GET /api/system/llm/diagnostics endpoint.
5 tests covering response shape, key-safety, router readiness, breaker state, env source.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from fastapi.testclient import TestClient
from backend.main import app
from backend.src.database.models import Base
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_admin


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def override_db(db_engine):
    """Override get_db to use the in-memory SQLite engine."""
    SessionLocal = sessionmaker(bind=db_engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(override_db):
    """TestClient with get_current_user and require_admin overridden."""

    def fake_user():
        return {"user_id": "test-user-id", "org_id": "test-org-id", "role": "admin"}

    def fake_admin():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_admin] = fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Shared mock helpers ──────────────────────────────────────────────────────


def _mock_circuit_breaker(provider, org_id, **kwargs):
    """Return a MagicMock pretending to be a PersistentCircuitBreaker."""
    cb = MagicMock()
    cb.state = "closed"
    cb.provider = provider
    return cb


def _mock_rate_limiter(provider, org_id, **kwargs):
    """Return a MagicMock pretending to be a ProviderRateLimiter."""
    rl = MagicMock()
    rl.tokens_remaining.return_value = 100
    rl.provider = provider
    return rl


# Decorators shared by every test: isolate Redis-backed classes.
_COMMON_PATCHES = [
    patch(
        "backend.src.api.system.PersistentCircuitBreaker",
        side_effect=_mock_circuit_breaker,
    ),
    patch(
        "backend.src.api.system.ProviderRateLimiter",
        side_effect=_mock_rate_limiter,
    ),
]


def _apply_common_patches(func):
    """Stack the shared patches onto a test function."""
    for p in reversed(_COMMON_PATCHES):
        func = p(func)
    return func


# ── 1. test_diagnostics_returns_200 ──────────────────────────────────────────


class TestDiagnosticsReturns200:

    @patch("backend.src.llm.router.get_llm_router")
    @patch("backend.src.api.system.ProviderRateLimiter", side_effect=_mock_rate_limiter)
    @patch("backend.src.api.system.PersistentCircuitBreaker", side_effect=_mock_circuit_breaker)
    def test_diagnostics_returns_200(
        self, mock_cb, mock_rl, mock_router, client
    ):
        """GET /api/system/llm/diagnostics returns 200 with all expected fields."""
        router_instance = MagicMock()
        router_instance.providers = {"anthropic": MagicMock()}
        mock_router.return_value = router_instance

        resp = client.get("/api/system/llm/diagnostics")
        assert resp.status_code == 200

        data = resp.json()
        expected_fields = {
            "default_provider",
            "fallback_provider",
            "openai_key_present",
            "anthropic_key_present",
            "timeout_seconds",
            "router_ready",
            "breaker_state",
            "rate_limit_status",
            "effective_env_source",
        }
        assert expected_fields == set(data.keys())


# ── 2. test_diagnostics_never_exposes_keys ───────────────────────────────────


class TestDiagnosticsNeverExposesKeys:

    @patch("backend.src.llm.router.get_llm_router")
    @patch("backend.src.api.system.ProviderRateLimiter", side_effect=_mock_rate_limiter)
    @patch("backend.src.api.system.PersistentCircuitBreaker", side_effect=_mock_circuit_breaker)
    @patch("backend.src.api.system.settings")
    def test_diagnostics_never_exposes_keys(
        self, mock_settings, mock_cb, mock_rl, mock_router, client
    ):
        """Response has openai_key_present / anthropic_key_present as bools,
        and no raw API key values appear anywhere in the response body."""
        fake_openai_key = "sk-FAKEOPENAIKEY1234567890abcdef"
        fake_anthropic_key = "sk-ant-FAKEANTHROPICKEY1234567890"

        mock_settings.OPENAI_API_KEY = fake_openai_key
        mock_settings.ANTHROPIC_API_KEY = fake_anthropic_key
        mock_settings.LLM_DEFAULT_PROVIDER = "anthropic"
        mock_settings.LLM_FALLBACK_PROVIDER = "openai"
        mock_settings.LLM_TIMEOUT_SECONDS = 30
        mock_settings.LLM_PROVIDER = ""

        router_instance = MagicMock()
        router_instance.providers = {"anthropic": MagicMock()}
        mock_router.return_value = router_instance

        resp = client.get("/api/system/llm/diagnostics")
        assert resp.status_code == 200

        data = resp.json()
        raw_text = resp.text

        # Key-present fields must be booleans
        assert isinstance(data["openai_key_present"], bool)
        assert isinstance(data["anthropic_key_present"], bool)
        assert data["openai_key_present"] is True
        assert data["anthropic_key_present"] is True

        # Raw key values must NOT appear anywhere in the serialised response
        assert fake_openai_key not in raw_text
        assert fake_anthropic_key not in raw_text


# ── 3. test_diagnostics_router_ready_with_provider ───────────────────────────


class TestDiagnosticsRouterReadyWithProvider:

    @patch("backend.src.llm.router.get_llm_router")
    @patch("backend.src.api.system.ProviderRateLimiter", side_effect=_mock_rate_limiter)
    @patch("backend.src.api.system.PersistentCircuitBreaker", side_effect=_mock_circuit_breaker)
    def test_diagnostics_router_ready_with_provider(
        self, mock_cb, mock_rl, mock_router, client
    ):
        """When get_llm_router returns a router with providers, router_ready=True."""
        router_instance = MagicMock()
        router_instance.providers = {"anthropic": MagicMock(), "openai": MagicMock()}
        mock_router.return_value = router_instance

        resp = client.get("/api/system/llm/diagnostics")
        assert resp.status_code == 200

        data = resp.json()
        assert data["router_ready"] is True


# ── 4. test_diagnostics_breaker_state_present ────────────────────────────────


class TestDiagnosticsBreakerStatePresent:

    @patch("backend.src.llm.router.get_llm_router")
    @patch("backend.src.api.system.ProviderRateLimiter", side_effect=_mock_rate_limiter)
    @patch("backend.src.api.system.PersistentCircuitBreaker", side_effect=_mock_circuit_breaker)
    def test_diagnostics_breaker_state_present(
        self, mock_cb, mock_rl, mock_router, client
    ):
        """breaker_state dict has 'anthropic' and 'openai' keys."""
        router_instance = MagicMock()
        router_instance.providers = {}
        mock_router.return_value = router_instance

        resp = client.get("/api/system/llm/diagnostics")
        assert resp.status_code == 200

        breaker_state = resp.json()["breaker_state"]
        assert isinstance(breaker_state, dict)
        assert "anthropic" in breaker_state
        assert "openai" in breaker_state
        # Values come from our mocked cb.state = "closed"
        assert breaker_state["anthropic"] == "closed"
        assert breaker_state["openai"] == "closed"


# ── 5. test_diagnostics_effective_env_source_shows_config ────────────────────


class TestDiagnosticsEffectiveEnvSourceShowsConfig:

    @patch("backend.src.llm.router.get_llm_router")
    @patch("backend.src.api.system.ProviderRateLimiter", side_effect=_mock_rate_limiter)
    @patch("backend.src.api.system.PersistentCircuitBreaker", side_effect=_mock_circuit_breaker)
    def test_diagnostics_effective_env_source_shows_config(
        self, mock_cb, mock_rl, mock_router, client
    ):
        """effective_env_source dict has LLM_DEFAULT_PROVIDER and LLM_FALLBACK_PROVIDER keys."""
        router_instance = MagicMock()
        router_instance.providers = {}
        mock_router.return_value = router_instance

        resp = client.get("/api/system/llm/diagnostics")
        assert resp.status_code == 200

        env_source = resp.json()["effective_env_source"]
        assert isinstance(env_source, dict)
        assert "LLM_DEFAULT_PROVIDER" in env_source
        assert "LLM_FALLBACK_PROVIDER" in env_source
