# RBAC Matrix — FASE 5.3

**Roles**: `viewer`, `operator`, `admin`
**Default**: First user in org gets `admin`. All subsequent users get `viewer`.
**No admin-by-default**: Every request requires a valid JWT token.

---

## Endpoint x Role Matrix

| Method | Endpoint | viewer | operator | admin | Auth Level |
|--------|----------|--------|----------|-------|------------|
| **Auth (Public — No Token Required)** |
| POST | `/api/auth/login` | - | - | - | Public |
| POST | `/api/auth/register` | - | - | - | Public |
| POST | `/api/auth/refresh` | - | - | - | Public |
| GET | `/api/auth/me` | R | R | R | Any authenticated |
| **Health (Public)** |
| GET | `/api/health` | - | - | - | Public |
| GET | `/api/health/ready` | - | - | - | Public |
| GET | `/api/health/live` | - | - | - | Public |
| GET | `/metrics` | - | - | - | Public |
| **Dashboard (Read-Only)** |
| GET | `/api/dashboard/kpis` | R | R | R | Any authenticated |
| **Audit (Read-Only)** |
| GET | `/api/audit/` | R | R | R | Any authenticated |
| GET | `/api/audit/stats/summary` | R | R | R | Any authenticated |
| GET | `/api/audit/{entry_id}` | R | R | R | Any authenticated |
| **Policies (Read-Only)** |
| GET | `/api/policies/rules` | R | R | R | Any authenticated |
| GET | `/api/policies/violations` | R | R | R | Any authenticated |
| GET | `/api/policies/rules/{rule_id}` | R | R | R | Any authenticated |
| **Creatives (Read-Only + Generate)** |
| GET | `/api/creatives/` | R | R | R | Any authenticated |
| POST | `/api/creatives/tag-angles` | R | R | R | Any authenticated |
| POST | `/api/creatives/generate` | R | R | R | Any authenticated |
| **Saturation (Read + Upload)** |
| GET | `/api/saturation/analyze` | R | R | R | Any authenticated |
| GET | `/api/saturation/angle/{id}` | R | R | R | Any authenticated |
| POST | `/api/saturation/upload-csv` | 403 | W | W | Operator+ |
| **Opportunities (Read-Only)** |
| GET | `/api/opportunities/` | R | R | R | Any authenticated |
| GET | `/api/opportunities/{id}` | R | R | R | Any authenticated |
| **Decisions (RBAC per action)** |
| GET | `/api/decisions/` | R | R | R | Any authenticated |
| GET | `/api/decisions/{id}` | R | R | R | Any authenticated |
| POST | `/api/decisions/` | 403 | W | W | Operator+ |
| POST | `/api/decisions/{id}/validate` | 403 | W | W | Operator+ |
| POST | `/api/decisions/{id}/request-approval` | 403 | W | W | Operator+ |
| POST | `/api/decisions/{id}/approve` | 403 | W | W | Operator+ |
| POST | `/api/decisions/{id}/reject` | 403 | W | W | Operator+ |
| POST | `/api/decisions/{id}/execute` | 403 | 403 | W | Admin only |
| **Meta OAuth + Accounts (FASE 5.4)** |
| GET | `/api/meta/oauth/start` | 403 | 403 | W | Admin only (CONNECT_META) |
| GET | `/api/meta/oauth/callback` | - | - | - | Public (Meta redirect) |
| GET | `/api/meta/adaccounts` | R | R | R | Any authenticated |
| POST | `/api/meta/adaccounts/select` | W | W | W | Any authenticated |
| GET | `/api/meta/adaccounts/active` | R | R | R | Any authenticated |
| **Organizations (Admin manages)** |
| GET | `/api/orgs/` | R | R | R | Any authenticated |
| GET | `/api/orgs/{id}` | R | R | R | Any authenticated |
| GET | `/api/orgs/{id}/ad-accounts` | R | R | R | Any authenticated |
| POST | `/api/orgs/` | 403 | 403 | W | Admin only |
| POST | `/api/orgs/{id}/operator-armed` | 403 | 403 | W | Admin only |

**Legend**: R = Read allowed, W = Write allowed, 403 = Forbidden, `-` = No auth required

---

## Permission Map

| Permission | viewer | operator | admin |
|------------|--------|----------|-------|
| `read:dashboard` | Y | Y | Y |
| `read:decisions` | Y | Y | Y |
| `read:audit` | Y | Y | Y |
| `read:creatives` | Y | Y | Y |
| `read:saturation` | Y | Y | Y |
| `read:opportunities` | Y | Y | Y |
| `read:policies` | Y | Y | Y |
| `read:orgs` | Y | Y | Y |
| `create:decisions` | - | Y | Y |
| `approve:decisions` | - | Y | Y |
| `execute:decisions` | - | - | Y |
| `upload:data` | - | Y | Y |
| `manage:orgs` | - | - | Y |
| `manage:users` | - | - | Y |
| `manage:settings` | - | - | Y |
| `connect:meta` | - | - | Y |

---

## JWT Token Structure

```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "role": "operator",
  "org_id": "org-uuid",
  "type": "access",
  "iat": 1708099200,
  "exp": 1708102800
}
```

| Field | Description |
|-------|-------------|
| `sub` | User UUID (primary key) |
| `email` | User email (for logging) |
| `role` | One of: `viewer`, `operator`, `admin` |
| `org_id` | Organization UUID (multi-tenant scope) |
| `type` | `access` or `refresh` |
| `iat` | Issued at (Unix timestamp) |
| `exp` | Expires at (access: 60min default, refresh: 7 days) |

---

## Token TTL Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | **(required)** | HMAC signing key. Min 32 chars recommended. |
| `JWT_ACCESS_TTL_MINUTES` | `60` | Access token lifetime in minutes |
| `JWT_REFRESH_TTL_DAYS` | `7` | Refresh token lifetime in days |

---

## Security Rules

1. **No admin by default** — First user in org gets admin, rest get viewer
2. **Token required on all protected endpoints** — No anonymous access
3. **User verified in DB on every request** — Deleted users instantly lose access
4. **All requests logged** — `user_id + role + email + path + trace_id`
5. **Passwords hashed** — SHA-256 + salt (upgrade to bcrypt in production)
6. **Tokens never stored in DB** — Stateless JWT, validation via signature only

---

## Test Coverage (28 auth + 20 meta = 48 RBAC-related tests)

| Category | Tests | What's Verified |
|----------|-------|-----------------|
| Authentication (401) | 8 | No token, bad token, expired token, wrong password, missing email |
| Token Lifecycle | 4 | Access works, refresh works, /me works, access-as-refresh fails |
| RBAC Viewer (403) | 7 | Can read all, blocked from create/approve/execute/manage |
| RBAC Operator (403) | 3 | Can create/approve, blocked from execute/manage-orgs |
| RBAC Admin | 3 | Can execute, create orgs, toggle operator armed |
| Registration | 3 | First user = admin, second = viewer, duplicate blocked |
