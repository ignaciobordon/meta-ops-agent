"""
Sprint 10 -- Creatives LLM Job Tests.
Tests the fixed POST /api/creatives/generate endpoint and the
creatives_generate task runner dispatch.
8 tests covering: correct Factory/Scorer method calls, script_text
assembly, full mock flow, task runner dispatch, error cases, and
usage gate enforcement.
"""
import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Patch PG_UUID BEFORE any model imports so SQLite can handle UUID columns.
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
PG_UUID.impl = String(36)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-testing-only")

from backend.main import app
from backend.src.database.models import (
    Base,
    Organization,
    AdAccount,
    MetaConnection,
    Creative,
    ConnectionStatus,
    Subscription,
    PlanEnum,
    SubscriptionStatusEnum,
)
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user, require_any_authenticated


# ── Helpers: build mock AdScript and EvaluationScore ──────────────────────────


def _make_mock_adscript(hook="Stop scrolling.", body="This changes everything.", cta="Shop now."):
    """Return a MagicMock that quacks like src.schemas.factory.AdScript."""
    script = MagicMock()
    script.hook = hook
    script.body = body
    script.cta = cta
    script.framework = "PAS"
    script.target_avatar = "Busy professional"
    script.visual_brief = "Bright colors, product close-up"
    script.script_id = f"script-{uuid4().hex[:8]}"
    script.angle = "pain_point"
    script.brand_map_hash = "abc123"
    return script


def _make_mock_eval_score(overall=7.5):
    """Return a MagicMock that quacks like src.schemas.scoring.EvaluationScore."""
    score = MagicMock()
    score.overall_score = overall
    score.model_dump.return_value = {
        "hook_strength": {"score": 8.0, "reasoning": "Good hook"},
        "brand_alignment": {"score": 7.0, "reasoning": "On brand"},
        "clarity": {"score": 7.5, "reasoning": "Clear message"},
        "audience_fit": {"score": 7.0, "reasoning": "Fits avatar"},
        "cta_quality": {"score": 8.0, "reasoning": "Strong CTA"},
        "overall_score": overall,
        "overall_reasoning": "Solid creative",
    }
    return score


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
def org_id(db_session):
    """Create an Organization row and return its id."""
    _org_id = uuid4()
    org = Organization(
        id=_org_id,
        name="Creative Test Org",
        slug=f"cre-test-{_org_id.hex[:8]}",
        created_at=datetime.utcnow(),
    )
    db_session.add(org)
    db_session.commit()
    return _org_id


@pytest.fixture(scope="function")
def subscription(db_session, org_id):
    """Create a Subscription so UsageService.check_limit does not raise 403."""
    sub = Subscription(
        id=uuid4(),
        org_id=org_id,
        plan=PlanEnum.PRO,
        status=SubscriptionStatusEnum.ACTIVE,
        max_ad_accounts=100,
        max_decisions_per_month=1000,
        max_creatives_per_month=500,
        allow_live_execution=True,
        created_at=datetime.utcnow(),
    )
    db_session.add(sub)
    db_session.commit()
    return sub


@pytest.fixture(scope="function")
def ad_account_id(db_session, org_id):
    """Create a MetaConnection + AdAccount and return the AdAccount id."""
    conn_id = uuid4()
    conn = MetaConnection(
        id=conn_id,
        org_id=org_id,
        access_token_encrypted="fake-token-encrypted",
        status=ConnectionStatus.ACTIVE,
        connected_at=datetime.utcnow(),
    )
    db_session.add(conn)
    db_session.flush()

    _ad_account_id = uuid4()
    acct = AdAccount(
        id=_ad_account_id,
        connection_id=conn_id,
        meta_ad_account_id=f"act_{uuid4().hex[:12]}",
        name="Test Ad Account",
    )
    db_session.add(acct)
    db_session.commit()
    return _ad_account_id


@pytest.fixture(scope="function")
def user_id():
    return uuid4()


