# UI_OPERABILITY_REPORT.md — Frontend Operability Audit

**Date**: 2026-02-16
**Auditor**: Claude (Principal Systems Architect + Production Auditor)
**Frontend**: `http://localhost:5173` (Vite dev server)
**Backend**: `http://localhost:8000` (FastAPI, running)
**Method**: Source code analysis + API call tracing

---

## STATUS UI: NON-FUNCTIONAL (ALL PAGES RETURN 401)

The frontend is architecturally complete — all 9 pages exist, all API calls use real endpoints via centralized `api.ts` client. However, **zero pages display data** because the API client sends no `Authorization` header. Every authenticated endpoint returns 401.

---

## 1. AUTH UX CHECKLIST

| Item | Status | Evidence |
|------|--------|----------|
| Login page exists | NO | `App.tsx` has no `/login` route. No `LoginPage.tsx` file exists. |
| Registration page exists | NO | No `RegisterPage.tsx`. Registration only possible via API (curl). |
| Auth context/provider | NO | No `AuthContext.tsx` or `AuthProvider`. No React context for auth state. |
| Token storage (localStorage) | NO | No code reads/writes `localStorage` for tokens. |
| Axios interceptor (attach Bearer) | NO | `api.ts:8-13` — axios instance has no request interceptor. |
| 401 response handler | NO | No response interceptor to catch 401 → redirect to login. |
| Token refresh flow | NO | No interceptor to call `/api/auth/refresh` on 401. |
| Protected route wrapper | NO | `App.tsx:22-33` — all routes are public, no auth guard. |
| Logout functionality | NO | No logout button or handler anywhere in the frontend. |
| "Remember me" / session persistence | NO | No token persistence mechanism. |
| User display (name/role) | PARTIAL | `store/index.ts` has `currentUser` state but it's never populated. |

**Verdict**: 0/11 auth UX items implemented. The entire auth frontend is missing.

---

## 2. BOOTSTRAP UX CHECKLIST

| Item | Status | Evidence |
|------|--------|----------|
| First-user detection | NO | No API call to check if system is bootstrapped. |
| Onboarding wizard | NO | No onboarding flow exists. |
| Organization creation UI | NO | `organizationsApi.create()` exists but no UI calls it for onboarding. |
| Bootstrap API endpoint | NO | Backend has no `/api/auth/bootstrap` endpoint. |
| Error message for empty state | NO | Pages show generic error (401), not "Please set up your account". |
| Seed data indication | NO | No UI indicator showing demo vs real data. |

**Verdict**: 0/6 bootstrap UX items implemented. New users cannot start from scratch via browser.

---

## 3. BROWSER WALKTHROUGH — Page-by-Page Audit

### 3.1 Dashboard (`/dashboard`)

