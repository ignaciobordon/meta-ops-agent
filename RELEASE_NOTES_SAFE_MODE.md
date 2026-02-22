# RELEASE NOTES — SAFE MODE

**Version**: FASE 5.3 + 5.4 (Auth + RBAC + Meta OAuth + Safe Operations)
**Date**: 2026-02-16
**Status**: All tests green (131 backend + frontend build)

---

## What's New

### Authentication & Authorization (FASE 5.3)
- **JWT Authentication**: HS256 tokens with 60-min access + 7-day refresh rotation
- **Bootstrap Flow**: First-time setup creates org + admin in one step — works from browser (empty DB auto-detected)
- **Login Page**: Dual-mode form (login/bootstrap), auto-detects which mode to show
- **RBAC**: Three roles (admin/operator/viewer) with permission matrix enforced on every endpoint
- **Protected Routes**: All pages require auth; unauthorized access redirects to `/login`
- **Token Refresh**: Transparent auto-refresh via Axios interceptor with concurrent request queue
- **Logout**: Clears tokens + Zustand store, redirects to login

### Meta OAuth & Multi-Account (FASE 5.4)
- **OAuth Flow**: Admin can initiate Meta OAuth, exchange tokens, sync ad accounts
- **Token Encryption**: AES-256-GCM at rest with separate encryption key
- **Account Selection**: Any authenticated user can view/select active ad account
- **Account Gating**: Decision form requires active ad account before submission

### UI Unblocking
- **ControlPanel**: `user_id` from auth context (no more null), `ad_account_id` from store
- **DecisionQueue**: User context from `useAuth()`, safe null check with login redirect
- **AuditLog**: Error state now renders properly, "View Details" toggles JSON expansion
- **Creatives**: "Generate" button wired to `POST /api/creatives/generate` (requires ANTHROPIC_API_KEY)
- **Opportunities**: "Create Campaign" navigates to Control Panel
- **Sidebar**: Shows user name + role, logout button

### Safety Hardening
- **Operator Armed Enforcement**: Backend blocks live execution when `operator_armed=false` (dry_run always allowed)
- **Trailing Slash Normalization**: `redirect_slashes=False` eliminates 307 redirects
- **seed_demo.py Fixed**: Correct role enum + password hash + token placeholder

---

## Files Created

| File | Purpose |
|------|---------|
| `frontend/src/auth/AuthContext.tsx` | Auth state management, token storage, login/bootstrap/logout |
| `frontend/src/auth/ProtectedRoute.tsx` | Route guard — redirects to /login if not authenticated |
| `frontend/src/pages/LoginPage.tsx` | Login + bootstrap dual-mode form |
| `frontend/src/pages/LoginPage.css` | Login page styles |
| `frontend/src/vite-env.d.ts` | Vite TypeScript type declarations |

## Files Modified

| File | Changes |
|------|---------|
| `backend/src/api/auth.py` | Added bootstrap-check + bootstrap endpoints |
| `backend/main.py` | `redirect_slashes=False` |
| `backend/seed_demo.py` | Fixed role enum, added password hash |
| `frontend/src/App.tsx` | AuthProvider wrapping, /login route, ProtectedRoute |
| `frontend/src/services/api.ts` | Auth interceptors (request + response 401 refresh), `creativesApi.generate` |
| `frontend/src/pages/ControlPanel.tsx` | useAuth for user_id, removed unused imports |
| `frontend/src/pages/DecisionQueue.tsx` | useAuth for approve user_id, removed unused import |
| `frontend/src/pages/AuditLog.tsx` | Error state rendering, expandable "View Details" |
| `frontend/src/pages/Creatives.tsx` | Generate wired to API |
| `frontend/src/pages/Opportunities.tsx` | "Create Campaign" onClick navigates to /control-panel |
| `frontend/src/components/layout/Sidebar.tsx` | User info display + logout button |
| `frontend/src/components/layout/Sidebar.css` | Styles for user info + logout |

---

## QA Results

```
Backend:  131/131 tests PASSED (10.41s)
Frontend: tsc + vite build SUCCESS (1573 modules, 0 errors)
```

### Test Breakdown
| Suite | Tests | Status |
|-------|-------|--------|
| test_auth_rbac.py | 28 | PASSED |
| test_meta_oauth.py | 18 | PASSED |
| test_decision_api.py | 8 | PASSED |
| test_decision_service.py | 12 | PASSED |
| test_e2e_workflows.py | 30 | PASSED |
| test_operator.py | 10 | PASSED |
| test_real_data_endpoints.py | 25 | PASSED |
| **Total** | **131** | **ALL GREEN** |

---

## Definition of Done — Verification

| Criteria | Status |
|----------|--------|
| From empty DB: can bootstrap org+admin via browser | DONE |
| Can login and navigate all pages without 401 | DONE |
| Dashboard shows real KPIs from DB | DONE |
| Meta OAuth start returns authorization URL | DONE |
| Can select active ad account | DONE |
| Can create decision from UI (user_id from auth) | DONE |
| Full decision lifecycle in UI (draft→executed DRY_RUN) | DONE |
| AuditLog shows real entries with expandable details | DONE |
| `pytest`: 131/131 PASSED | DONE |
| `npm run build`: 0 errors | DONE |

---

## Known Limitations

1. **Creatives Generate**: Requires `ANTHROPIC_API_KEY` env var — returns 500 without it
2. **Saturation + Opportunities**: Use demo files (`demo_ads_performance.csv`, `demo_brand.txt`)
3. **Live Execution**: Untested against real Meta API (operator_armed=OFF by default)
4. **SQLite**: Single-writer concurrency; production should migrate to PostgreSQL
5. **In-memory state**: Kill switch and cooldown locks reset on server restart
