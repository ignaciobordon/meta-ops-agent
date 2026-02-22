"""
Sprint 7 -- BLOQUE 1: Generic Task Runner.
Loads JobRun, executes via dispatch map, handles status transitions.
Integrates with: ErrorClassifier, Backoff, Idempotency lock.
"""
import time
import concurrent.futures
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm.attributes import flag_modified
from backend.src.database.models import JobRun, JobRunStatus
from backend.src.retries.error_classifier import classify_error, classify_llm_error
from backend.src.retries.backoff import get_next_retry_delay
from backend.src.observability.metrics import track_job_run
from src.utils.logging_config import logger, set_trace_id

# Per-job-type execution timeouts (seconds)
_JOB_TIMEOUT = {
    "creatives_generate": 300,
    "opportunities_analyze": 180,
    "content_studio_generate": 900,
    "ci_ingest": 300,
    "ci_detect": 180,
    "unified_intelligence_analyze": 360,
    "flywheel_run": 1800,
    "data_room_export": 300,
}
_DEFAULT_JOB_TIMEOUT = 120

# Job types that use LLM-specific error classification
_LLM_JOB_TYPES = {"creatives_generate", "opportunities_analyze", "content_studio_generate", "unified_intelligence_analyze"}


def _load_brand_map_from_profile(db, org_id, brand_profile_id=None):
    """
    Load BrandMap from a BrandMapProfile in the DB.
    If the profile is already analyzed (status='ready'), reconstruct from stored JSON.
    If not analyzed yet, run fresh BrandMapBuilder.build() on the raw_text.
    Falls back to demo_brand.txt if no brand_profile_id is provided.
    Returns: BrandMap object
    """
    from src.engines.brand_map.builder import BrandMapBuilder
    from pathlib import Path

    builder = BrandMapBuilder()

    if brand_profile_id:
        from backend.src.database.models import BrandMapProfile
        from uuid import UUID as _UUID

        profile = db.query(BrandMapProfile).filter(
            BrandMapProfile.id == _UUID(brand_profile_id),
        ).first()

        if not profile:
            raise ValueError(f"BrandMapProfile {brand_profile_id} not found")

        # If already analyzed, reconstruct BrandMap from stored JSON (skip LLM)
        if profile.status == "ready" and profile.structured_json:
            from src.schemas.brand_map import BrandMap
            try:
                brand_map = BrandMap.model_validate(profile.structured_json)
                logger.info(
                    "BRAND_MAP_RECONSTRUCTED_FROM_JSON | profile_id={} | status=ready",
                    brand_profile_id,
                )
                return brand_map
            except Exception as e:
                logger.warning(
                    "BRAND_MAP_JSON_RECONSTRUCT_FAILED | profile_id={} | error={} | falling back to build()",
                    brand_profile_id, str(e)[:200],
                )
                # Fall through to build() below

        # Profile exists but not analyzed — run fresh analysis on raw_text
        brand_map = builder.build(profile.raw_text)
        logger.info(
            "BRAND_MAP_BUILT_FROM_PROFILE | profile_id={} | status={}",
            brand_profile_id, profile.status,
        )
        return brand_map

    # Fallback: demo_brand.txt
    demo_brand_path = Path(__file__).parent.parent.parent.parent / "data" / "demo_brand.txt"
    if not demo_brand_path.exists():
        raise FileNotFoundError("Brand data not available at data/demo_brand.txt")

    brand_text = demo_brand_path.read_text(encoding="utf-8")
    brand_map = builder.build(brand_text)
    logger.info("BRAND_MAP_LOADED_FROM_DEMO | path={}", demo_brand_path)
    return brand_map