@pytest.fixture(scope="function")
def client(override_db, db_session, org_id, user_id, subscription):
    """TestClient with auth overrides (require_any_authenticated + get_current_user)."""

    def fake_user():
        return {
            "user_id": str(user_id),
            "id": str(user_id),
            "org_id": str(org_id),
            "role": "operator",
            "email": "test@example.com",
            "name": "Test User",
        }

    def fake_auth():
        return None

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[require_any_authenticated] = fake_auth
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Shared patch helper for endpoint tests ───────────────────────────────────
# The generate_creatives endpoint does local imports of Path and BrandMapBuilder
# inside the function body.  We patch at their source modules so that when the
# endpoint runs `from pathlib import Path` / `from src.engines...` it picks up
# our mocks.


def _endpoint_patches(mock_factory, mock_scorer, brand_file_exists=True):
    """
    Return a combined context manager that patches:
    - get_factory / get_scorer (module-level helpers in creatives.py)
    - BrandMapBuilder at its source module
    - pathlib.Path so the demo_brand_path check succeeds
    """
    mock_brand_map = MagicMock(name="BrandMap")
    mock_builder_inst = MagicMock()
    mock_builder_inst.build.return_value = mock_brand_map

    # Build a mock Path class whose instances behave like real Path objects.
    # The endpoint does: Path(__file__).parent.parent.parent.parent / "data" / "demo_brand.txt"
    # That is two __truediv__ calls.  The final object needs .exists() and .read_text().
    mock_path_final = MagicMock()
    mock_path_final.exists.return_value = brand_file_exists
    mock_path_final.read_text.return_value = "Fake brand data for testing"

    mock_path_mid = MagicMock()
    mock_path_mid.__truediv__ = MagicMock(return_value=mock_path_final)

    # Create a Path mock that supports chained .parent and first / operator
    mock_path_inst = MagicMock()
    mock_path_inst.parent = mock_path_inst  # .parent.parent.parent.parent -> self
    mock_path_inst.__truediv__ = MagicMock(return_value=mock_path_mid)

    original_path = __import__("pathlib").Path

    def patched_path_cls(arg):
        # Only intercept Path(__file__) calls from creatives.py
        if isinstance(arg, str) and "creatives" in arg:
            return mock_path_inst
        return original_path(arg)

    patches = [
        patch("backend.src.api.creatives.get_factory", return_value=mock_factory),
        patch("backend.src.api.creatives.get_scorer", return_value=mock_scorer),
        patch("src.engines.brand_map.builder.BrandMapBuilder", return_value=mock_builder_inst),
        patch("backend.src.api.creatives.Path", side_effect=patched_path_cls, create=True),
    ]
    return patches


class _MultiPatch:
    """Context manager that enters multiple patches at once."""

    def __init__(self, patches):
        self._patches = patches
        self._mocks = []

    def __enter__(self):
        self._mocks = [p.__enter__() for p in self._patches]
        return self._mocks

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.__exit__(*args)


# ── 1. test_generate_endpoint_returns_202_async ──────────────────────────────


class TestGenerateEndpointReturns202Async:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    @patch("backend.src.api.creatives.UsageService")
    def test_generate_endpoint_returns_202_async(
        self, MockUsageService, mock_enqueue, client, ad_account_id
    ):
        """POST /api/creatives/generate now returns 202 with job_id (Sprint 11 async)."""
        mock_usage_inst = MagicMock()
        MockUsageService.return_value = mock_usage_inst

        resp = client.post(
            "/api/creatives/generate",
            json={
                "angle_id": "pain_point",
                "brand_map_id": "demo",
                "n_variants": 1,
                "ad_account_id": str(ad_account_id),
            },
        )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "fake-job-id"
        assert data["status"] == "queued"


# ── 2. test_generate_enqueues_creatives_generate ─────────────────────────────


class TestGenerateEnqueuesCreativesGenerate:

    @patch("backend.src.jobs.queue.enqueue", return_value="fake-job-id")
    @patch("backend.src.api.creatives.UsageService")
    def test_generate_enqueues_creatives_generate(
        self, MockUsageService, mock_enqueue, client, ad_account_id
    ):
        """Endpoint calls enqueue with task_name='creatives_generate'."""
        mock_usage_inst = MagicMock()
        MockUsageService.return_value = mock_usage_inst

        resp = client.post(
            "/api/creatives/generate",
            json={
                "angle_id": "pain_point",
                "brand_map_id": "demo",
                "n_variants": 1,
                "ad_account_id": str(ad_account_id),
            },
        )
        assert resp.status_code == 202
        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args
        assert call_kwargs.kwargs.get("task_name") == "creatives_generate"


