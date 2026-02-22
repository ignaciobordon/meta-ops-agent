# Release Notes: Sprint 10 — LLM Reliability Fix Pack

## Summary

Sprint 10 makes Creatives and Opportunities 100% functional by fixing broken wiring, ensuring env var parity across all Docker services, and adding diagnostics + observability for the LLM Router introduced in Sprint 9.

**No new features.** Reliability, wiring, and verification only.

---

## Changes

### BLOQUE A: Config Normalization + Diagnostics
- **Legacy compat**: `LLM_PROVIDER` env var (Sprint <=8) auto-bridges to `LLM_DEFAULT_PROVIDER`
- **Auto-detection**: If no provider specified, detects from available API keys
- **Diagnostics endpoint**: `GET /api/system/llm/diagnostics` (admin-only) — shows provider config, circuit breaker state, rate limiter status. Never exposes API keys.

### BLOQUE B: Docker Env Parity
- All 4 services (backend, celery-default, celery-io, celery-llm) now receive:
  - `OPENAI_API_KEY`, `LLM_DEFAULT_PROVIDER`, `LLM_FALLBACK_PROVIDER`, `LLM_TIMEOUT_SECONDS`
  - `CHROMA_PERSIST_DIRECTORY`, `JWT_SECRET` (previously missing on workers)

### BLOQUE C: Creatives/Opportunities Wiring
- **Fixed** `creatives.py`: `factory.generate_script()` -> `factory.generate_scripts()` (correct method)
- **Fixed** `creatives.py`: `scorer.score()` -> `scorer.evaluate()` (correct method)
- **Fixed** `creatives.py`: `scripts.variants[i]` -> iterate `List[AdScript]` directly
- **Wired** `creatives_generate` in `task_runner.py`: was a placeholder, now fully implements Factory -> Scorer -> DB persistence flow

### BLOQUE D: Queue Routing + Time Limits
- Added global Celery time limits: 120s soft / 180s hard
- Added per-task override for `creatives_generate`: 300s soft / 360s hard (LLM tasks need longer)

### BLOQUE E: Observability
- Added `queue` field to `JobRunResponse` in Ops Console (derived from QUEUE_ROUTING)

### BLOQUE F: Runbooks
- `RUNBOOK_LLM.md`: Full operational guide for LLM Router
- `RELEASE_NOTES_LLM_FIXPACK.md`: This file

---

## Verification Matrix

| Check | Command | Expected |
|---|---|---|
| Tests pass | `python -m pytest tests/ -v --ignore=tests/test_integration_pipeline.py` | All green |
| Frontend builds | `cd frontend && npm run build` | 0 TS errors |
| Diagnostics works | `GET /api/system/llm/diagnostics` | 200 with provider info |
| Creatives generate | `POST /api/creatives/generate` | 200 with scored scripts |
| Opportunities load | `GET /api/opportunities/` | 200 with opportunity list |
| Docker env parity | `docker compose exec celery-llm env \| grep LLM_` | All vars present |
| LLM metrics exist | `GET /metrics` | `llm_requests_total` present |
| Ops queue field | `GET /api/ops/jobs` | `queue` field in response |

---

## Files Changed

### New (3)
- `backend/src/api/system.py` — LLM diagnostics endpoint
- `RUNBOOK_LLM.md`
- `RELEASE_NOTES_LLM_FIXPACK.md`

### Modified (6)
- `backend/src/config.py` — Legacy LLM_PROVIDER compat + auto-detection
- `backend/main.py` — Register system router
- `docker-compose.yml` — Env var parity across all services
- `backend/src/api/creatives.py` — Fix broken method calls
- `backend/src/jobs/task_runner.py` — Wire creatives_generate dispatch
- `backend/src/infra/celery_app.py` — Add time limits
- `backend/src/api/ops.py` — Add queue field to JobRunResponse
