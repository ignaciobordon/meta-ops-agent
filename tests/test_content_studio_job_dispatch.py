"""
Tests for Content Studio job dispatch integration.
6 tests covering QUEUE_ROUTING, _JOB_TIMEOUT, _LLM_JOB_TYPES, and _dispatch behavior.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.src.jobs.queue import QUEUE_ROUTING
from backend.src.jobs.task_runner import _JOB_TIMEOUT, _LLM_JOB_TYPES, _dispatch


# ── Tests 1-4: Constants and routing ──────────────────────────────────────────


def test_queue_routing_includes_content_studio():
    """QUEUE_ROUTING must contain the 'content_studio_generate' key."""
    assert "content_studio_generate" in QUEUE_ROUTING


def test_queue_routing_maps_to_llm():
    """content_studio_generate must route to the 'llm' queue."""
    assert QUEUE_ROUTING["content_studio_generate"] == "llm"


def test_job_timeout_content_studio():
    """content_studio_generate must have a 240-second timeout."""
    assert _JOB_TIMEOUT["content_studio_generate"] == 240


def test_llm_job_types_includes_content_studio():
    """content_studio_generate must be in _LLM_JOB_TYPES for LLM error classification."""
    assert "content_studio_generate" in _LLM_JOB_TYPES


# ── Tests 5-6: _dispatch behavior ────────────────────────────────────────────


@patch("backend.src.services.content_creator_service.generate_pack")
def test_dispatch_content_studio_calls_generate_pack(mock_generate_pack):
    """_dispatch('content_studio_generate', ...) calls generate_pack with correct pack_id."""
    pack_id = "00000000-0000-0000-0000-000000000099"

    mock_job_run = MagicMock()
    mock_job_run.payload_json = {"pack_id": pack_id}
    mock_job_run.org_id = "00000000-0000-0000-0000-000000000001"

    mock_db = MagicMock()

    _dispatch("content_studio_generate", mock_job_run, mock_db)

    mock_generate_pack.assert_called_once_with(pack_id, mock_db)


def test_dispatch_content_studio_requires_pack_id():
    """_dispatch('content_studio_generate', ...) raises ValueError when pack_id is missing."""
    mock_job_run = MagicMock()
    mock_job_run.payload_json = {}
    mock_job_run.org_id = "00000000-0000-0000-0000-000000000001"

    mock_db = MagicMock()

    with pytest.raises(ValueError, match="requires pack_id"):
        _dispatch("content_studio_generate", mock_job_run, mock_db)
