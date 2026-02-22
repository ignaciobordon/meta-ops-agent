# Meta Ops Agent - Production Audit Checklist

**Audit Date**: _______________
**Auditor**: _______________
**Version/Tag**: _______________

---

## 1. Security Audit

### 1.1 Authentication & Authorization
- [ ] JWT secret key is randomly generated (min 256-bit)
- [ ] JWT tokens have reasonable expiry (24h recommended)
- [ ] All API endpoints require authentication (except /health, /docs)
- [ ] Role-based access control (RBAC) enforced on sensitive operations
- [ ] Director+ role required for decision approval
- [ ] Admin-only access for organization management

### 1.2 Secrets Management
- [ ] No hardcoded API keys, tokens, or passwords in source code
- [ ] All secrets loaded from environment variables (.env)
- [ ] .env file is in .gitignore
- [ ] META_ACCESS_TOKEN is encrypted at rest
- [ ] ANTHROPIC_API_KEY is never exposed in logs or API responses
- [ ] Database password is unique and strong (min 20 chars)

### 1.3 Input Validation
- [ ] All API inputs validated via Pydantic models
- [ ] SQL injection prevention via SQLAlchemy ORM (no raw queries)
- [ ] XSS prevention (JSON-only API, no HTML rendering)
- [ ] Budget change limits enforced by PolicyEngine (max 20% increase)
- [ ] Entity IDs validated as proper format

### 1.4 Network Security
- [ ] HTTPS enforced (HTTP redirects to HTTPS)
- [ ] SSL/TLS certificate valid and auto-renewing
- [ ] CORS restricted to known frontend origins
- [ ] Rate limiting active (100 req/min per client)
- [ ] Security headers configured in Nginx (X-Frame-Options, CSP, etc.)
- [ ] Database not exposed to public network (localhost only)

### 1.5 Dependency Security
- [ ] No known CVEs in Python dependencies (`pip audit`)
- [ ] No known CVEs in Node.js dependencies (`npm audit`)
- [ ] Dependencies pinned to specific versions
- [ ] No unnecessary packages installed

---

## 2. Application Architecture

### 2.1 Backend (FastAPI)
- [ ] Application starts without errors
- [ ] All routers registered (health, orgs, decisions, creatives, saturation)
- [ ] Database migrations up to date (`alembic current`)
- [ ] Error handling returns proper HTTP status codes
- [ ] Logging structured with trace IDs

### 2.2 Database (PostgreSQL)
- [ ] Database created and accessible
- [ ] All tables created via Alembic migrations
- [ ] Foreign key constraints in place
- [ ] Indexes on frequently queried columns (email, trace_id, state, created_at)
- [ ] UUID primary keys on all tables
- [ ] Connection pooling configured

### 2.3 Frontend (React/Vite)
- [ ] Production build succeeds (`npm run build`)
- [ ] No console errors on load
- [ ] API base URL configured for production
- [ ] Environment variables set correctly

### 2.4 Middleware Stack
- [ ] MetricsMiddleware tracking HTTP requests
- [ ] RateLimitMiddleware active (100 req/min)
- [ ] CORS middleware allowing only known origins

---

## 3. Functionality Verification

### 3.1 Health Endpoints
- [ ] `GET /api/health` returns comprehensive status
- [ ] `GET /api/health/ready` returns readiness for k8s
- [ ] `GET /api/health/live` returns liveness probe
- [ ] `GET /metrics` returns Prometheus metrics

### 3.2 Organization Management
- [ ] Create organization works
- [ ] List organizations works
- [ ] Get organization by ID works
- [ ] Toggle operator_armed works
- [ ] List ad accounts for org works
- [ ] Duplicate slug returns 400

### 3.3 Decision Lifecycle
- [ ] Create draft decision works
- [ ] Policy validation correctly approves/blocks
- [ ] Request approval state transition works
- [ ] Approve decision works (Director+ only)
- [ ] Reject decision works with reason
- [ ] Execute decision (dry-run) works
- [ ] Execute decision (live) works when operator_armed=true
- [ ] State machine prevents invalid transitions

### 3.4 Policy Engine
- [ ] Budget change within limits (10%) passes validation
- [ ] Budget change exceeding limits (100%) gets blocked
- [ ] creative_edit action type is always blocked
- [ ] Cooldown periods enforced between changes

### 3.5 Saturation Analysis
- [ ] Demo CSV analysis returns proper results
- [ ] Saturation scores in valid range (0-100)
- [ ] Recommendations are meaningful (keep/monitor/refresh/kill)

---

## 4. Performance

### 4.1 Response Times
- [ ] Health check responds in < 500ms
- [ ] API endpoints respond in < 2s under normal load
- [ ] Database queries use proper indexes
- [ ] No N+1 query patterns

### 4.2 Resource Usage
- [ ] Memory usage stable (no leaks over 24h)
- [ ] CPU usage reasonable under normal load
- [ ] Disk space adequate (>20% free)
- [ ] Database connections properly pooled and released

### 4.3 Scalability
- [ ] Gunicorn/Uvicorn worker count appropriate for CPU cores
- [ ] Database connection pool size matches worker count
- [ ] ChromaDB can handle expected vector volume

---

## 5. Monitoring & Observability

### 5.1 Health Checks
- [ ] Health endpoint checks database connectivity
- [ ] Health endpoint checks ChromaDB availability
- [ ] Health endpoint checks API key configuration
- [ ] Health endpoint checks disk space
- [ ] Degraded status returned when non-critical deps fail
- [ ] Unhealthy status returned when critical deps fail

