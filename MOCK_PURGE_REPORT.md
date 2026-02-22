# MOCK PURGE REPORT — FASE 5.1

**Date**: 2026-02-16
**Scope**: Every endpoint, service, engine, frontend page, data file
**Verdict**: 13 mock data sources found. 2 routers not even mounted.

---

## CRITICAL DISCOVERY: Dead Routers

| Router | File | Status |
|--------|------|--------|
| policies | `backend/src/api/policies.py` | **NOT INCLUDED in main.py** — endpoints unreachable |
| audit | `backend/src/api/audit.py` | **NOT INCLUDED in main.py** — endpoints unreachable |

Both files define routes but `backend/main.py` never calls `app.include_router()` for them.
**Fix**: Add both routers to main.py with proper prefixes.

---

## BACKEND MOCKS (by severity)

### CRITICAL — Returns 100% fake data

| # | File | Function | Lines | Mock Type | Fix Plan |
|---|------|----------|-------|-----------|----------|
| 1 | `backend/src/middleware/auth.py` | `get_current_user()` | 61-81 | Returns hardcoded mock admin `dev-user-1` for all requests | Replace with real JWT decode + DB user lookup |
| 2 | `backend/src/middleware/auth.py` | `create_access_token()` | 147-148 | Returns `"mock-jwt-{user_id}"` string | Replace with real `jwt.encode()` using SECRET_KEY |
| 3 | `backend/src/api/policies.py` | `list_policy_rules()` | 50-91 | 5 hardcoded rule dicts | Derive from `DEFAULT_RULES` in `src/core/rules.py` |
| 4 | `backend/src/api/policies.py` | `list_violations()` | 108-127 | 2 hardcoded fake violations | Query `DecisionPack` where `state=BLOCKED` |
| 5 | `backend/src/api/policies.py` | `get_policy_rule()` | 144-162 | 2 hardcoded rule dicts | Derive from `DEFAULT_RULES` registry |
| 6 | `backend/src/api/creatives.py` | `list_creatives()` | 176-193 | 2 hardcoded demo creatives | Query `Creative` DB table |

### HIGH — Uses demo data files instead of DB/API

| # | File | Function | Lines | Mock Type | Fix Plan |
|---|------|----------|-------|-----------|----------|
| 7 | `backend/src/api/creatives.py` | `tag_angles()` | 78-90 | Reads `data/demo_brand.txt` | Accept brand_map_id, load from DB or ChromaDB |
| 8 | `backend/src/api/creatives.py` | `generate_creatives()` | 121-133 | Reads `data/demo_brand.txt` | Accept brand_map_id, load from DB or ChromaDB |
| 9 | `backend/src/api/opportunities.py` | `list_opportunities()` | 38-89 | Reads `data/demo_brand.txt` + rebuilds BrandMap every request | Persist BrandMap, load from DB |
| 10 | `backend/src/api/saturation.py` | `analyze_saturation()` | 68-119 | Reads `data/demo_ads_performance.csv` | Add CSV upload + store in DB, or query Meta API |

### MODERATE — Partial mock (mostly real, some hardcoded fields)

| # | File | Function | Lines | Mock Type | Fix Plan |
|---|------|----------|-------|-----------|----------|
| 11 | `backend/src/api/audit.py` | `list_audit_entries()` | 81 | `user_email="demo@example.com"` hardcoded | Join with `User` table via `created_by_user_id` |
| 12 | `backend/src/api/audit.py` | `get_audit_entry()` | 125 | `user_email="demo@example.com"` hardcoded | Same join |
| 13 | `backend/src/api/audit.py` | `get_audit_stats()` | 162-168 | `successful: 0, failed: 0` hardcoded | Calculate from `execution_result` JSON field |

---

## FRONTEND MOCKS

