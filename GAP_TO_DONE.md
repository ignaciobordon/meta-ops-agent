# GAP_TO_DONE.md — Gap Analysis: Current State → "App Lista para Operar (SAFE)"

**Date**: 2026-02-16
**Goal**: App usable in SAFE mode (connection, approval, dry-run). No live mutations.
**Baseline**: 28 backend endpoints working, 131/131 tests passing, frontend pages wired to API

---

## INVENTARIO: What Works Today

### Backend — FULLY FUNCTIONAL
| Module | Status | Evidence |
|--------|--------|----------|
| Auth (login/register/refresh/me) | WORKING | 200 on all endpoints, JWT tokens, RBAC enforced |
| Dashboard KPIs | WORKING | Real DB queries, reflects decision execution data |
| Decision Lifecycle (7 endpoints) | WORKING | Full state machine: draft→validate→approve→execute(dry_run) |
| Audit Log (3 endpoints) | WORKING | Real DB queries, user joins, stats |
| Policies (3 endpoints) | WORKING | 6 real rules from DEFAULT_RULES, violations from DB |
| Creatives (3 endpoints) | WORKING | DB query for list, real engine for tag/generate |
| Saturation (2 endpoints) | WORKING | Real engine, uses demo CSV as MVP fallback |
| Opportunities (2 endpoints) | WORKING | Real engine, uses demo_brand.txt as MVP fallback |
| Meta OAuth (5 endpoints) | WORKING | OAuth flow, token encryption, account management |
| Organizations (3 endpoints) | WORKING | CRUD, operator armed toggle |
| Health + Metrics (4 endpoints) | WORKING | Health/ready/live + Prometheus metrics |

### Frontend — API WIRING DONE, AUTH MISSING
| Page | API Wiring | Displays Data? |
|------|-----------|---------------|
| Dashboard | Real API calls | NO — 401 (no auth token) |
| Decision Queue | Real API calls | NO — 401 |
| Control Panel | Real API calls + OAuth | NO — 401 |
| Creatives | Real API calls | NO — 401 |
| Saturation | Real API calls | NO — 401 |
| Opportunities | Real API calls | NO — 401 |
| Policies | Real API calls | NO — 401 |
| Audit Log | Real API calls | NO — 401 |
| Help | Hardcoded (intentional) | YES |

---

## MAPA: Module Completion Status

| Module | Plan Status | Gaps |
|--------|------------|------|
| Database models | COMPLETE | No gaps |
| Auth middleware (RBAC) | COMPLETE | No gaps |
| Auth API endpoints | COMPLETE | No gaps |
| Decision service + API | COMPLETE | No gaps |
| Policy engine | COMPLETE | No gaps |
| Audit system | COMPLETE | No gaps |
| Meta OAuth backend | COMPLETE | No gaps |
| Token encryption (AES-GCM) | COMPLETE | No gaps |
| Frontend API client (api.ts) | COMPLETE | No gaps |
| Frontend state (Zustand) | COMPLETE | No gaps |
| Frontend pages (wiring) | COMPLETE | No gaps |
| **Frontend auth flow** | **MISSING** | No login page, no token storage, no auth headers |
| **Frontend onboarding** | **MISSING** | No org creation flow for first user |
| **DB bootstrap** | **PARTIAL** | seed_demo.py broken (wrong role, no password) |

---

## DEUDA TECNICA Y FUNCIONAL

### P0 — BLOQUEANTES (app no funciona sin esto)

#### P0-1: Frontend Login Page + Auth Context
- **Evidencia**: `App.tsx` has no `/login` route. `api.ts` has no `Authorization` header injection.
- **Impacto**: TODAS las paginas del frontend retornan 401. La app es completamente no-funcional desde el browser.
- **Fix propuesto**:
  1. Create `LoginPage.tsx` with email/password form
  2. Create `AuthContext.tsx` with token storage (localStorage), login/logout/refresh logic
  3. Add Axios interceptor in `api.ts` to attach `Authorization: Bearer {token}` to all requests
  4. Add Axios response interceptor to catch 401 → redirect to login
  5. Wrap `App.tsx` routes in `<AuthProvider>` with protected route component
  6. Add `/login` route (public) and gate all other routes behind auth
- **Esfuerzo**: 4-6 horas

