# AUDIT_RUNTIME.md — Runtime Smoke Test Results

**Date**: 2026-02-16
**Server**: `http://localhost:8000` (FastAPI + SQLite, fresh DB)
**Frontend**: `http://localhost:5173` (Vite dev server)
**Auditor**: Claude (Principal Engineer + QA Lead + SRE)

---

## Endpoint Inventory (from OpenAPI /openapi.json)

**Total registered endpoints: 28**

### Health (3)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/health` | Public | 207 (degraded — disk space warning) |
| GET | `/api/health/ready` | Public | 200 `{"ready":true}` |
| GET | `/api/health/live` | Public | 200 `{"alive":true,"uptime_seconds":...}` |

### Auth (4)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| POST | `/api/auth/login` | Public | 200 — Returns JWT access + refresh tokens |
| POST | `/api/auth/register` | Public | 200 — First user=admin, rest=viewer |
| POST | `/api/auth/refresh` | Public | 200 — Rotates tokens correctly |
| GET | `/api/auth/me` | Bearer | 200 — Returns user id/email/name/role/org_id |

### Dashboard (1)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/dashboard/kpis` | Bearer | 200 — Real DB queries (Pending/Executed/Blocked/DryRuns) |

### Decisions (7)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/decisions/` | Bearer (any) | 200 — Real DB, returns list |
| POST | `/api/decisions/` | Bearer (operator+) | 200 — Creates draft with trace_id |
| POST | `/api/decisions/{id}/validate` | Bearer (operator+) | 200 — Runs policy checks |
| POST | `/api/decisions/{id}/request-approval` | Bearer (operator+) | 200 — State → pending_approval |
| POST | `/api/decisions/{id}/approve` | Bearer (operator+) | 200 — State → approved |
| POST | `/api/decisions/{id}/reject` | Bearer (operator+) | 200 — State → rejected |
| POST | `/api/decisions/{id}/execute` | Bearer (admin) | 200 — Executes (dry_run supported) |

### Audit (3)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/audit/` | Bearer | 200 — Real DB, shows executed decisions |
| GET | `/api/audit/stats/summary` | Bearer | 200 — `{"total_executions":1,"successful":0,"failed":0,"dry_run":1}` |
| GET | `/api/audit/{entry_id}` | Bearer | 200/404 |

### Policies (3)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/policies/rules` | Bearer | 200 — 6 real rules from DEFAULT_RULES registry |
| GET | `/api/policies/violations` | Bearer | 200 — Real DB (empty when no violations) |
| GET | `/api/policies/rules/{rule_id}` | Bearer | 200 — Single rule lookup |

### Creatives (3)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/creatives/` | Bearer | 200 — Real DB query (empty on fresh DB) |
| POST | `/api/creatives/tag-angles` | Bearer | Functional — Uses real AngleTagger engine |
| POST | `/api/creatives/generate` | Bearer | Functional — Uses real CreativeGenerator engine |

### Saturation (2)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/saturation/analyze` | Bearer | 200 — Returns 5 angles from demo CSV |
| GET | `/api/saturation/angle/{angle_id}` | Bearer | 200 — Single angle lookup |

### Opportunities (2)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/opportunities/` | Bearer | 200 — Returns opportunities from demo_brand.txt |
| GET | `/api/opportunities/{opportunity_id}` | Bearer | 200 — Single lookup |

### Meta OAuth (5)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/meta/oauth/start` | Bearer (admin/CONNECT_META) | 200 — Returns Facebook OAuth URL |
| GET | `/api/meta/oauth/callback` | Public (Meta redirect) | 302 — Processes OAuth callback |
| GET | `/api/meta/adaccounts` | Bearer (any) | 200 — Lists org's ad accounts |
| POST | `/api/meta/adaccounts/select` | Bearer (any) | 200 — Sets active account |
| GET | `/api/meta/adaccounts/active` | Bearer (any) | 200 — Returns active account info |