# ── 3. test_task_runner_script_text_assembly ─────────────────────────────────


class TestTaskRunnerScriptTextAssembly:

    def test_task_runner_script_text_assembly(self, db_session, org_id, ad_account_id):
        """task_runner assembles script_text as f\"{hook}\\n{body}\\n{cta}\" from AdScript."""
        from backend.src.jobs.task_runner import _dispatch
        from backend.src.database.models import JobRun

        hook = "Are you tired of bad ads?"
        body = "Our AI writes creatives that convert at 3x the rate."
        cta = "Try it free today."

        mock_factory_inst = MagicMock()
        mock_factory_inst.generate_scripts.return_value = [
            _make_mock_adscript(hook=hook, body=body, cta=cta)
        ]

        mock_scorer_inst = MagicMock()
        mock_scorer_inst.evaluate.return_value = _make_mock_eval_score(8.0)

        mock_builder_inst = MagicMock()
        mock_builder_inst.build.return_value = MagicMock(name="BrandMap")

        mock_path_final = MagicMock()
        mock_path_final.exists.return_value = True
        mock_path_final.read_text.return_value = "brand data"
        mock_path_mid = MagicMock()
        mock_path_mid.__truediv__ = MagicMock(return_value=mock_path_final)
        mock_path_inst = MagicMock()
        mock_path_inst.parent = mock_path_inst
        mock_path_inst.__truediv__ = MagicMock(return_value=mock_path_mid)

        import pathlib
        original_path = pathlib.Path
        def patched_path_cls(arg):
            if isinstance(arg, str) and "task_runner" in arg:
                return mock_path_inst
            return original_path(arg)

        job_run = MagicMock(spec=JobRun)
        job_run.org_id = org_id
        job_run.payload_json = {
            "angle_id": "pain_point",
            "n_variants": 1,
            "ad_account_id": str(ad_account_id),
        }

        with patch("src.engines.factory.factory.Factory", return_value=mock_factory_inst), \
             patch("src.engines.scoring.scorer.Scorer", return_value=mock_scorer_inst), \
             patch("src.engines.brand_map.builder.BrandMapBuilder", return_value=mock_builder_inst), \
             patch("pathlib.Path", side_effect=patched_path_cls):
            _dispatch("creatives_generate", job_run, db_session)

        expected = f"{hook}\n{body}\n{cta}"
        call_kwargs = mock_scorer_inst.evaluate.call_args
        actual_asset = call_kwargs.kwargs.get("asset", call_kwargs.args[0] if call_kwargs.args else None)
        assert actual_asset == expected


# ── 4. test_task_runner_persists_scored_creatives ────────────────────────────


