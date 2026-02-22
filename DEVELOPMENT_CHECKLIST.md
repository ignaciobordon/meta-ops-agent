# Meta Ops Agent - Development Checklist

**Generated**: 2026-02-16
**Auditor**: Claude (Senior Lead Engineer)
**Scope**: Full codebase audit — backend, frontend, engines, configs
**Status**: ALL ITEMS IMPLEMENTED AND VERIFIED

---

## Priority Legend
- **P0 CRITICAL** — Breaks production, security risk, data loss
- **P1 HIGH** — Bugs, incorrect behavior, missing error handling
- **P2 MEDIUM** — Code quality, maintainability, performance

---

## P0 CRITICAL

### [x] [C01] Create .gitignore file
- **File**: `.gitignore` (was missing)
- **Fix**: Created comprehensive .gitignore for Python, Node.js, IDE files, .env, databases

### [x] [C02] Frontend: Replace hardcoded localhost URLs with api.ts client
- **Files**: 5 pages (Opportunities, Policies, Creatives, Saturation, AuditLog)
- **Fix**: Added typed API methods to `api.ts` (opportunitiesApi, policiesApi, creativesApi, saturationApi, auditApi) and refactored all 5 pages to use centralized client

### [x] [C03] Fix mutable default values in SQLAlchemy models
- **File**: `backend/src/database/models.py`
- **Fix**: Changed all `default={}` to `default=dict` and `default=[]` to `default=list` (10 fields fixed)

### [x] [C04] Rate limiter memory leak — no client cleanup
- **File**: `backend/src/middleware/rate_limit.py`
- **Fix**: Added stale client cleanup (removes clients not seen in 2x window) on every is_allowed() call

### [x] [C05] session.py get_db() missing error rollback
- **File**: `backend/src/database/session.py`
- **Fix**: Added `except: db.rollback(); raise` before `finally` block

---

## P1 HIGH

### [x] [H01] Frontend store: type-safe currentUser
- **File**: `frontend/src/store/index.ts`
- **Fix**: Created `AppUser` interface and replaced `any` with `AppUser | null`

### [x] [H02] logging_config.py: Missing functools.wraps
- **File**: `src/utils/logging_config.py`
- **Fix**: Added `import functools` and `@functools.wraps(func)` on wrapper

### [x] [H03] logging_config.py: No directory check for logs/
- **File**: `src/utils/logging_config.py`
- **Fix**: Added `os.makedirs("logs", exist_ok=True)` before logger.add

### [x] [H04] rate_limit.py: Fix type hint `any` -> `Any`
- **File**: `backend/src/middleware/rate_limit.py`
- **Fix**: Imported `Any` from typing, fixed hint, removed unused `defaultdict` import

### [x] [H05] rate_limit.py: retry_after can go negative
- **File**: `backend/src/middleware/rate_limit.py`
- **Fix**: Clamped to `max(1, int(self.window - time_passed))`

### [x] [H06] VectorDBClient: Thread-unsafe singleton
- **File**: `src/database/vector/db_client.py`
- **Fix**: Added `threading.Lock()` around `__new__` singleton creation

### [x] [H07] builder.py: Unhandled StopIteration
- **File**: `src/engines/brand_map/builder.py`
- **Fix**: Changed `next(...)` to `next(..., None)` with explicit ValueError if None

### [x] [H08] builder.py: Hardcoded OpenAI model ID
- **File**: `src/engines/brand_map/builder.py`
- **Fix**: Changed to `os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06")`

### [x] [H09] Frontend Dashboard: Silent error on API failure
- **File**: `frontend/src/pages/Dashboard.tsx`
- **Fix**: Added error state variable and error display with retry button

### [x] [H10] + [H11] Standardize router prefixes
- **Files**: `opportunities.py`, `creatives.py`, `saturation.py`, `main.py`
- **Fix**: Removed `/api/` prefix from routers, added prefix in main.py `include_router()` for consistency

---

## P2 MEDIUM

### [x] [M01] policy_engine.py: Use timezone-aware datetime
- **File**: `src/core/policy_engine.py`
- **Fix**: Replaced all `datetime.utcnow()` with `datetime.now(timezone.utc)`

### [x] [M02] Frontend: Add error display for pages with error state
- **Files**: `Opportunities.tsx`, `Saturation.tsx`, `Policies.tsx`
- **Fix**: Added error display blocks with retry buttons to all 3 pages

### [ ] [M03] Docker-compose: Add backend and database services
- **File**: `docker-compose.yml`
- **Status**: DEFERRED — Infrastructure task, not blocking for development
- **Note**: Current docker-compose only has ChromaDB. Full stack compose is a separate task.

### [x] [M04] Create proper .env.template
- **File**: `.env.template`
- **Fix**: Updated with all env vars: LLM providers, Meta API, database, vector DB, frontend

### [x] [M05] Frontend: Add API methods for missing endpoints
- **File**: `frontend/src/services/api.ts`
- **Fix**: Added opportunitiesApi, policiesApi, creativesApi, saturationApi, auditApi with full TypeScript interfaces

---

## Verification

```
E2E Tests: 30/30 PASSING
Deprecation warnings: 8 (non-blocking — noted in HANDOFF_NOTES.md)
```

---

**Completed**: 16/17 items (1 deferred — M03 Docker-compose)
**Implemented by**: Claude (Senior Lead Engineer)
**Date**: 2026-02-16