### Organizations (3)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/api/orgs/` | Bearer (any) | 200 — Lists all orgs |
| POST | `/api/orgs/` | Bearer (admin) | 200 — Creates org |
| POST | `/api/orgs/{org_id}/operator-armed` | Bearer (admin) | 200 — Toggles operator armed |

### Metrics (1)
| Method | Path | Auth | Status |
|--------|------|------|--------|
| GET | `/metrics` | Public | 200 — Prometheus metrics (requests, durations) |

---

## Full Decision Workflow Trace

```
1. POST /api/decisions/      → 200  state=draft      trace_id=draft-d21f099d1bce
2. POST /decisions/{id}/validate        → 200  state=ready      risk=0.0 checks=0
3. POST /decisions/{id}/request-approval → 200  state=pending_approval
4. POST /decisions/{id}/approve          → 200  state=approved
5. POST /decisions/{id}/execute          → 200  state=executed   dry_run=true

Audit log: 1 entry captured
Dashboard KPIs: Executed Today=1, Dry Runs Today=1
```

**Verdict**: Decision lifecycle works end-to-end (draft → validate → approval → execute). Dry run mode functional.

---

## RBAC Verification

| Test | Expected | Actual | Pass? |
|------|----------|--------|-------|
| Viewer GET /api/meta/oauth/start | 403 | 403 | YES |
| Admin GET /api/meta/oauth/start | 200 | 200 | YES |
| No auth GET /api/decisions | 401 | 401 (via 307→401) | YES |
| Admin POST /api/orgs/{id}/operator-armed | 200 | 200 | YES |
| Register new user (existing org) | viewer role | viewer | YES |
| Register duplicate email | 400 | 400 | YES |
| Refresh token | new tokens | new tokens | YES |

---

## Data Source Classification

| Endpoint | Data Source | Real? |
|----------|-----------|-------|
| `/api/dashboard/kpis` | DecisionPack DB queries | YES — Real |
| `/api/decisions/` | DecisionPack DB table | YES — Real |
| `/api/audit/` | DecisionPack + User join | YES — Real |
| `/api/policies/rules` | DEFAULT_RULES registry (Python code) | YES — Real (static config) |
| `/api/policies/violations` | DecisionPack DB queries | YES — Real |
| `/api/creatives/` | Creative DB table | YES — Real |
| `/api/saturation/analyze` | `data/demo_ads_performance.csv` | DEMO — MVP fallback |
| `/api/opportunities/` | `data/demo_brand.txt` via BrandMapBuilder | DEMO — MVP fallback |
| `/api/meta/adaccounts` | AdAccount DB table | YES — Real |
| `/api/orgs/` | Organization DB table | YES — Real |

---

## Critical Findings

### P0: Frontend Has No Login Page
- **Evidence**: `App.tsx` has no `/login` route. `api.ts` has no `Authorization` header. No token storage.
- **Impact**: After FASE 5.3 added auth, ALL frontend API calls return 401. The frontend is non-functional.
- **Fix**: Implement Login page, AuthContext with token storage, Axios interceptor for Bearer header.

### P0: Bootstrap Chicken-and-Egg
- **Evidence**: `POST /api/auth/register` requires `org_id`. `POST /api/orgs/` requires admin auth.
- **Impact**: Cannot create first org + user from API alone. Requires DB seeding script.
- **Fix**: Add `/api/auth/register-with-org` endpoint or allow register without org_id for first user.

### P1: seed_demo.py Uses Invalid Role
- **Evidence**: `seed_demo.py:54` uses `RoleEnum.DIRECTOR`. Auth middleware only recognizes `admin/operator/viewer`.
- **Impact**: Users seeded by seed_demo.py can't log in (no password_hash) and have invalid role.
- **Fix**: Update seed_demo.py to use `RoleEnum.ADMIN` and set `password_hash`.
