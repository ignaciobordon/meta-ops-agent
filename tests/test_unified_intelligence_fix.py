"""Tests for unified intelligence service bug fixes (Sprint 13 Phase 0)."""
import pytest
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4


class TestUnifiedIntelligenceFix:

    def test_import_path_correct(self):
        """schema import uses correct singular path."""
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        assert UnifiedIntelligenceService is not None

    def test_analyze_is_sync(self):
        """analyze() is not a coroutine."""
        import inspect
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        assert not inspect.iscoroutinefunction(UnifiedIntelligenceService.analyze)

    def test_analyze_calls_router_sync(self):
        """generate() called without await."""
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        from backend.src.llm.schema import LLMResponse

        db = MagicMock()
        svc = UnifiedIntelligenceService(db, uuid4())
        svc.gather_context = MagicMock(return_value={
            "brand_map": {"available": False},
            "ci_data": {"available": False},
            "saturation": {"available": False},
            "brain": {"available": False},
        })

        mock_response = LLMResponse(
            provider="test", model="test", content={},
            raw_text='[{"id":"opp-1","gap_id":"test","title":"T","description":"D","strategy":"S","priority":"high","estimated_impact":0.5,"impact_reasoning":"R","identified_at":"2024-01-01"}]',
        )

        with patch('backend.src.services.unified_intelligence.LLMRouter') as MockRouter:
            MockRouter.return_value.generate.return_value = mock_response
            result = svc.analyze()

        assert len(result) == 1
        assert result[0]["gap_id"] == "test"

    def test_analyze_uses_raw_text(self):
        """response.raw_text used, not response.content."""
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        from backend.src.llm.schema import LLMResponse

        db = MagicMock()
        svc = UnifiedIntelligenceService(db, uuid4())
        svc.gather_context = MagicMock(return_value={
            "brand_map": {"available": False},
            "ci_data": {"available": False},
            "saturation": {"available": False},
            "brain": {"available": False},
        })

        mock_response = LLMResponse(
            provider="test", model="test",
            content={"not": "used"},
            raw_text='[]',
        )

        with patch('backend.src.services.unified_intelligence.LLMRouter') as MockRouter:
            MockRouter.return_value.generate.return_value = mock_response
            result = svc.analyze()

        assert result == []

    def test_parse_opportunities_json_array(self):
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        result = UnifiedIntelligenceService._parse_opportunities('[{"id": "1"}, {"id": "2"}]')
        assert len(result) == 2

    def test_parse_opportunities_markdown_fenced(self):
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        text = '```json\n[{"id": "1"}]\n```'
        result = UnifiedIntelligenceService._parse_opportunities(text)
        assert len(result) == 1

    def test_parse_opportunities_empty(self):
        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        result = UnifiedIntelligenceService._parse_opportunities("no valid json here")
        assert result == []

    def test_feature_memory_column_name(self):
        from backend.src.database.models import FeatureMemory
        columns = [c.name for c in FeatureMemory.__table__.columns]
        assert 'samples' in columns
        assert 'sample_count' not in columns