class TestTaskRunnerPersistesScoredCreatives:

    def test_task_runner_persists_scored_creatives(self, db_session, org_id, ad_account_id):
        """task_runner persists Creative records with correct scores to DB."""
        from backend.src.jobs.task_runner import _dispatch
        from backend.src.database.models import JobRun

        scripts = [
            _make_mock_adscript(hook="Hook A", body="Body A", cta="CTA A"),
            _make_mock_adscript(hook="Hook B", body="Body B", cta="CTA B"),
        ]
        mock_factory_inst = MagicMock()
        mock_factory_inst.generate_scripts.return_value = scripts

        mock_scorer_inst = MagicMock()
        mock_scorer_inst.evaluate.return_value = _make_mock_eval_score(8.2)

        mock_builder_inst = MagicMock()
        mock_builder_inst.build.return_value = MagicMock(name="BrandMap")

        mock_path_final = MagicMock()
        mock_path_final.exists.return_value = True
        mock_path_final.read_text.return_value = "brand data"
        mock_path_mid = MagicMock()
        mock_path_mid.__truediv__ = MagicMock(return_value=mock_path_final)
        mock_path_inst = MagicMock()
        mock_path_inst.parent = mock_path_inst
        mock_path_inst.__truediv__ = MagicMock(return_value=mock_path_mid)

        import pathlib
        original_path = pathlib.Path
        def patched_path_cls(arg):
            if isinstance(arg, str) and "task_runner" in arg:
                return mock_path_inst
            return original_path(arg)

        job_run = MagicMock(spec=JobRun)
        job_run.org_id = org_id
        job_run.payload_json = {
            "angle_id": "social_proof",
            "n_variants": 2,
            "ad_account_id": str(ad_account_id),
        }

        with patch("src.engines.factory.factory.Factory", return_value=mock_factory_inst), \
             patch("src.engines.scoring.scorer.Scorer", return_value=mock_scorer_inst), \
             patch("src.engines.brand_map.builder.BrandMapBuilder", return_value=mock_builder_inst), \
             patch("pathlib.Path", side_effect=patched_path_cls):
            _dispatch("creatives_generate", job_run, db_session)

        # Verify Creative records were persisted
        creatives = db_session.query(Creative).all()
        assert len(creatives) == 2
        for c in creatives:
            assert c.overall_score == 8.2
            assert c.ad_account_id == ad_account_id


# ── 5. test_task_runner_creatives_generate_calls_factory ─────────────────────


class TestTaskRunnerCreativesGenerateCallsFactory:

    def test_task_runner_creatives_generate_calls_factory(
        self, db_session, org_id, ad_account_id
    ):
        """The creatives_generate dispatch in task_runner calls
        Factory().generate_scripts() (not the old placeholder)."""
        from backend.src.jobs.task_runner import _dispatch
        from backend.src.database.models import JobRun

        mock_script = _make_mock_adscript()
        mock_factory_inst = MagicMock()
        mock_factory_inst.generate_scripts.return_value = [mock_script]

        mock_scorer_inst = MagicMock()
        mock_scorer_inst.evaluate.return_value = _make_mock_eval_score()

        mock_builder_inst = MagicMock()
        mock_builder_inst.build.return_value = MagicMock(name="BrandMap")

        # Build a mock Path chain that supports .parent chaining and two
        # __truediv__ calls: Path(__file__).parent...parent / "data" / "demo_brand.txt"
        mock_path_final = MagicMock()
        mock_path_final.exists.return_value = True
        mock_path_final.read_text.return_value = "brand data"

        mock_path_mid = MagicMock()
        mock_path_mid.__truediv__ = MagicMock(return_value=mock_path_final)

        mock_path_inst = MagicMock()
        mock_path_inst.parent = mock_path_inst  # .parent.parent... -> self
        mock_path_inst.__truediv__ = MagicMock(return_value=mock_path_mid)

        import pathlib
        original_path = pathlib.Path

        def patched_path_cls(arg):
            if isinstance(arg, str) and "task_runner" in arg:
                return mock_path_inst
            return original_path(arg)

        # Create a fake JobRun
        job_run = MagicMock(spec=JobRun)
        job_run.org_id = org_id
        job_run.payload_json = {
            "angle_id": "pain_point",
            "n_variants": 1,
            "ad_account_id": str(ad_account_id),
        }

        with patch("src.engines.factory.factory.Factory", return_value=mock_factory_inst), \
             patch("src.engines.scoring.scorer.Scorer", return_value=mock_scorer_inst), \
             patch("src.engines.brand_map.builder.BrandMapBuilder", return_value=mock_builder_inst), \
             patch("pathlib.Path", side_effect=patched_path_cls):
            _dispatch("creatives_generate", job_run, db_session)

        # Verify Factory().generate_scripts() was called
        mock_factory_inst.generate_scripts.assert_called_once()
        call_kwargs = mock_factory_inst.generate_scripts.call_args
        assert call_kwargs.kwargs.get("target_angles") == ["pain_point"]
        assert call_kwargs.kwargs.get("num_variants") == 1

        # Verify Scorer().evaluate() was called
        mock_scorer_inst.evaluate.assert_called_once()


# ── 6. test_task_runner_creatives_generate_raises_on_no_account ──────────────


