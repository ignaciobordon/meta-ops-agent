# RUNBOOK_LOCAL_VERIFIED.md — Verified Local Setup

**Date**: 2026-02-16
**Verified on**: Windows 11, Python 3.11.9, Node 18+
**Result**: Backend running on :8000, Frontend on :5173, 28 endpoints verified

---

## Prerequisites

```bash
# Python 3.11+
python --version  # Python 3.11.9

# Node.js 18+ (for frontend)
node --version

# Required Python packages (install globally or in venv)
pip install fastapi uvicorn sqlalchemy pydantic pydantic-settings \
  pyjwt cryptography httpx loguru python-dotenv pandas \
  chromadb prometheus_client
```

---

## Step 1: Configure Environment

Create/update `.env` in project root:

```bash
cd meta-ops-agent

# Required for auth (FASE 5.3)
# Without this, ALL protected endpoints return 500
echo 'JWT_SECRET=your-secret-key-at-least-32-chars-long' >> .env

# Required for Meta OAuth (FASE 5.4)
echo 'META_APP_ID=your_meta_app_id' >> .env
echo 'META_APP_SECRET=your_meta_app_secret' >> .env

# Generate encryption key:
python -c "import base64,os; print('META_TOKEN_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())" >> .env

echo 'META_OAUTH_REDIRECT_URI=http://localhost:8000/api/meta/oauth/callback' >> .env
```

**Minimum `.env` for local development:**
```env
JWT_SECRET=local-dev-jwt-secret-meta-ops-agent-2026
META_APP_ID=test_app_id_local
META_APP_SECRET=test_app_secret_local
META_TOKEN_ENCRYPTION_KEY=dGVzdC1lbmNyeXB0aW9uLWtleS1leGFjdGx5LTMyYiE=
META_OAUTH_REDIRECT_URI=http://localhost:8000/api/meta/oauth/callback
```

---

## Step 2: Start Backend

```bash
cd meta-ops-agent

# Set JWT_SECRET as env var (critical — must match .env or be set separately)
export JWT_SECRET=local-dev-jwt-secret-meta-ops-agent-2026
export META_APP_ID=test_app_id_local
export META_APP_SECRET=test_app_secret_local
export META_TOKEN_ENCRYPTION_KEY=dGVzdC1lbmNyeXB0aW9uLWtleS1leGFjdGx5LTMyYiE=

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

**Expected output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     API_STARTUP | Initializing database...
INFO:     API_STARTUP | Database initialized
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Verify:**
```bash
curl http://localhost:8000/api/health
# {"status":"healthy",...}

curl http://localhost:8000/api/health/ready
# {"ready":true}
```

---

## Step 3: Bootstrap Database (First Time Only)

The API has a chicken-and-egg problem: registration requires an org_id, but creating orgs requires admin auth. Bootstrap via Python:

```bash
cd meta-ops-agent
export JWT_SECRET=local-dev-jwt-secret-meta-ops-agent-2026

python -c "
import sys; sys.path.insert(0, '.')
from uuid import uuid4
from datetime import datetime, timezone
from backend.src.database.session import SessionLocal, init_db
from backend.src.database.models import Organization, User, UserOrgRole, RoleEnum
from backend.src.middleware.auth import hash_password

init_db()
db = SessionLocal()

# Create org
org = Organization(id=uuid4(), name='My Workspace', slug='my-workspace',
    operator_armed=False, created_at=datetime.now(timezone.utc))
db.add(org)
db.flush()

# Create admin user
admin = User(id=uuid4(), email='admin@local.com', name='Admin',
    password_hash=hash_password('admin123'), created_at=datetime.now(timezone.utc))
db.add(admin)
db.flush()

# Assign admin role
role = UserOrgRole(id=uuid4(), user_id=admin.id, org_id=org.id,
    role=RoleEnum.ADMIN, assigned_at=datetime.now(timezone.utc))
db.add(role)
db.commit()

print(f'ORG_ID={org.id}')
print(f'ADMIN: admin@local.com / admin123')
db.close()
"
```

**After bootstrap, login works:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@local.com","password":"admin123"}'
# Returns: {"access_token":"eyJ...", "refresh_token":"eyJ...", ...}
```

---

## Step 4: Start Frontend

```bash
cd meta-ops-agent/frontend
npm install   # first time only
npm run dev
```

**Expected output:**
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
```

**IMPORTANT**: The frontend currently has NO login page. All API calls will return 401.
This is the primary gap to fix (see GAP_TO_DONE.md, item P0-1).

---

## Step 5: Verify API Endpoints

```bash
# Login and capture token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@local.com","password":"admin123"}' | \
  python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test authenticated endpoints
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/dashboard/kpis
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/decisions/
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/audit/
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/policies/rules
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/creatives/
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/saturation/analyze
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/opportunities/
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/meta/adaccounts
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/meta/adaccounts/active
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/orgs/
```

All should return 200 with JSON data.

---

## Step 6: Test Decision Workflow

```bash
# Get org_id and set up ad account first (requires Meta connection)
# Then create decision:
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/decisions/ \
  -d '{"ad_account_id":"UUID","user_id":"UUID","action_type":"budget_change",
       "entity_type":"adset","entity_id":"test_001","entity_name":"Test",
       "payload":{"current_budget":50,"new_budget":60},"rationale":"Testing"}'

# Then: validate → request-approval → approve → execute (dry_run=true)
```

---

## Known Issues

1. **Frontend 401**: No login page or auth token management. Frontend pages show error states.
2. **Bootstrap**: Must seed DB manually for first org/user (see Step 3).
3. **seed_demo.py broken**: Uses `RoleEnum.DIRECTOR` (invalid) and no `password_hash`. Don't use it.
4. **Health endpoint**: Returns 207 "degraded" if disk space is low — cosmetic, not a real issue.
5. **Trailing slash redirects**: Some endpoints redirect 307 when called without trailing slash (e.g., `/api/decisions` → `/api/decisions/`). Use trailing slash consistently.