**Source**: `Dashboard.tsx` (108 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `dashboardApi.getKpis(1)` + `decisionsApi.list({limit:10})` | Lines 22-25 |
| Auth header sent | NO | `api.ts` has no interceptor |
| What user sees | Error state: "Failed to load dashboard data. Backend may be offline." | Line 31 |
| Error handling | YES — shows error + Retry button | Lines 46-51 |
| Loading state | YES — "Loading..." text | Line 45 |
| Empty state | YES — "No decisions yet. Create one from the Control Panel." | Lines 71-74 |
| Data correctness (if auth worked) | Dashboard would show real KPIs from DB | Verified via curl |

**Failure mode**: `Promise.all([kpiRes, decisionsRes])` → both reject with 401 → catch block shows error.

### 3.2 Decision Queue (`/decisions`)

**Source**: `DecisionQueue.tsx` (237 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `decisionsApi.list(params)` | Line 21 |
| Auth header sent | NO | |
| What user sees | Empty list (catches 401 silently in console) | Lines 23-25 |
| State filter buttons | YES — 7 states: all/draft/ready/pending_approval/approved/executed/blocked | Lines 94, 101-109 |
| Action buttons | YES — Validate/Request Approval/Approve/Reject/Execute per state | Lines 196-225 |
| Execute uses `currentUser` | YES — `currentUser!.id` for approve, `currentOrg?.operator_armed` for execute | Lines 52, 73 |
| **Critical**: `currentUser` is null | Will crash on approve/execute | `useStore().currentUser` is never populated |

**Failure modes**:
1. 401 on list → empty queue (silent failure)
2. `currentUser!.id` → null reference crash on approve action
3. `currentOrg?.operator_armed` → always undefined, Execute Live always blocked

### 3.3 Control Panel (`/control-panel`)

**Source**: `ControlPanel.tsx` (399 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `organizationsApi.list()` + `metaApi.getActiveAccount()` + `metaApi.listAdAccounts()` | Lines 54-81 |
| Auth header sent | NO | |
| What user sees | Partially rendered (settings card visible, API calls fail silently) | |
| Operator Armed toggle | YES — calls `organizationsApi.toggleOperatorArmed()` | Lines 83-91 |
| Meta Connect button | YES — calls `metaApi.oauthStart()` → redirects to Facebook OAuth | Lines 94-104 |
| Ad Account selector | YES — dropdown populated from `metaApi.listAdAccounts()` | Lines 233-253 |
| OAuth callback handler | YES — reads `?meta_connected=true` query param | Lines 40-51 |
| Decision form gated | YES — requires `metaConnected` to show form | Lines 272-280 |
| Uses `currentUser.id` | YES — `currentUser.id` for `user_id` in create payload | Line 145 |
| **Critical**: form submit requires `currentUser` | Will show alert "No user logged in" | Line 126 |

**Failure modes**:
1. 401 on all initial API calls → org not loaded, meta state not loaded
2. Form submit → "No user logged in" alert (correct guard exists at line 125-128)
3. Operator armed toggle → 401 error in console

### 3.4 Creatives (`/creatives`)

**Source**: `Creatives.tsx` (126 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `creativesApi.list()` | Line 23 |
| Auth header sent | NO | |
| What user sees | Error state with retry button | |
| Generate button | EXISTS but shows `alert()` — TODO comment | Lines 33-41 |
| "Use in Campaign" button | EXISTS but shows `alert()` | Lines 44-46 |
| i18n support | YES — uses `useLanguage()` context | Line 9 |
| Generate modal | YES — `GenerateCreativeModal` component with form | Lines 118-122 |

**Failure mode**: 401 → error state → "Something went wrong" with Retry.

### 3.5 Saturation (`/saturation`)

**Source**: `Saturation.tsx` (133 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `saturationApi.analyze()` | Line 19 |
| Auth header sent | NO | |
| What user sees | Error state: "Failed to load saturation analysis" | |
| Visualization | YES — saturation bar charts per angle with color coding | Lines 86-98 |
| Status indicators | YES — fresh/moderate/saturated with icons | Lines 29-39 |
| Metric display | YES — CTR trend + frequency per angle | Lines 104-120 |

**Failure mode**: 401 → error state with retry button.

### 3.6 Opportunities (`/opportunities`)

**Source**: `Opportunities.tsx` (97 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `opportunitiesApi.list()` | Line 19 |
| Auth header sent | NO | |
| What user sees | Error state | |
| Priority badges | YES — high/medium/low with color coding | Lines 60-63 |
| Impact display | YES — estimated_impact as percentage | Lines 67-70 |
| Strategy section | YES — recommended strategy per opportunity | Lines 76-83 |
| "Create Campaign" button | EXISTS but no `onClick` handler | Line 88 |

**Failure mode**: 401 → error state. Button is decorative (no handler).

### 3.7 Policies (`/policies`)

**Source**: `Policies.tsx` (136 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `policiesApi.listRules()` | Line 19 |
| Auth header sent | NO | |
| What user sees | Error state | |
| Summary stats | YES — total rules, critical count, total violations | Lines 69-86 |
| Severity badges | YES — critical/high/medium with icons | Lines 29-44 |
| Enabled status | YES — enabled/disabled indicator per rule | Lines 99-111 |

**Failure mode**: 401 → error state. Would display 6 rules correctly if authenticated.

### 3.8 Audit Log (`/audit`)

**Source**: `AuditLog.tsx` (126 lines)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | `auditApi.list()` | Line 19 |
| Auth header sent | NO | |
| What user sees | Loading state, then empty (error not displayed) | |
| Status icons | YES — success/failed/dry_run with color icons | Lines 29-39 |
| Relative timestamps | YES — "X minutes ago" / "X hours ago" | Lines 46-60 |
| "View Details" button | EXISTS but no handler | Line 109 |
| **Bug**: Error state not displayed | Error caught but not rendered in UI | Lines 22-24 vs 76-78 |

**Failure mode**: 401 → `setError(...)` called but error div only shows when `!loading`, and `loading` is set to false correctly. However, there's no error rendering in the template — the error state div is MISSING from the JSX. Lines 76-113 render either loading or entries list, but never the error.

### 3.9 Help (`/help`)

**Source**: Hardcoded content (intentional)

| Check | Result | Evidence |
|-------|--------|----------|
| API calls | NONE | |
| What user sees | Static FAQ content | |
| Interactive | YES — FAQ accordion | |

**Status**: FULLY FUNCTIONAL. Only page that works as-is.

---

## 4. ZUSTAND STORE AUDIT

**Source**: `store/index.ts` (58 lines)

| State Field | Initialized | Populated By | Current Value | Issue |
|-------------|------------|-------------|---------------|-------|
| `currentOrg` | `null` | Should be set after login | `null` | Never set — no auth flow |
| `currentUser` | `null` | Should be set after login | `null` | Never set — causes null reference crashes |
| `activeAdAccount` | `null` | `metaApi.getActiveAccount()` | `null` (401 blocks) | Would work if auth existed |
| `adAccounts` | `[]` | `metaApi.listAdAccounts()` | `[]` (401 blocks) | Would work if auth existed |
| `metaConnected` | `false` | Derived from `activeAdAccount` | `false` | Would work if auth existed |
| `sidebarCollapsed` | `false` | User toggle | Works | No issues |

---

## 5. API CLIENT AUDIT (`api.ts`)

**Source**: `services/api.ts` (239 lines)

| Check | Status | Evidence |
|-------|--------|----------|
| Base URL configurable | YES | `VITE_API_URL` env var with fallback to `localhost:8000/api` |
| Content-Type header | YES | `application/json` |
| Auth header interceptor | MISSING | No request interceptor exists |
| 401 response interceptor | MISSING | No response interceptor exists |
| Token refresh logic | MISSING | No refresh mechanism |
| API modules defined | YES | 10 modules: organizations, meta, decisions, opportunities, policies, creatives, saturation, audit, dashboard, health |
| TypeScript interfaces | YES | All response types defined correctly |
| Request/response types match backend | YES (mostly) | `CreateDecisionData` matches `DecisionCreate` schema |

---

## 6. GAP LIST — PRIORITIZED

### P0: BLOCKING (app non-functional without these)

| # | Gap | File(s) | Impact | Fix |
|---|-----|---------|--------|-----|
| P0-1 | No login page | NEW: `LoginPage.tsx` | Users cannot authenticate | Create login form with email/password |
| P0-2 | No auth context | NEW: `AuthContext.tsx` | No token storage or management | Create context with login/logout/refresh |
| P0-3 | No Axios auth interceptor | `api.ts` | All API calls return 401 | Add request interceptor to attach Bearer token |
| P0-4 | No protected routes | `App.tsx` | Unauthenticated users see all pages | Add route guard component |
| P0-5 | No bootstrap endpoint | Backend: `auth.py` | First user can't register without org_id | Add `/api/auth/bootstrap` or modify register |

### P1: IMPORTANT (functional but broken interactions)

| # | Gap | File(s) | Impact | Fix |
|---|-----|---------|--------|-----|
| P1-1 | `currentUser` null crashes | `DecisionQueue.tsx:52`, `ControlPanel.tsx:145` | Approve/Execute/Create crash | Populate from auth context after login |
| P1-2 | `currentOrg` null | `DecisionQueue.tsx:73` | Execute live check always fails | Populate from auth context |
| P1-3 | Creatives generate = alert() | `Creatives.tsx:35` | Generate button does nothing useful | Wire to `POST /api/creatives/generate` |
| P1-4 | Opportunities "Create Campaign" no handler | `Opportunities.tsx:88` | Button is decorative | Add onClick handler (navigate to ControlPanel) |
| P1-5 | AuditLog error state not rendered | `AuditLog.tsx:76-78` | Error silently swallowed | Add error div to JSX template |
| P1-6 | AuditLog "View Details" no handler | `AuditLog.tsx:109` | Button is decorative | Add modal or detail view |

### P2: IMPROVEMENTS (not blocking but improve quality)

| # | Gap | File(s) | Impact | Fix |
|---|-----|---------|--------|-----|
| P2-1 | No 401 → redirect interceptor | `api.ts` | Users see error states instead of login redirect | Add response interceptor |
| P2-2 | No token refresh | `api.ts` | Session expires after 60min without warning | Add refresh interceptor |
| P2-3 | No logout button | `Layout.tsx` or sidebar | Users can't log out | Add logout in sidebar/header |
| P2-4 | No role-based UI hiding | All pages | Viewers see admin-only buttons | Conditionally render based on user.role |
| P2-5 | No loading skeleton components | All pages | Jarring "Loading..." text | Add skeleton components |
| P2-6 | No demo data indicator | Saturation, Opportunities | Users don't know data is from demo files | Add banner "Using demo data" |

---

## 7. WHAT WORKS TODAY (If Auth Were Added)

If P0-1 through P0-4 were implemented (login page + auth context + interceptor + route guard), the following would immediately work:

| Feature | Confidence | Verified Via |
|---------|-----------|-------------|
| Dashboard shows real KPIs | HIGH | API returns correct data (curl verified) |
| Decision Queue lists all decisions | HIGH | 6 decisions in DB with real state data |
| Decision lifecycle (create→approve→execute) | MEDIUM | Works via API, but needs `currentUser` population |
| Policy rules display (6 rules) | HIGH | API returns real rule data |
| Saturation analysis (5 angles) | HIGH | API returns real analysis from demo CSV |
| Opportunities (5 items) | HIGH | API returns real opportunities from demo brand |
| Audit Log (4 entries) | HIGH | API returns real audit entries with trace_ids |
| Meta OAuth initiation | HIGH | OAuth URL generated correctly |
| Ad account selector | HIGH | Account data in DB |
| Operator Armed toggle | HIGH | API toggles correctly |

**Estimated effort to reach "works in browser"**: 4-6 hours for P0-1 through P0-5.

---

## 8. ARCHITECTURE VERDICT

### Strengths
1. **Clean API client architecture**: Centralized `api.ts` with typed modules — no scattered fetch calls
2. **Zustand store ready**: All state fields defined and typed for auth/meta/UI
3. **Error handling patterns**: Most pages have loading/error/empty states
4. **i18n ready**: Language context exists with EN/ES translations
5. **Component structure**: Modular pages, shared layout, CSS modules

### Weaknesses
1. **Auth is 100% missing**: Not partially done — zero auth code exists in frontend
2. **No middleware layer**: No interceptors, no guards, no auth HOC
3. **Store unpopulated**: Zustand fields exist but nothing populates them
4. **Inconsistent error handling**: AuditLog swallows errors, others display them

### Recommendation
The frontend is **architecturally sound but operationally dead**. The fix is surgical: add auth layer (LoginPage + AuthContext + Interceptor + RouteGuard). Once auth works, 8/9 pages will immediately display real data. The remaining P1 items are polish, not blockers.
