"""Tests for Flywheel API endpoints (Sprint 13)."""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4


class TestFlywheelAPI:

    def test_flywheel_router_exists(self):
        """Flywheel API router should be importable."""
        from backend.src.api.flywheel import router
        assert router is not None

    def test_flywheel_run_endpoint_exists(self):
        """POST /run endpoint should exist."""
        from backend.src.api.flywheel import router
        routes = [r.path for r in router.routes]
        assert "/run" in routes

    def test_flywheel_list_endpoint_exists(self):
        """GET /runs endpoint should exist."""
        from backend.src.api.flywheel import router
        routes = [r.path for r in router.routes]
        assert "/runs" in routes

    def test_flywheel_detail_endpoint_exists(self):
        """GET /runs/{run_id} endpoint should exist."""
        from backend.src.api.flywheel import router
        routes = [r.path for r in router.routes]
        assert "/runs/{run_id}" in routes

    def test_flywheel_retry_endpoint_exists(self):
        """POST retry endpoint should exist."""
        from backend.src.api.flywheel import router
        routes = [r.path for r in router.routes]
        retry_routes = [r for r in routes if "retry" in r]
        assert len(retry_routes) > 0

    def test_flywheel_registered_in_main(self):
        """Flywheel router should be registered in main app."""
        from backend.main import app
        paths = [r.path for r in app.routes]
        flywheel_paths = [p for p in paths if '/flywheel' in p]
        assert len(flywheel_paths) > 0
