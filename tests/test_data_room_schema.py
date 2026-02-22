"""Tests for Data Room schema (Sprint 13)."""
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4


class TestDataRoomSchema:

    def test_data_room_router_exists(self):
        """Data Room API router should be importable."""
        from backend.src.api.data_room import router
        assert router is not None

    def test_schema_endpoint_exists(self):
        """GET /schema endpoint should exist."""
        from backend.src.api.data_room import router
        routes = [r.path for r in router.routes]
        assert "/schema" in routes

    def test_export_endpoint_exists(self):
        """POST /export endpoint should exist."""
        from backend.src.api.data_room import router
        routes = [r.path for r in router.routes]
        assert "/export" in routes

    def test_data_room_registered_in_main(self):
        """Data Room router should be registered in main app."""
        from backend.main import app
        paths = [r.path for r in app.routes]
        dr_paths = [p for p in paths if '/data-room' in p]
        assert len(dr_paths) > 0

    def test_export_service_has_datasets(self):
        """DataRoomExportService should have DATASETS defined."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        db = MagicMock()
        svc = DataRoomExportService(db, uuid4())
        schema = svc.get_schema()
        assert len(schema) >= 10