#### P0-2: Bootstrap / Onboarding Flow
- **Evidencia**: `POST /api/auth/register` requires `org_id`. `POST /api/orgs/` requires admin auth. No way to create first user.
- **Impacto**: No se puede arrancar la app desde cero sin scripts manuales de DB.
- **Fix propuesto** (option A — recommended):
  1. Add `POST /api/auth/bootstrap` endpoint: creates org + first admin user in one call
  2. Only works when DB has zero organizations (prevents abuse)
  3. Frontend detects empty state → shows onboarding wizard
- **Fix propuesto** (option B — simpler):
  1. Update `POST /api/auth/register` to auto-create org when `org_name` is provided and no orgs exist
- **Esfuerzo**: 2-3 horas

#### P0-3: Fix seed_demo.py
- **Evidencia**: Line 54 uses `RoleEnum.DIRECTOR` (auth only knows admin/operator/viewer). Line 43: User has no `password_hash`.
- **Impacto**: seed_demo.py crea datos inutilizables — users que no pueden loguearse.
- **Fix propuesto**: Update to use `RoleEnum.ADMIN`, add `password_hash=hash_password("demo123")`.
- **Esfuerzo**: 15 minutos

---

### P1 — IMPORTANTES (funcional pero con fricciones)

#### P1-1: Frontend Decision Form Needs user_id from Auth Context
- **Evidencia**: `DecisionCreate` schema requires `user_id` and `ad_account_id` in body. ControlPanel.tsx doesn't pass these from auth context.
- **Impacto**: Decision creation will fail from UI even after login is implemented.
- **Fix propuesto**: Extract `user_id` from auth context, `ad_account_id` from store's `activeAdAccount`.
- **Esfuerzo**: 1 hora

#### P1-2: Creatives Generate Button Not Connected
- **Evidencia**: `Creatives.tsx:35` — `// TODO: Call API to generate creative`. Currently shows `alert()`.
- **Impacto**: "Generate New" button in Creatives page does nothing useful.
- **Fix propuesto**: Implement `creativesApi.generate(payload)` call and handle response.
- **Esfuerzo**: 1 hora

#### P1-3: Opportunities "Create Campaign" Button No Handler
- **Evidencia**: `Opportunities.tsx:88` — button has no onClick handler.
- **Impacto**: Users can see opportunities but can't act on them.
- **Fix propuesto**: Navigate to ControlPanel with pre-filled data, or open decision creation modal.
- **Esfuerzo**: 1-2 horas

#### P1-4: AuditLog Missing Error State Display
- **Evidencia**: `AuditLog.tsx` catches error but doesn't display it in UI.
- **Impacto**: Users see blank page instead of error message when API fails.
- **Fix propuesto**: Add error state display similar to Dashboard.tsx pattern.
- **Esfuerzo**: 30 minutos

#### P1-5: AuditLog "View Details" Button No Handler
- **Evidencia**: `AuditLog.tsx:109` — "View Details" button exists but does nothing.
- **Impacto**: Users can't drill into individual audit entries.
- **Fix propuesto**: Add modal or navigate to detail view with `auditApi.get(id)`.
- **Esfuerzo**: 1 hora

#### P1-6: Trailing Slash Inconsistency (307 Redirects)
- **Evidencia**: `/api/decisions` returns 307 redirect to `/api/decisions/`. Same for `/api/orgs`.
- **Impacto**: Potential issues with CORS, preflight requests, or frontend clients that don't follow redirects.
- **Fix propuesto**: Either standardize all routes with trailing slash or add `redirect_slashes=False` to FastAPI app.
- **Esfuerzo**: 30 minutos

---

### P2 — MEJORAS (no bloquean pero mejoran calidad)

#### P2-1: Saturation/Opportunities Use Demo Data Files
- **Evidencia**: `saturation.py:77` loads `demo_ads_performance.csv`. `opportunities.py:45` loads `demo_brand.txt`.
- **Impacto**: Data shown is from static files, not from user's Meta account.
- **Fix propuesto**: Implement Meta API data sync (FASE 5.5+) or make CSV upload more prominent.
- **Esfuerzo**: Depends on Meta API scope

#### P2-2: Decision `validate` Returns 0 Policy Checks
- **Evidencia**: Validation runs but `policy_checks=[]` and `risk_score=0.0` in smoke test.
- **Impacto**: No actual policy enforcement happening on decisions.
- **Fix propuesto**: Wire PolicyEngine checks into DecisionService.validate() properly.
- **Esfuerzo**: 2-3 horas

