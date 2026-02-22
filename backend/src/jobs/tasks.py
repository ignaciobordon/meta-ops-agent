"""
Sprint 7 -- BLOQUE 1: Celery Task Definitions.
Wraps existing synchronous service calls. Each task delegates to run_job().
We set max_retries=0 because retry logic is handled by our own task_runner.
"""
try:
    from backend.src.infra.celery_app import celery_app

    if celery_app is not None:
        from backend.src.jobs.task_runner import run_job

        @celery_app.task(name="backend.src.jobs.tasks.meta_sync_assets", bind=True, max_retries=0)
        def meta_sync_assets(self, job_run_id: str):
            run_job(job_run_id, "meta_sync_assets")

        @celery_app.task(name="backend.src.jobs.tasks.meta_sync_insights", bind=True, max_retries=0)
        def meta_sync_insights(self, job_run_id: str):
            run_job(job_run_id, "meta_sync_insights")

        @celery_app.task(name="backend.src.jobs.tasks.meta_live_monitor", bind=True, max_retries=0)
        def meta_live_monitor(self, job_run_id: str):
            run_job(job_run_id, "meta_live_monitor")

        @celery_app.task(name="backend.src.jobs.tasks.meta_generate_alerts", bind=True, max_retries=0)
        def meta_generate_alerts(self, job_run_id: str):
            run_job(job_run_id, "meta_generate_alerts")

        @celery_app.task(name="backend.src.jobs.tasks.outcome_capture", bind=True, max_retries=0)
        def outcome_capture(self, job_run_id: str):
            run_job(job_run_id, "outcome_capture")

        @celery_app.task(name="backend.src.jobs.tasks.decision_execute", bind=True, max_retries=0)
        def decision_execute(self, job_run_id: str):
            run_job(job_run_id, "decision_execute")

        @celery_app.task(name="backend.src.jobs.tasks.creatives_generate", bind=True, max_retries=0)
        def creatives_generate(self, job_run_id: str):
            run_job(job_run_id, "creatives_generate")

        @celery_app.task(name="backend.src.jobs.tasks.opportunities_analyze", bind=True, max_retries=0)
        def opportunities_analyze(self, job_run_id: str):
            run_job(job_run_id, "opportunities_analyze")

        @celery_app.task(name="backend.src.jobs.tasks.ci_ingest", bind=True, max_retries=0)
        def ci_ingest(self, job_run_id: str):
            run_job(job_run_id, "ci_ingest")

        @celery_app.task(name="backend.src.jobs.tasks.ci_detect", bind=True, max_retries=0)
        def ci_detect(self, job_run_id: str):
            run_job(job_run_id, "ci_detect")

        @celery_app.task(name="backend.src.jobs.tasks.unified_intelligence_analyze", bind=True, max_retries=0)
        def unified_intelligence_analyze(self, job_run_id: str):
            run_job(job_run_id, "unified_intelligence_analyze")

        @celery_app.task(name="backend.src.jobs.tasks.flywheel_run", bind=True, max_retries=0)
        def flywheel_run(self, job_run_id: str):
            run_job(job_run_id, "flywheel_run")

        @celery_app.task(name="backend.src.jobs.tasks.data_room_export", bind=True, max_retries=0)
        def data_room_export(self, job_run_id: str):
            run_job(job_run_id, "data_room_export")

except ImportError:
    pass  # Celery not installed — tasks won't be registered
