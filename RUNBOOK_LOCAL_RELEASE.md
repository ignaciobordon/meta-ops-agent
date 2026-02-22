# Runbook — Local Release (Meta Ops Agent)

Step-by-step guide to run Meta Ops Agent on localhost.

---

## 1. Prerequisites

| Requirement    | Version   | Notes                                      |
|----------------|-----------|--------------------------------------------|
| Python         | 3.11+     | Required for backend                       |
| Node.js        | 18+       | Required for frontend build                |
| npm            | 9+        | Comes with Node.js                         |
| Redis          | Any       | **Optional** — jobs use sync fallback if unavailable |

---

## 2. Clone & Setup

```bash
git clone <repo>
cd meta-ops-agent

# Copy environment template and edit with your keys
cp .env.template .env
# Edit .env with your ANTHROPIC_API_KEY, META_APP_ID, META_APP_SECRET, etc.

# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..
```

---

## 3. Environment Check

Run the pre-flight validation script to verify your environment is correctly configured:

```bash
python scripts/env_check.py
```

This checks:
- Python version and required packages
- Required environment variables (API keys, secrets)
- Port availability (8000, 5173)
- Optional service availability (Redis, PostgreSQL)

---

## 4. Start All Services

```bash
bash scripts/dev_up.sh
```

This starts the backend (FastAPI on port 8000) and frontend (Vite on port 5173) in the background. If Redis is available, Celery workers are also started.

---

## 5. Access the Application

| Service       | URL                            |
|---------------|--------------------------------|
| Frontend      | http://localhost:5173          |
| Backend API   | http://localhost:8000          |
| API Docs      | http://localhost:8000/docs     |

---

## 6. Login

Use the default admin credentials:

- **Email:** `admin@example.com`
- **Password:** `admin123`

---

## 7. Smoke Test

With the application running, execute the automated smoke tests to verify core functionality:

```bash
python scripts/smoke_local.py
```

This validates:
- API health endpoint responds
- Authentication flow works
- Job submission and completion
- Meta connection endpoint availability

---

## 8. Stop All Services

```bash
bash scripts/dev_down.sh
```

This cleanly shuts down the backend, frontend, and any Celery workers.

---

## 9. Troubleshooting

### "Redis not running"

This is **not a problem**. Jobs will run via the sync fallback (in-process execution). No action needed. You will see a log message like:

```
WARNING: Celery broker unreachable, using sync fallback
```

### "ANTHROPIC_API_KEY not set"

Set it in your `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Without this key, LLM-powered features (creative generation, opportunity analysis) will not work. Other features remain functional.

### "Job timed out"

Jobs have a 2-3 minute execution timeout. If a job times out:

1. Open the **Ops Console** to see the error details (error code and message)
2. Use the **Retry** button in the Creatives or Opportunities view to re-run the job

### "Frontend not loading"

Ensure frontend dependencies are installed:

```bash
cd frontend && npm install
```

Then restart via `bash scripts/dev_up.sh`.

---

## 10. Running Tests

Run the full backend test suite:

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_pipeline.py
```

Expected result: ~681 tests passing.

---

## 11. Frontend Build Check

Verify the frontend compiles without TypeScript errors:

```bash
cd frontend && npm run build
```

Expected result: Clean build with 0 errors.
