# PIPELINE_TRACE.md — End-to-End Pipeline Execution Trace

**Date**: 2026-02-16
**Server**: `http://localhost:8000` (live session, uptime 14309s)
**Auth**: `admin@audit.com` / `admin123` (admin role)
**Method**: Real HTTP requests against running server + direct Python execution

---

## Trace A: Happy Path — Decision Lifecycle (Budget Change Within Policy Limits)

### Step 1: Authentication
```
POST /api/auth/login
  Body: {"email":"admin@audit.com","password":"admin123"}
  → 200 OK
  → access_token: eyJ... (HS256 JWT, 60-min expiry)
  → role: admin
  → org_id: cc57d41a-7980-4d6e-92f8-09fd8fedcefa
```

### Step 2: Create Decision Draft
```
POST /api/decisions/
  Auth: Bearer {token}
  Body: {
    "ad_account_id": "1c926037-920a-4900-a64b-100e718680d7",
    "user_id": "305f6a56-7065-452c-bc72-a405682a831b",
    "action_type": "budget_change",
    "entity_type": "adset",
    "entity_id": "audit_pipeline_002",
    "entity_name": "Audit Pipeline Trace",
    "payload": {"current_budget": 50, "new_budget": 55},
    "rationale": "Pipeline trace for audit - within policy limits"
  }
  → 200 OK
  → id: e7217bdb-6e07-4967-9c28-12bd7fb091f3
  → trace_id: draft-cf28f28c86b7
  → state: draft
  → created_at: 2026-02-16T19:26:06.204899
```
**What happened**: DecisionService creates DecisionPack in SQLite with state=draft, assigns trace_id.

### Step 3: Validate Decision (Policy Check)
```
POST /api/decisions/{id}/validate
  → 200 OK
  → state: ready
  → risk_score: 0.0
  → policy_checks: 0 checks
  → validated_at: 2026-02-16T19:26:06.702461
```
**What happened**: PolicyEngine evaluated 5 rules against the action. Budget change = 10% (50→55), which is under the 20% BudgetDeltaRule threshold. All rules passed. State transitions: draft → ready.

**Note**: `policy_checks=0` returned because the backend validation only returns checks that failed or had warnings. No failures = empty array.

### Step 4: Request Approval
```
POST /api/decisions/{id}/request-approval
  → 200 OK
  → state: pending_approval
```
**What happened**: State machine validates current state is `ready`, transitions to `pending_approval`. Decision is now visible to approvers.

### Step 5: Approve Decision
```
POST /api/decisions/{id}/approve
  Body: {"approver_user_id": "305f6a56-7065-452c-bc72-a405682a831b"}
  → 200 OK
  → state: approved
  → approved_at: 2026-02-16T19:26:07.228584
```
**What happened**: State validates current state is `pending_approval`, records approver and timestamp, transitions to `approved`.

### Step 6: Execute (Dry Run)
```
POST /api/decisions/{id}/execute
  Body: {"dry_run": true}
  → 200 OK
  → state: executed
  → executed_at: 2026-02-16T19:26:07.495148
```
**What happened**: Operator executes in DRY_RUN mode. No Meta API calls made. State transitions: approved → executed. Audit log entry created with status=dry_run.

### Verification: Dashboard Updated
```
GET /api/dashboard/kpis
  → Pending Approvals: 0
  → Executed Today: 4
  → Blocked by Policy: 2
  → Dry Runs Today: 4
```

### Verification: Audit Log Updated
```
GET /api/audit/
  → Total entries: 4
  → Latest: draft-cf28f28c86b7 status=dry_run

GET /api/audit/stats/summary
  → total_executions: 4
  → successful: 0
  → failed: 0
  → dry_run: 4
  → period_days: 7
```

### Happy Path State Machine
```
draft ──validate──→ ready ──request-approval──→ pending_approval ──approve──→ approved ──execute──→ executed
  ↑                                                                  │
  │                                                                  └──reject──→ rejected
  └──────────────────────────────────────────────────────────────────────────────────────────
```

---

## Trace B: Policy Block Path — Budget Exceeds Threshold

### Step 1: Create Decision Draft
```
POST /api/decisions/
  Body: {
    ...
    "payload": {"current_budget": 50, "new_budget": 65},
    "rationale": "This should be blocked by BudgetDeltaRule"
  }
  → 200 OK
  → state: draft
```

### Step 2: Validate (BLOCKED)
```
POST /api/decisions/{id}/validate
  → 200 OK
  → state: blocked
  → risk_score: 0.0
  → policy_checks: 1
    BudgetDeltaRule: passed=False severity=block
    Message: "Budget change 30.0% exceeds max allowed 20%."
```
**What happened**: PolicyEngine's BudgetDeltaRule detected 30% change (50→65), exceeding the 20% maximum. Decision blocked. State transitions: draft → blocked (terminal state).

### Blocked State — No Further Transitions Possible
```
POST /api/decisions/{id}/request-approval
  → 400 Bad Request
  → "Cannot transition from state blocked to pending_approval"
```
**Proof**: Blocked decisions are terminal. The state machine enforces this correctly.

