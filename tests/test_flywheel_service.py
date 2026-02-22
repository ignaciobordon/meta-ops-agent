"""Tests for FlywheelService (Sprint 13)."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4
from datetime import datetime


class TestFlywheelService:

    def _make_service(self):
        from backend.src.services.flywheel_service import FlywheelService
        db = MagicMock()
        org_id = uuid4()
        return FlywheelService(db, org_id), db

    def test_create_run_creates_steps(self):
        """create_run should create 8 steps."""
        svc, db = self._make_service()

        # Mock db.add and db.flush
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)
        db.flush.return_value = None

        run = svc.create_run({})
        # Should have added 1 run + 8 steps = 9 objects
        assert len(added_objects) >= 9
        assert run.status == "queued"

    def test_steps_in_correct_order(self):
        """Steps should be in order 1-8."""
        svc, db = self._make_service()

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)
        db.flush.return_value = None

        svc.create_run({})

        from backend.src.database.models import FlywheelStep
        steps = [o for o in added_objects if isinstance(o, FlywheelStep)]
        orders = [s.step_order for s in steps]
        assert orders == list(range(1, 9))

    def test_step_names_correct(self):
        """Steps should have expected names."""
        svc, db = self._make_service()
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)
        db.flush.return_value = None

        svc.create_run({})

        from backend.src.database.models import FlywheelStep
        steps = [o for o in added_objects if isinstance(o, FlywheelStep)]
        names = [s.step_name for s in steps]
        assert "meta_sync" in names
        assert "brain_analysis" in names
        assert "unified_intelligence" in names
        assert "export" in names

    def test_get_run_with_steps_not_found(self):
        """get_run_with_steps returns None for missing run."""
        svc, db = self._make_service()
        db.query.return_value.filter.return_value.first.return_value = None
        result = svc.get_run_with_steps(uuid4())
        assert result is None

    def test_list_runs(self):
        """list_runs calls query with correct filters."""
        svc, db = self._make_service()
        mock_query = MagicMock()
        db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = svc.list_runs(10)
        assert result == []
        mock_query.limit.assert_called_with(10)

    def test_models_exist(self):
        """FlywheelRun and FlywheelStep models exist."""
        from backend.src.database.models import FlywheelRun, FlywheelStep
        assert FlywheelRun.__tablename__ == "flywheel_runs"
        assert FlywheelStep.__tablename__ == "flywheel_steps"
