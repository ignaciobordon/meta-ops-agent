"""Tests for Data Room export security (Sprint 13)."""
import io
import pytest
from unittest.mock import MagicMock
from uuid import uuid4
from openpyxl import load_workbook


class TestDataRoomSecurity:

    def test_sensitive_columns_defined(self):
        """SENSITIVE_COLUMNS should include token and password fields."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        assert "access_token_encrypted" in DataRoomExportService.SENSITIVE_COLUMNS
        assert "password_hash" in DataRoomExportService.SENSITIVE_COLUMNS
        assert "key_hash" in DataRoomExportService.SENSITIVE_COLUMNS

    def test_sanitize_removes_sensitive(self):
        """Sanitization should strip sensitive column values."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        svc = DataRoomExportService(MagicMock(), uuid4())
        val = svc._sanitize_value("secret_token_value", "access_token_encrypted")
        assert val != "secret_token_value"

    def test_sanitize_truncates_long_json(self):
        """JSON strings > 32KB should be truncated."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        svc = DataRoomExportService(MagicMock(), uuid4())
        long_json = '{"data": "' + 'x' * 40000 + '"}'
        val = svc._sanitize_value(long_json, "payload_json")
        assert len(str(val)) < 40000

    def test_max_json_cell_len(self):
        """MAX_JSON_CELL_LEN should be 32768."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        assert DataRoomExportService.MAX_JSON_CELL_LEN == 32768

    def test_no_sensitive_in_schema(self):
        """Schema should not expose sensitive column names."""
        from backend.src.services.data_room_export_service import DataRoomExportService
        svc = DataRoomExportService(MagicMock(), uuid4())
        schema = svc.get_schema()
        for ds in schema:
            name = ds.get("key", "") if isinstance(ds, dict) else str(ds)
            assert "token" not in name.lower()
            assert "password" not in name.lower()