---

## Trace C: CP Engine Direct Execution Chain

### CP0 → CP2: Vector Store + Tagger
```python
# CP0: ChromaDB initialized at ./chroma_data
vdb = VectorDBClient()
col = vdb.client.get_or_create_collection('audit_test')
col.upsert(ids=['test1'], documents=['Audit runtime proof'])
col.query(query_texts=['audit']) → "Audit runtime proof"

# CP2: Tagger uses ChromaDB for centroid storage
tagger = Tagger()  # Loads all-MiniLM-L6-v2, creates 45 centroids in ChromaDB
result = tagger.classify('Get 50% off - limited time only')
→ L1: Conversion (score=0.299)
→ L2: Risk Reversal (score=0.298)
→ L3: [Free Trial/Sample (0.289), Money-Back Guarantee (0.271), Exclusive Member Perk (0.268)]
```

### CP5 → CP7: Policy Check + Operator Execution
```python
# CP5: Policy Engine evaluates action
pe = PolicyEngine()  # 5 rules loaded
safe_action = ActionRequest(budget 100→110, 10%)
pe.evaluate(safe_action) → approved=True

risky_action = ActionRequest(budget 100→150, 50%)
pe.evaluate(risky_action) → approved=False
  → BudgetDeltaRule: "Budget change 50.0% exceeds max allowed 20%."

# CP7: Operator executes in DRY_RUN
op = Operator(mode='DRY_RUN')
pack = DecisionPack(action=safe_action)
op.execute(pack) → state=executed (dry_run)

# CP7: Kill switch blocks all execution
op.kill_switch = True
op.execute(pack) → raises KillSwitchActive (hard block)
```

### CP4: Saturation Analysis (API Route)
```
GET /api/saturation/analyze
→ 5 creatives analyzed from demo CSV (45 rows)
  Results Proof - V1: 0.29 (fresh)
  Community Pride - V2: 0.21 (fresh)
  Transformation Story - V1: 0.15 (fresh)
  Beginner Friendly - V3: 0.13 (fresh)
  Time Efficient - V2: 0.12 (fresh)
```

---

## Trace D: Cross-System Data Flow Verification

### Dashboard ← Decisions ← Audit
```
1. Decision created → Dashboard "Pending Approvals" increments
2. Decision executed → Dashboard "Executed Today" increments
3. Decision executed → Audit entry created with trace_id
4. Decision blocked → Dashboard "Blocked by Policy" increments
5. Dry run executed → Dashboard "Dry Runs Today" increments + Audit status=dry_run
```

**Verified state after full trace session:**
```
Dashboard KPIs:
  Pending Approvals: 0 (all processed)
  Executed Today: 4 (3 previous + 1 from Trace A)
  Blocked by Policy: 2 (1 from previous + 1 from Trace B)
  Dry Runs Today: 4 (all were dry_run)

Audit Log:
  4 entries (all dry_run)
  Each with unique trace_id linking back to decision
```

---

## Break Points Identified

| Break Point | CP | Trigger | Impact | Severity |
|------------|-----|---------|--------|----------|
| Anthropic API key missing | CP1,3,6 | No `ANTHROPIC_API_KEY` in env | BrandMap/Score/Generate fail | HIGH |
| ChromaDB disk full | CP0,1,2 | `./chroma_data/` volume exhausted | Vector ops fail | HIGH |
| CSV file missing | CP4 | `data/demo_ads_performance.csv` deleted | Saturation returns empty | MEDIUM |
| Demo brand file missing | CP1 | `data/demo_brand.txt` deleted | Opportunities returns empty | MEDIUM |
| Kill switch lost on restart | CP7 | Server process restart | Kill switch resets to False | MEDIUM |
| Cooldown locks lost on restart | CP5 | Server process restart | Cooldown enforcement resets | MEDIUM |
| JWT_SECRET not set | Auth | Missing env var | All auth endpoints 500 | CRITICAL |
| META_TOKEN_ENCRYPTION_KEY wrong | Meta OAuth | Wrong/missing key | Token decrypt fails | HIGH |
| SQLite database locked | All | Concurrent write contention | 500 errors | MEDIUM |

---

## Pipeline Latency Profile (Observed)

| Operation | Latency | Notes |
|-----------|---------|-------|
| Login | ~100ms | JWT generation |
| Create Decision | ~50ms | DB insert |
| Validate Decision | ~500ms | Policy engine evaluation |
| Request Approval | ~30ms | State transition |
| Approve | ~30ms | State transition |
| Execute (dry_run) | ~250ms | DRY_RUN simulation + audit log |
| Dashboard KPIs | ~100ms | 4 DB aggregate queries |
| Saturation Analyze | ~200ms | CSV load + pandas processing |
| Opportunities List | ~500ms | BrandMap text processing |
| Full lifecycle (5 steps) | ~1.3s | End-to-end from create to execute |
