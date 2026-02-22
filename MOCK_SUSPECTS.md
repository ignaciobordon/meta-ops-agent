# MOCK_SUSPECTS.md — Mock/Hardcoded Data Audit

**Date**: 2026-02-16
**Scan**: All `.py` and `.tsx` files in backend/ and frontend/src/

---

## Verdict: Backend APIs Are Real (No Hardcoded Response Data)

All backend API route handlers query real databases via SQLAlchemy ORM. No route returns hardcoded arrays or fake data in the response body.

---

## Demo Data Sources (Intentional MVP Fallbacks)

### 1. `data/demo_brand.txt` — Brand definition for El Templo Calisthenics
| Field | Value |
|-------|-------|
| **Used by** | `backend/src/api/creatives.py` (lines 79, 83, 122, 126) |
| | `backend/src/api/opportunities.py` (lines 39-51) |
| **Purpose** | Input text for BrandMapBuilder engine to generate opportunities and creatives |
| **TODO markers** | `creatives.py:79` — "TODO: In production, load from database using brand_map_id" |
| | `opportunities.py:39` — "TODO: Query BrandMap from database when BrandMap storage is implemented" |
| **Status** | KNOWN MVP FALLBACK. Engines process this file through real code paths. |
| **Approved?** | CONDITIONAL — acceptable for MVP, must implement BrandMap DB storage before production |

### 2. `data/demo_ads_performance.csv` — Meta Ads export (El Templo)
| Field | Value |
|-------|-------|
| **Used by** | `backend/src/api/saturation.py` (lines 66-83) |
| **Purpose** | Input CSV for SaturationEngine analysis |
| **TODO marker** | `saturation.py:72` — "TODO: Load ad performance data from database when Meta API sync is implemented" |
| **Fallback behavior** | If CSV missing → returns empty list. Can be replaced via `/api/saturation/upload-csv` |
| **Status** | KNOWN MVP FALLBACK. SaturationEngine processes this CSV through real code paths. |
| **Approved?** | CONDITIONAL — acceptable because `/upload-csv` endpoint exists for real data |

### 3. `backend/seed_demo.py` — Database seeder
| Field | Value |
|-------|-------|
| **Purpose** | Bootstrap development database with sample org/user/connection |
| **Issues found** | |
| | Line 54: `RoleEnum.DIRECTOR` — invalid role (auth system uses admin/operator/viewer) |
| | Line 43-44: User has no `password_hash` — cannot login |
| | Line 59: MetaConnection with `access_token_encrypted="demo_token_encrypted"` — not real AES-GCM |
| | Line 71: AdAccount with `meta_ad_account_id="act_123456789"` — fake Meta ID |
| **Status** | BROKEN — seed_demo.py creates users that can't authenticate |
| **Approved?** | NO — must be updated to work with FASE 5.3 auth system |

---

## Frontend — Zero Hardcoded Data

| Page | Status | Evidence |
|------|--------|----------|
| Dashboard.tsx | REAL API | `dashboardApi.getKpis()`, `decisionsApi.list()` |
| DecisionQueue.tsx | REAL API | Full CRUD via `decisionsApi.*` |
| ControlPanel.tsx | REAL API | `organizationsApi.list()`, `metaApi.*`, `decisionsApi.create()` |
| Creatives.tsx | REAL API (list) | `creativesApi.list()` — generate has TODO |
| Saturation.tsx | REAL API | `saturationApi.analyze()` |
| Opportunities.tsx | REAL API | `opportunitiesApi.list()` |
| Policies.tsx | REAL API | `policiesApi.listRules()` |
| AuditLog.tsx | REAL API | `auditApi.list()` |
| Help.tsx | HARDCODED | Static FAQ content — intentional, no API needed |

**Key issue**: All pages use real API calls BUT the API client (`api.ts`) has no `Authorization` header, so every call returns 401 in practice.

---

## Previously Purged Mocks (FASE 5.1-5.2)

These were identified and fixed in previous phases:
- Dashboard.tsx hardcoded KPIs → replaced with `dashboardApi.getKpis()`
- store/index.ts demo user → replaced with `null` (populated by auth)
- ControlPanel.tsx `demo-account-001` fallback → removed
- Individual page `fetch()` calls → centralized in `api.ts`
- All confirmed replaced in FASE 5.2 and verified in MOCK_PURGE_REPORT.md

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| Backend route handlers returning hardcoded data | 0 | CLEAN |
| Demo data files used as input sources | 2 | CONDITIONAL (MVP acceptable) |
| Frontend pages with hardcoded data | 1 | ACCEPTABLE (Help page) |
| Broken seed script | 1 | NEEDS FIX |
| TODO comments indicating incomplete features | 4 | TRACKED |