| # | File | What | Lines | Fix Plan |
|---|------|------|-------|----------|
| 14 | `frontend/src/pages/Dashboard.tsx` | KPI cards: `$1,247.50`, `$42.15`, `3 pending`, `12 executed` | 31-36 | Create `/api/dashboard/kpis` endpoint, fetch real data |
| 15 | `frontend/src/store/index.ts` | `currentUser: { id: 'user-demo-001', name: 'Demo User' }` | 34-39 | Load from auth endpoint after login |
| 16 | `frontend/src/pages/ControlPanel.tsx` | `ad_account_id || 'demo-account-001'` fallback | 74 | Require real ad_account_id selection |
| 17 | `frontend/src/pages/ControlPanel.tsx` | `handleConnectMetaAccount()` shows alert "Coming soon" | 54 | Implement OAuth flow (FASE 5.4) |

---

## ENGINE/ADAPTER MOCKS (Acceptable — DRY_RUN mode)

| # | File | What | Lines | Status |
|---|------|------|-------|--------|
| 18 | `src/adapters/meta_api.py` | `_simulate_response()` in DRY_RUN mode | 131-145 | **ACCEPTABLE** — DRY_RUN is a feature, not a bug |
| 19 | `src/adapters/meta_api.py` | `get_adset_status()` returns fake data in DRY_RUN | 149-150 | **ACCEPTABLE** — safety feature |
| 20 | `src/core/operator.py` | `dry_run: bool = True` default | 47 | **ACCEPTABLE** — safe default |
| 21 | `src/engines/brand_map/builder.py` | Placeholder embeddings (hash-based) | 313-314 | **DEFERRED** — Real embedding pipeline is P2 |

---

## DEMO DATA FILES

| File | Size | Used By | Action |
|------|------|---------|--------|
| `data/demo_brand.txt` | 100 lines | creatives.py, opportunities.py | Keep for demo mode, add DB-backed brand storage |
| `data/demo_ads_performance.csv` | 46 rows | saturation.py | Keep for demo mode, add CSV upload + DB storage |
| `data/v1/ad_summary.csv` | 55 rows | Nothing (archive) | Archive or delete |
| `data/v1/daily_performance.csv` | 3,334 rows | Nothing (archive) | Archive or delete |
| `data/v1/ad_copy.txt` | 102 lines | Nothing (archive) | Archive or delete |
| `COPYS BODYS EL TEMPLO.txt` | 102 lines | Nothing | Move to data/ or delete |
| `EL-TEMPLO-USD-*.csv` | 55 rows | Nothing | Move to data/ or delete |
| `Informe-sin-título-*.csv` | 3,334 rows | Nothing | Move to data/ or delete |

---

## ELIMINATION CHECKLIST

### Phase 5.2 — REAL DATA INTEGRATION (this session)

- [ ] Mount policies + audit routers in main.py
- [ ] policies.py: Derive rules from `DEFAULT_RULES`, violations from `DecisionPack`
- [ ] audit.py: Join User table for real emails, calculate real stats
- [ ] creatives.py `list_creatives()`: Query `Creative` DB table
- [ ] saturation.py: Add CSV upload endpoint alongside demo fallback
- [ ] Dashboard.tsx: Create KPIs endpoint, replace hardcoded values

### Phase 5.3 — AUTH (next)

- [ ] auth.py: Real JWT with `jwt.encode()`/`jwt.decode()` + SECRET_KEY
- [ ] store/index.ts: Remove hardcoded demo user, load from `/api/auth/me`
- [ ] ControlPanel.tsx: Remove `demo-account-001` fallback

### Phase 5.4 — META OAUTH (after auth)

- [ ] ControlPanel.tsx: Replace "Coming soon" alert with OAuth flow
- [ ] creatives.py `tag_angles()` / `generate_creatives()`: Load BrandMap from DB
- [ ] opportunities.py: Load BrandMap from DB instead of demo_brand.txt

---

**Total mock sources**: 21 (13 critical/high, 4 frontend, 4 acceptable DRY_RUN)
**Action required**: 17 items across 3 phases
**Acceptable as-is**: 4 items (DRY_RUN simulation is a safety feature)
