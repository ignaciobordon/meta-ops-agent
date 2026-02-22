# Release Notes — Sprint 12

**Version:** 0.12.0
**Date:** February 2026

---

## Highlights

- **Fixed infinite spinner** when generating creatives or analyzing opportunities
- **One-command dev environment setup** with `scripts/dev_up.sh`
- **Creative presets** for framework, hook style, audience, and objective
- **Enhanced Meta connection diagnostics** with actionable fix recommendations
- **Improved decision reports** with executive summary, metrics comparison, and recommendations

---

## Bug Fixes

### Jobs no longer hang when Celery/Redis is unavailable
Jobs now execute via a **sync fallback** when the Celery broker is unreachable. Instead of staying QUEUED forever, jobs run in-process and complete normally.

### Job execution timeout prevents stuck jobs
A hard timeout of **2-3 minutes** is enforced on all job executions. Jobs that exceed this limit are marked as FAILED with a descriptive error message instead of running indefinitely.

### Frontend polling timeout prevents infinite spinners
The frontend stops polling for job status after **2 minutes** and displays a timeout error with a retry option, eliminating infinite spinner scenarios.

### Better error messages with LLM-specific error codes
LLM failures now return standardized error codes (`llm_auth`, `llm_timeout`, `llm_rate_limit`, `llm_degraded`, `llm_provider_misconfig`) so users and operators can quickly identify and resolve issues.

---

## New Features

### Dev Environment Automation

- **`scripts/dev_up.sh`** — One-command boot for backend, frontend, and optional Celery workers
- **`scripts/dev_down.sh`** — Clean shutdown of all dev services
- **`scripts/env_check.py`** — Pre-flight environment validation (checks Python version, dependencies, env vars, ports)
- **`scripts/smoke_local.py`** — Automated runtime smoke tests for a running local instance

### Creative Presets

Creative generation now supports preset dropdowns for faster ad copy creation:

- **Framework:** AIDA, PAS, BAB, 4Ps
- **Hook Style:** Question, Statistic, Story, Bold Claim
- **Audience:** Target audience selection
- **Objective:** Campaign objective selection

### Enhanced Meta Connection Diagnostics

`GET /api/meta/verify` now returns richer diagnostic information:

- `token_valid` — Boolean indicating whether the Meta token is healthy
- `scopes` — List of granted permissions
- `recommended_fix` — Actionable suggestion when the connection is unhealthy (e.g., "Re-authenticate via OAuth to refresh your token")

### Ops Console Improvements

The Ops Console table now includes additional columns for better job observability:

- **Queue** — Which queue processed the job
- **Request ID** — Unique identifier for request tracing
- **Error Code** — Standardized error code (e.g., `llm_timeout`)
- **Error Message** — Human-readable error description

### Enhanced DOCX Reports

Decision reports exported as DOCX now include:

- **Executive summary** — High-level overview of findings
- **Metrics comparison** — Side-by-side performance data tables
- **Recommendations** — Data-driven action items
- **Data sources** — Attribution of where metrics originated

### Retry Buttons

Failed creative generation and opportunity analysis jobs now show **Retry** buttons directly in the UI, allowing users to re-run jobs without navigating away.

---

## Known Limitations

- **Playwright E2E tests** require both backend and frontend to be running (`bash scripts/dev_up.sh` before running E2E)
- **Smoke tests** require login credentials to exist in the database (default admin user must be seeded)
- **Creative generation quality** depends on the LLM provider — Anthropic (Claude) is recommended for best results

---

## Test Stats

| Metric             | Value          |
|--------------------|----------------|
| Pytest tests       | ~681 passing   |
| TypeScript errors  | 0              |
| Frontend build     | Clean          |