def run_job(job_run_id: str, job_type: str):
    """Execute a single job run with full lifecycle management."""
    from backend.src.database.session import SessionLocal

    db = SessionLocal()
    try:
        job_run = db.query(JobRun).filter(JobRun.id == UUID(job_run_id)).first()
        if not job_run:
            logger.warning("JOB_RUN_NOT_FOUND | {}", job_run_id)
            return

        # Guard: skip if not in QUEUED or RETRY_SCHEDULED
        if job_run.status not in (JobRunStatus.QUEUED, JobRunStatus.RETRY_SCHEDULED):
            logger.info("JOB_RUN_SKIP | {} | status={}", job_run_id, job_run.status.value)
            return

        # Set trace context
        if job_run.trace_id:
            set_trace_id(job_run.trace_id)

        # Acquire execution lock
        from backend.src.jobs.idempotency import acquire_execution_lock, release_execution_lock
        if not acquire_execution_lock(job_run_id):
            logger.info("JOB_RUN_LOCKED | {} | already executing", job_run_id)
            return

        t0 = time.monotonic()
        try:
            # Transition to RUNNING
            job_run.status = JobRunStatus.RUNNING
            job_run.started_at = datetime.utcnow()
            job_run.attempts += 1
            db.commit()

            # Dispatch to actual service logic with timeout
            timeout = _JOB_TIMEOUT.get(job_type, _DEFAULT_JOB_TIMEOUT)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_dispatch, job_type, job_run, db)
                try:
                    future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(
                        f"Job execution exceeded {timeout}s timeout"
                    )
            duration = time.monotonic() - t0

            # SUCCESS
            job_run.status = JobRunStatus.SUCCEEDED
            job_run.finished_at = datetime.utcnow()
            db.commit()

            track_job_run(job_type, "succeeded", duration)
            logger.info(
                "JOB_RUN_SUCCEEDED | {} | type={} | attempt={}/{} | duration={:.2f}s",
                job_run_id, job_type, job_run.attempts, job_run.max_attempts, duration,
            )

        except Exception as e:
            db.rollback()

            # Re-load to avoid stale state
            job_run = db.query(JobRun).filter(JobRun.id == UUID(job_run_id)).first()
            if not job_run:
                return

            job_run.finished_at = datetime.utcnow()
            error_class = classify_llm_error(e) if job_type in _LLM_JOB_TYPES else classify_error(e)
            job_run.last_error_code = error_class.code
            job_run.last_error_message = str(e)[:2000]

            if error_class.retryable and job_run.attempts < job_run.max_attempts:
                delay = get_next_retry_delay(job_type, job_run.attempts)
                job_run.status = JobRunStatus.RETRY_SCHEDULED
                db.commit()

                # Re-enqueue with delay
                from backend.src.jobs.queue import enqueue
                enqueue(
                    task_name=job_type,
                    payload=job_run.payload_json or {},
                    org_id=job_run.org_id,
                    eta=datetime.utcnow() + delay,
                    scheduled_job_id=job_run.scheduled_job_id,
                    trace_id=job_run.trace_id,
                    max_attempts=job_run.max_attempts,
                )
            else:
                if job_run.attempts >= job_run.max_attempts:
                    job_run.status = JobRunStatus.DEAD
                else:
                    job_run.status = JobRunStatus.FAILED
                db.commit()

            track_job_run(job_type, job_run.status.value, time.monotonic() - t0)
            logger.error(
                "JOB_RUN_FAILED | {} | type={} | error_class={} | attempt={}/{} | error={}",
                job_run_id, job_type, error_class.code,
                job_run.attempts, job_run.max_attempts, str(e)[:200],
            )

        finally:
            release_execution_lock(job_run_id)

    finally:
        db.close()


