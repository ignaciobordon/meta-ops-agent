"""
Sprint 10 -- Worker env-parity & config legacy-compat tests.

Validates:
  - docker-compose.yml env-var parity across all 4 worker/backend services
  - Legacy LLM_PROVIDER -> LLM_DEFAULT_PROVIDER fallback logic
  - Auto-detection of provider from API keys
  - Celery time-limit configuration
  - Queue routing for creatives_generate
"""
import os

# Set JWT_SECRET before any application imports that would trigger Settings()
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

import importlib
import pathlib
from unittest.mock import patch, MagicMock

import pytest
import yaml


# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCKER_COMPOSE_PATH = PROJECT_ROOT / "docker-compose.yml"

# The 4 services that must share env vars
WORKER_SERVICES = ["backend", "celery-default", "celery-io", "celery-llm"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_compose() -> dict:
    """Parse docker-compose.yml and return the full dict."""
    with open(DOCKER_COMPOSE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _service_env_keys(compose: dict, service_name: str) -> set[str]:
    """
    Return the set of env-var *names* for a given service.
    Handles both mapping (KEY: value) and list (- KEY=value) formats.
    """
    svc = compose["services"][service_name]
    env = svc.get("environment", {})

    if isinstance(env, dict):
        return set(env.keys())

    # list of "KEY=value" strings
    keys = set()
    for item in env:
        key = item.split("=", 1)[0]
        keys.add(key)
    return keys


def _create_fresh_settings(**env_overrides):
    """
    Create a brand-new Settings instance with the given env overrides.
    We must reload the config module to re-run the module-level legacy compat
    logic, so we patch os.environ *before* re-importing.
    """
    # Baseline: provide required defaults so Settings() doesn't fail
    baseline = {
        "JWT_SECRET": "test-secret-key-for-jwt-testing-only",
        "DATABASE_URL": "sqlite:///./test.db",
    }
    baseline.update(env_overrides)

    # Wipe any cached module so we get a fresh import
    import sys
    mods_to_remove = [k for k in sys.modules if k.startswith("backend.src.config")]
    for m in mods_to_remove:
        del sys.modules[m]

    with patch.dict(os.environ, baseline, clear=True):
        from backend.src.config import settings  # noqa: reimport intended
        return settings


# ── Docker-Compose Tests ─────────────────────────────────────────────────────

class TestDockerComposeEnvParity:
    """Ensure Sprint 10 env vars are present across all services."""

    def test_docker_compose_backend_has_openai_key(self):
        """backend service must declare OPENAI_API_KEY."""
        compose = _load_compose()
        backend_keys = _service_env_keys(compose, "backend")
        assert "OPENAI_API_KEY" in backend_keys, (
            "OPENAI_API_KEY missing from backend service in docker-compose.yml"
        )

    @pytest.mark.parametrize("var", [
        "LLM_DEFAULT_PROVIDER",
        "LLM_FALLBACK_PROVIDER",
        "LLM_TIMEOUT_SECONDS",
    ])
    def test_docker_compose_all_services_have_llm_vars(self, var: str):
        """All 4 services must declare the Sprint-10 LLM env vars."""
        compose = _load_compose()
        for service in WORKER_SERVICES:
            keys = _service_env_keys(compose, service)
            assert var in keys, (
                f"{var} missing from service '{service}' in docker-compose.yml"
            )

    def test_docker_compose_all_services_have_jwt_secret(self):
        """All 4 services must declare JWT_SECRET."""
        compose = _load_compose()
        for service in WORKER_SERVICES:
            keys = _service_env_keys(compose, service)
            assert "JWT_SECRET" in keys, (
                f"JWT_SECRET missing from service '{service}' in docker-compose.yml"
            )


# ── Config Legacy Compat Tests ───────────────────────────────────────────────

class TestConfigLegacyCompat:
    """
    Verify the module-level fallback logic in backend/src/config.py:
      LLM_DEFAULT_PROVIDER empty -> use LLM_PROVIDER -> auto-detect from keys
    """

    def test_config_legacy_llm_provider_fallback(self):
        """
        When LLM_DEFAULT_PROVIDER is empty and legacy LLM_PROVIDER='anthropic',
        settings.LLM_DEFAULT_PROVIDER must resolve to 'anthropic'.
        """
        s = _create_fresh_settings(
            LLM_DEFAULT_PROVIDER="",
            LLM_PROVIDER="anthropic",
            ANTHROPIC_API_KEY="",
            OPENAI_API_KEY="",
        )
        assert s.LLM_DEFAULT_PROVIDER == "anthropic", (
            f"Expected 'anthropic' from legacy LLM_PROVIDER, got '{s.LLM_DEFAULT_PROVIDER}'"
        )

    def test_config_auto_detection_anthropic(self):
        """
        When both LLM_DEFAULT_PROVIDER and LLM_PROVIDER are empty but
        ANTHROPIC_API_KEY is set, auto-detection should pick 'anthropic'.
        """
        s = _create_fresh_settings(
            LLM_DEFAULT_PROVIDER="",
            LLM_PROVIDER="",
            ANTHROPIC_API_KEY="sk-ant-test-key",
            OPENAI_API_KEY="",
        )
        assert s.LLM_DEFAULT_PROVIDER == "anthropic", (
            f"Expected auto-detected 'anthropic', got '{s.LLM_DEFAULT_PROVIDER}'"
        )


# ── Celery Config Tests ─────────────────────────────────────────────────────

class TestCeleryConfig:
    """Verify Celery time-limit configuration without requiring a real broker."""

    def test_celery_has_time_limits(self):
        """
        celery_app.conf must have task_soft_time_limit=120 and
        task_time_limit=180 (the global defaults).
        """
        # Mock kombu and celery so we don't need a live Redis
        mock_celery_cls = MagicMock()
        mock_app_instance = MagicMock()
        mock_celery_cls.return_value = mock_app_instance

        # Capture what conf.update() receives
        captured_conf = {}

        def fake_update(**kwargs):
            captured_conf.update(kwargs)

        mock_app_instance.conf.update.side_effect = fake_update

        with patch.dict("sys.modules", {
            "kombu": MagicMock(),
            "celery": MagicMock(Celery=mock_celery_cls),
        }):
            import sys
            # Clear cached module so we reimport with our mocks
            mods_to_remove = [
                k for k in sys.modules
                if k.startswith("backend.src.infra.celery_app")
            ]
            for m in mods_to_remove:
                del sys.modules[m]

            importlib.import_module("backend.src.infra.celery_app")

        assert captured_conf.get("task_soft_time_limit") == 120, (
            f"Expected task_soft_time_limit=120, got {captured_conf.get('task_soft_time_limit')}"
        )
        assert captured_conf.get("task_time_limit") == 180, (
            f"Expected task_time_limit=180, got {captured_conf.get('task_time_limit')}"
        )


# ── Queue Routing Tests ─────────────────────────────────────────────────────

class TestQueueRouting:
    """Validate QUEUE_ROUTING mappings from backend.src.jobs.queue."""

    def test_queue_routing_creatives_to_llm(self):
        """creatives_generate must be routed to the 'llm' queue."""
        from backend.src.jobs.queue import QUEUE_ROUTING

        assert "creatives_generate" in QUEUE_ROUTING, (
            "creatives_generate not found in QUEUE_ROUTING"
        )
        assert QUEUE_ROUTING["creatives_generate"] == "llm", (
            f"Expected 'llm' queue for creatives_generate, "
            f"got '{QUEUE_ROUTING['creatives_generate']}'"
        )