class TestTaskRunnerCreativesGenerateRaisesOnNoAccount:

    def test_task_runner_creatives_generate_raises_on_no_account(self, db_engine):
        """creatives_generate raises ValueError when no ad_account_id in payload
        and no AdAccount records exist in the database."""
        from backend.src.jobs.task_runner import _dispatch
        from backend.src.database.models import JobRun

        # Use a fresh session with no AdAccount rows
        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()

        try:
            job_run = MagicMock(spec=JobRun)
            job_run.org_id = uuid4()
            job_run.payload_json = {
                "angle_id": "urgency",
                "n_variants": 1,
                # No ad_account_id
            }

            with pytest.raises(ValueError, match="No ad account available"):
                _dispatch("creatives_generate", job_run, session)
        finally:
            session.close()


# ── 7. test_task_runner_creatives_generate_raises_on_no_brand_data ───────────


class TestTaskRunnerCreativesGenerateRaisesOnNoBrandData:

    def test_task_runner_creatives_generate_raises_on_no_brand_data(
        self, db_session, org_id, ad_account_id
    ):
        """creatives_generate raises FileNotFoundError when brand data file is missing."""
        from backend.src.jobs.task_runner import _dispatch
        from backend.src.database.models import JobRun

        # Build a mock Path chain.  The task_runner code does:
        #   Path(__file__).parent.parent.parent.parent / "data" / "demo_brand.txt"
        # That is two __truediv__ calls after the .parent chain.
        # The final object must have exists() -> False.
        mock_path_final = MagicMock()
        mock_path_final.exists.return_value = False

        mock_path_mid = MagicMock()
        mock_path_mid.__truediv__ = MagicMock(return_value=mock_path_final)

        mock_path_inst = MagicMock()
        mock_path_inst.parent = mock_path_inst  # .parent.parent... -> self
        mock_path_inst.__truediv__ = MagicMock(return_value=mock_path_mid)

        import pathlib
        original_path = pathlib.Path

        def patched_path_cls(arg):
            if isinstance(arg, str) and "task_runner" in arg:
                return mock_path_inst
            return original_path(arg)

        job_run = MagicMock(spec=JobRun)
        job_run.org_id = org_id
        job_run.payload_json = {
            "angle_id": "pain_point",
            "n_variants": 1,
            "ad_account_id": str(ad_account_id),
        }

        # Must also patch BrandMapBuilder and Factory/Scorer to prevent
        # their __init__ from hitting real services if imports resolve.
        with patch("pathlib.Path", side_effect=patched_path_cls), \
             patch("src.engines.brand_map.builder.BrandMapBuilder"), \
             patch("src.engines.factory.factory.Factory"), \
             patch("src.engines.scoring.scorer.Scorer"):
            with pytest.raises(FileNotFoundError, match="Brand data not available"):
                _dispatch("creatives_generate", job_run, db_session)


# ── 8. test_generate_endpoint_enforces_usage_gate ────────────────────────────


class TestGenerateEndpointEnforcesUsageGate:

    @patch("backend.src.api.creatives.UsageService")
    def test_generate_endpoint_enforces_usage_gate(
        self, MockUsageService, client, ad_account_id
    ):
        """UsageService.check_limit is called before generation starts.
        If it raises, the endpoint should 403 without calling Factory."""
        mock_usage_inst = MagicMock()
        from fastapi import HTTPException
        mock_usage_inst.check_limit.side_effect = HTTPException(
            status_code=403,
            detail="Monthly creative_generate limit reached (500/500).",
        )
        MockUsageService.return_value = mock_usage_inst

        resp = client.post(
            "/api/creatives/generate",
            json={
                "angle_id": "pain_point",
                "brand_map_id": "demo",
                "n_variants": 1,
                "ad_account_id": str(ad_account_id),
            },
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

        # Verify check_limit was called with event_type "creative_generate"
        mock_usage_inst.check_limit.assert_called_once()
        call_args = mock_usage_inst.check_limit.call_args
        # Second positional arg or keyword should be "creative_generate"
        if call_args.args:
            assert call_args.args[1] == "creative_generate"
        else:
            assert call_args.kwargs.get("event_type") == "creative_generate"