def _dispatch(job_type: str, job_run: JobRun, db):
    """Route job_type to existing service logic."""
    payload = job_run.payload_json or {}
    org_id = job_run.org_id

    if job_type == "meta_sync_assets":
        from backend.src.services.meta_sync_service import MetaSyncService
        svc = MetaSyncService(db)
        svc.sync_assets(org_id, UUID(payload["ad_account_id"]))

    elif job_type == "meta_sync_insights":
        from backend.src.services.meta_sync_service import MetaSyncService
        svc = MetaSyncService(db)
        svc.sync_insights(org_id, UUID(payload["ad_account_id"]))

    elif job_type == "meta_live_monitor":
        from backend.src.services.live_monitor import LiveMonitor
        monitor = LiveMonitor(db)
        monitor.check_drift(org_id, UUID(payload["ad_account_id"]))

    elif job_type == "meta_generate_alerts":
        from backend.src.engines.insight_engine import InsightEngine
        from backend.src.engines.anomaly_detector import AnomalyDetector
        ad_account_id = UUID(payload["ad_account_id"])
        InsightEngine(db).analyze(org_id, ad_account_id)
        AnomalyDetector(db).detect(org_id, ad_account_id)

    elif job_type == "outcome_capture":
        from backend.src.services.outcome_service import OutcomeCollector
        OutcomeCollector(db).capture_after(UUID(payload["outcome_id"]))

    elif job_type == "decision_execute":
        from backend.src.services.decision_service import DecisionService
        svc = DecisionService(db)
        svc.execute_decision(
            UUID(payload["decision_id"]),
            operator_armed=payload.get("operator_armed", False),
            dry_run=payload.get("dry_run", False),
        )

    elif job_type == "opportunities_analyze":
        from src.engines.brand_map.builder import BrandMapBuilder
        from pathlib import Path
        import json

        logger.info("JOB_LLM_START | type=opportunities_analyze | org={}", org_id)

        brand_map = _load_brand_map_from_profile(db, org_id, payload.get("brand_profile_id"))

        opportunities = []
        for idx, opp in enumerate(brand_map.opportunity_map):
            # Use LLM-estimated impact (0-100 scale → 0-1), fallback to position-based
            llm_impact = getattr(opp, "estimated_impact", 0.0) or 0.0
            if llm_impact > 0:
                impact = round(min(1.0, max(0.0, llm_impact / 100.0)), 2)
            else:
                impact = round(max(0.5, 0.9 - (idx * 0.1)), 2)

            impact_reasoning = getattr(opp, "impact_reasoning", "") or ""

            # Priority based on impact value
            priority = "high" if impact >= 0.7 else ("medium" if impact >= 0.4 else "low")

            opportunities.append({
                "id": f"opp-{idx+1}",
                "gap_id": opp.gap_id,
                "title": f"Market Opportunity: {opp.gap_id.replace('_', ' ').title()}",
                "description": opp.strategy_recommendation,
                "strategy": opp.strategy_recommendation,
                "priority": priority,
                "estimated_impact": impact,
                "impact_reasoning": impact_reasoning,
                "identified_at": brand_map.metadata.created_at.isoformat(),
            })

        # Store result in job payload (reassign dict so SQLAlchemy detects the change)
        updated_payload = dict(job_run.payload_json or {})
        updated_payload["result"] = opportunities
        job_run.payload_json = updated_payload
        flag_modified(job_run, "payload_json")
        db.commit()

        logger.info(
            "OPPORTUNITIES_ANALYZE_DONE | org={} | count={}",
            org_id, len(opportunities),
        )

    elif job_type == "creatives_generate":
        logger.info("JOB_LLM_START | type=creatives_generate | org={}", org_id)
        from src.engines.factory.factory import Factory
        from src.engines.scoring.scorer import Scorer
        from src.engines.brand_map.builder import BrandMapBuilder
        from backend.src.database.models import Creative, AdAccount
        from pathlib import Path

        angle_id = payload.get("angle_id", "")
        n_variants = payload.get("n_variants", 3)
        ad_account_id_str = payload.get("ad_account_id")
        flywheel_context = payload.get("flywheel_context")

        # Resolve ad account
        ad_account_id = None
        if ad_account_id_str:
            ad_account_id = UUID(ad_account_id_str)
        else:
            first_account = db.query(AdAccount).first()
            if first_account:
                ad_account_id = first_account.id

        if not ad_account_id:
            raise ValueError("No ad account available for creatives_generate")

        # Load BrandMap (from profile or fallback to demo_brand.txt)
        brand_map = _load_brand_map_from_profile(db, org_id, payload.get("brand_profile_id"))

        # Generate scripts (with interface guardrail)
        factory = Factory()
        if not hasattr(factory, "generate_scripts"):
            raise RuntimeError(
                f"Factory interface mismatch: 'generate_scripts' not found. "
                f"Available: {[m for m in dir(factory) if not m.startswith('_')]} | "
                f"job_run_id={job_run.id} | trace_id={job_run.trace_id}"
            )
        scripts = factory.generate_scripts(
            brand_map=brand_map,
            target_angles=[angle_id],
            num_variants=n_variants,
            flywheel_context=flywheel_context,
        )

        # Determine source and metadata for tracking
        source = "flywheel" if flywheel_context else "manual"
        flywheel_metadata = {}
        if flywheel_context:
            flywheel_metadata = {
                "opportunities_used": len(flywheel_context.get("all_opportunities", [])),
                "winning_features_used": len(flywheel_context.get("winning_features", [])),
                "saturated_ads_avoided": len(flywheel_context.get("saturated_ads", [])),
                "priority_breakdown": flywheel_context.get("priority_breakdown", {}),
            }

        # Score and persist (with interface guardrail)
        scorer = Scorer()
        if not hasattr(scorer, "evaluate"):
            raise RuntimeError(
                f"Scorer interface mismatch: 'evaluate' not found. "
                f"Available: {[m for m in dir(scorer) if not m.startswith('_')]} | "
                f"job_run_id={job_run.id} | trace_id={job_run.trace_id}"
            )
        now = datetime.utcnow()
        for script in scripts[:n_variants]:
            script_text = f"{script.hook}\n{script.body}\n{script.cta}"
            score_result = scorer.evaluate(asset=script_text, brand_map=brand_map)

            eval_score = {}
            if hasattr(score_result, "model_dump"):
                eval_score = score_result.model_dump(mode="json")

            creative_record = Creative(
                ad_account_id=ad_account_id,
                name=angle_id.replace("_", " ").title(),
                ad_copy=script_text,
                tags=[{"l1": "angle", "l2": angle_id, "confidence": 1.0, "source": "factory"}],
                overall_score=score_result.overall_score,
                evaluation_score=eval_score,
                meta_ad_id=f"gen-{uuid4().hex[:16]}",
                scored_at=now,
                tagged_at=now,
                source=source,
                flywheel_metadata=flywheel_metadata,
            )
            db.add(creative_record)

        db.commit()
        logger.info(
            "CREATIVES_GENERATE_DONE | org={} | angle={} | scripts={} | source={}",
            org_id, angle_id, len(scripts), source,
        )

    elif job_type == "content_studio_generate":
        logger.info("JOB_LLM_START | type=content_studio_generate | org={}", org_id)
        from backend.src.services.content_creator_service import generate_pack
        pack_id = payload.get("pack_id", "")
        if not pack_id:
            raise ValueError("content_studio_generate requires pack_id in payload")
        generate_pack(pack_id, db)
        logger.info("CONTENT_STUDIO_GENERATE_DONE | org={} | pack={}", org_id, pack_id)

    elif job_type == "content_studio_regenerate":
        logger.info("JOB_LLM_START | type=content_studio_regenerate | org={}", org_id)
        from backend.src.services.content_creator_service import regenerate_pack
        pack_id = payload.get("pack_id", "")
        channels = payload.get("channels", [])
        locked_variant_ids = payload.get("locked_variant_ids", {})
        if not pack_id:
            raise ValueError("content_studio_regenerate requires pack_id in payload")
        regenerate_pack(pack_id, channels, locked_variant_ids, db)
        logger.info("CONTENT_STUDIO_REGENERATE_DONE | org={} | pack={}", org_id, pack_id)

    elif job_type == "unified_intelligence_analyze":
        logger.info("JOB_LLM_START | type=unified_intelligence_analyze | org={}", org_id)

        from backend.src.services.unified_intelligence import UnifiedIntelligenceService
        svc = UnifiedIntelligenceService(db, org_id)
        opportunities = svc.analyze(brand_profile_id=payload.get("brand_profile_id"))

        # Store result in job payload (reassign dict so SQLAlchemy detects the change)
        updated_payload = dict(job_run.payload_json or {})
        updated_payload["result"] = opportunities
        job_run.payload_json = updated_payload
        flag_modified(job_run, "payload_json")
        db.commit()

        logger.info(
            "UNIFIED_INTELLIGENCE_DONE | org={} | count={}",
            org_id, len(opportunities),
        )

    elif job_type == "ci_ingest":
        from backend.src.ci.ci_tasks import run_ci_ingest
        run_ci_ingest(org_id, payload, db, job_run_id=str(job_run.id))

    elif job_type == "ci_detect":
        from backend.src.ci.ci_tasks import run_ci_detect
        run_ci_detect(org_id, payload, db, job_run_id=str(job_run.id))

    elif job_type == "flywheel_run":
        from backend.src.services.flywheel_service import FlywheelService
        svc = FlywheelService(db, org_id)
        svc.execute_run(UUID(payload["flywheel_run_id"]))

    elif job_type == "data_room_export":
        import tempfile
        from backend.src.database.models import DataExport
        from backend.src.services.data_room_export_service import DataRoomExportService

        export = db.query(DataExport).filter(DataExport.id == UUID(payload["export_id"])).first()
        if not export:
            raise ValueError(f"DataExport {payload['export_id']} not found")

        export.status = "running"
        db.commit()

        try:
            svc = DataRoomExportService(db, org_id)
            xlsx_bytes, total_rows = svc.build_xlsx(export.params_json or {})

            # Save to temp file
            with tempfile.NamedTemporaryFile(
                suffix=".xlsx", prefix="data_room_", delete=False
            ) as tmp:
                tmp.write(xlsx_bytes)
                tmp_path = tmp.name

            export.file_path = tmp_path
            export.rows_exported = total_rows
            export.status = "succeeded"
            export.finished_at = datetime.utcnow()
            db.commit()

            logger.info(
                "DATA_ROOM_EXPORT_DONE | export={} | rows={} | path={}",
                export.id, total_rows, tmp_path,
            )
        except Exception as e:
            export.status = "failed"
            export.last_error = str(e)[:2000]
            export.finished_at = datetime.utcnow()
            db.commit()
            raise

    else:
        raise ValueError(f"Unknown job_type: {job_type}")