#### P2-3: Operator Armed Doesn't Gate Decision Execution in Backend
- **Evidencia**: Can execute decisions even when `operator_armed=False`.
- **Impacto**: The safety switch is frontend-only (DecisionQueue.tsx checks it), backend doesn't enforce.
- **Fix propuesto**: Add `operator_armed` check in `execute()` endpoint.
- **Esfuerzo**: 30 minutos

#### P2-4: No Frontend Token Refresh Flow
- **Evidencia**: No Axios interceptor for 401 → refresh token → retry.
- **Impacto**: Users get logged out after 60 minutes without warning.
- **Fix propuesto**: Add interceptor that catches 401, calls `/api/auth/refresh`, retries original request.
- **Esfuerzo**: 1-2 horas (part of P0-1)

#### P2-5: Health Returns 207 "Degraded" on Low Disk
- **Evidencia**: Health endpoint checks disk space and marks "degraded" at 1.1% free.
- **Impacto**: Cosmetic — not a real issue for functionality.
- **Fix propuesto**: Lower the threshold or make it configurable.
- **Esfuerzo**: 15 minutos

---

## CHECKLIST DE CIERRE: "App Lista para Operar (SAFE)"

- [ ] **P0-1**: Frontend login page + auth context + Axios interceptor
- [ ] **P0-2**: Bootstrap/onboarding endpoint (register-with-org)
- [ ] **P0-3**: Fix seed_demo.py (role + password)
- [ ] **P1-1**: Wire user_id/ad_account_id in decision form
- [ ] **P1-2**: Connect creatives generate button
- [ ] **P1-4**: Add error state to AuditLog
- [ ] **P1-6**: Fix trailing slash redirects
- [ ] **P2-3**: Backend enforcement of operator_armed on execute
- [ ] Verify: User can register/login through browser
- [ ] Verify: Dashboard shows real KPIs after creating decisions
- [ ] Verify: Decision lifecycle works from UI (create → approve → dry_run)
- [ ] Verify: Meta OAuth initiates from "Connect" button
- [ ] Verify: Ad account selector works after connection
- [ ] Verify: Audit log shows executed decisions
- [ ] Frontend build (`npm run build`) succeeds with no TypeScript errors

---

## NEXT SPRINT PLAN (3-5 Days)

### Day 1: Auth Frontend (P0-1 + P0-2)
- Create `LoginPage.tsx` (email/password form, styled to match app theme)
- Create `AuthContext.tsx` (login/logout/refresh, localStorage token management)
- Add Axios interceptor in `api.ts` (attach Bearer header, handle 401)
- Add `POST /api/auth/bootstrap` endpoint (org creation + first admin)
- Add protected route wrapper in `App.tsx`
- Test: Can register first user from browser, login, see dashboard

### Day 2: Fix Decision Flow (P0-3 + P1-1 + P1-2)
- Fix `seed_demo.py` (admin role, password hash)
- Wire `user_id` from AuthContext and `ad_account_id` from store into decision creation form
- Connect creatives generate button to `POST /api/creatives/generate`
- Test: Full decision lifecycle from browser (create → validate → approve → dry_run)

### Day 3: Polish + Safety (P1-4 + P1-6 + P2-3)
- Add error state to AuditLog page
- Fix trailing slash redirects (`redirect_slashes=False`)
- Add `operator_armed` backend check on decision execution
- Wire "View Details" in audit log
- Test: Toggle operator armed OFF → verify execution blocked

### Day 4: Integration Testing + QA
- Full browser walkthrough: register → login → connect Meta → select account → create decision → approve → dry_run → verify audit + dashboard
- Test viewer/operator roles from browser
- Fix any discovered issues
- Run `npm run build` and fix TypeScript errors

### Day 5: Documentation + Demo
- Update HANDOFF_NOTES.md with FASE 5.5 prep
- Record demo video or write demo script
- Tag release as `v0.5.4-safe`

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Auth implementation creates regressions | Medium | High | Run 131 backend tests after changes |
| Meta OAuth fails with real Meta app | Low | Medium | Already works with test credentials |
| TypeScript build fails | Medium | Low | Fix type errors incrementally |
| Token refresh race condition | Low | Medium | Implement mutex/queue for refresh calls |