### 5.2 Metrics
- [ ] HTTP request count tracked
- [ ] HTTP request duration histogram
- [ ] Decision creation counter
- [ ] Decision state transition counter
- [ ] Engine execution duration
- [ ] Rate limit exceeded counter
- [ ] Prometheus scrape endpoint accessible

### 5.3 Logging
- [ ] Structured JSON logging configured
- [ ] Trace IDs present in all decision-related logs
- [ ] Log rotation configured (max 100MB per file)
- [ ] No sensitive data in logs (tokens, passwords)
- [ ] Log levels appropriate (INFO in prod, no DEBUG)

### 5.4 Alerting
- [ ] Health check monitoring script installed
- [ ] Auto-restart on health check failure (with cooldown)
- [ ] Disk space alerts configured (< 10% warning)
- [ ] Error rate alerting threshold defined

---

## 6. Data Management

### 6.1 Backup Strategy
- [ ] PostgreSQL daily backup configured (2 AM)
- [ ] ChromaDB backup configured (3 AM)
- [ ] Backup retention policy set (30 days DB, 14 days ChromaDB)
- [ ] Backup verification script runs daily
- [ ] Backup restoration tested successfully

### 6.2 Data Integrity
- [ ] Foreign key constraints enforced in database
- [ ] Enum values validated (DecisionState, RoleEnum, ActionType)
- [ ] UUID uniqueness guaranteed
- [ ] Audit trail immutable (append-only)
- [ ] Timestamps in UTC

### 6.3 Data Privacy
- [ ] No PII stored unnecessarily
- [ ] Meta API tokens encrypted
- [ ] User passwords hashed (never stored plaintext)
- [ ] Audit logs don't contain sensitive data

---

## 7. Deployment Readiness

### 7.1 Configuration
- [ ] .env.template documents all required variables
- [ ] Production .env file populated
- [ ] Database URL configured for production
- [ ] CORS origins set to production frontend URL
- [ ] Debug mode OFF

### 7.2 Infrastructure
- [ ] Server provisioned (Ubuntu 22.04 LTS)
- [ ] Python 3.11+ installed
- [ ] PostgreSQL 16 installed and configured
- [ ] Nginx installed with SSL
- [ ] Systemd service configured for auto-restart
- [ ] Firewall configured (only 80, 443, 22)

### 7.3 CI/CD
- [ ] Git repository clean (no uncommitted changes)
- [ ] Production branch tagged
- [ ] Deployment guide (DEPLOYMENT.md) reviewed
- [ ] Rollback procedure (ROLLBACK.md) reviewed
- [ ] Meta API testing procedure (META_API_TESTING.md) reviewed

---

## 8. Testing Sign-Off

### 8.1 Test Results

| Test Suite | Tests | Passing | Status |
|------------|-------|---------|--------|
| E2E Workflows | 30 | 30 | PASS |
| Integration Pipeline | 8 | -- | VERIFY |
| Decision API | 7 | -- | VERIFY |
| Decision Service | -- | -- | VERIFY |

### 8.2 Test Coverage Areas
- [ ] Health/observability endpoints tested
- [ ] Organization CRUD tested
- [ ] Decision full lifecycle tested (create -> execute)
- [ ] Policy enforcement tested (pass and block)
- [ ] Error handling tested (404, 422, invalid state)
- [ ] Cross-cutting concerns tested (CORS, content types, docs)
- [ ] Data integrity tested (timestamps, independence)

---

## 9. Documentation Completeness

- [ ] DEPLOYMENT.md - Server setup and deployment guide
- [ ] ROLLBACK.md - Disaster recovery and rollback procedures
- [ ] META_API_TESTING.md - Meta API integration testing
- [ ] PRODUCTION_AUDIT.md - This production audit checklist
- [ ] README.md - Project overview and setup
- [ ] API documentation auto-generated via OpenAPI (/docs)

---

## 10. Final Sign-Off

| Area | Reviewer | Date | Status |
|------|----------|------|--------|
| Security | __________ | __________ | [ ] Approved |
| Backend | __________ | __________ | [ ] Approved |
| Frontend | __________ | __________ | [ ] Approved |
| Database | __________ | __________ | [ ] Approved |
| Infrastructure | __________ | __________ | [ ] Approved |
| Monitoring | __________ | __________ | [ ] Approved |

### Go/No-Go Decision

- [ ] **GO** - All checks pass, approved for production deployment
- [ ] **NO-GO** - Issues found, remediation required before deployment

**Notes**: _____________________________________________

---

## Appendix: Quick Verification Commands

```bash
# 1. Application starts
cd /opt/meta-ops-agent/backend && python main.py

# 2. Health check
curl -s http://localhost:8000/api/health | python3 -m json.tool

# 3. Metrics
curl -s http://localhost:8000/metrics | head -20

# 4. OpenAPI docs
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Title: {d[\"info\"][\"title\"]}'); print(f'Version: {d[\"info\"][\"version\"]}'); print(f'Paths: {len(d[\"paths\"])}')"

# 5. Run E2E tests
python -m pytest tests/test_e2e_workflows.py -v

# 6. Check database
sudo -u postgres psql meta_ops_agent -c "SELECT tablename FROM pg_tables WHERE schemaname='public';"

# 7. Check SSL
curl -vI https://your-domain.com 2>&1 | grep -E "SSL|subject|expire"

# 8. Check logs
sudo journalctl -u meta-ops-agent --since "1 hour ago" | tail -20
```
