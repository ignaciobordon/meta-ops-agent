# Meta Ops Agent — SaaS Platform

**Autonomous Meta Ads management with human-in-the-loop approval workflow.**

Multi-tenant platform that combines AI-powered decision engines (CP0-CP7) with a premium web UI for safe, auditable ad account management.

---

## Architecture

### Core System (CP0-CP7)
- **CP0**: Vector DB + Logging
- **CP1**: BrandMap Builder
- **CP2**: Angle Tagger
- **CP3**: Creative Scorer
- **CP4**: Saturation Engine
- **CP5**: Policy Engine (guardrails)
- **CP6**: Creative Factory (LLM script generation)
- **CP7**: Operator (execution layer)

### Product Layer (NEW)
- **Backend**: FastAPI + PostgreSQL + SQLAlchemy
- **Frontend**: React + TypeScript + Vite
- **Multi-tenant**: Organizations → Meta Connections → Ad Accounts
- **RBAC**: Viewer / Operator / Director / Admin
- **Workflow**: DRAFT → VALIDATE → APPROVE → EXECUTE

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- (Optional) Meta Ads account for live execution

### 1. Database Setup

Install and start PostgreSQL, then create the database:

```bash
# Create database
createdb meta_ops_agent

# Or via psql
psql -U postgres
CREATE DATABASE meta_ops_agent;
\q
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r ../requirements.txt

# Configure environment
cp ../.env.template .env
# Edit .env and set:
# - DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/meta_ops_agent
# - ANTHROPIC_API_KEY=your_key (for CP1, CP3, CP6)
# - META_ACCESS_TOKEN=your_token (optional, for live execution)

# Seed demo data
python seed_demo.py

# Start API server
python main.py
```

Backend will run on **http://localhost:8000**

API docs: **http://localhost:8000/docs**

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend will run on **http://localhost:5173**

---

## Usage

### Creating and Approving a Decision

1. **Navigate to Control Panel** (`/control-panel`)
2. **Create a draft**:
   - Select action type (e.g., "Budget Change")
   - Enter entity details (Adset ID, name)
   - Configure budget ($100 → $120)
   - Provide rationale
   - Click "Create Draft"

3. **Go to Decision Queue** (`/decisions`)
4. **Validate the draft**:
   - Click "Validate" on the draft card
   - Policy Engine checks (±20% budget delta, cooldown, learning phase)
   - If pass → state changes to READY

5. **Request Approval**:
   - Click "Request Approval"
   - State changes to PENDING_APPROVAL

6. **Approve** (Director+ role):
   - Click "Approve"
   - State changes to APPROVED

7. **Execute**:
   - **Dry Run First** (recommended): Simulates the API call
   - **Execute Live**: Requires "Operator Armed" toggle ON (header)
   - Meta API call is made (or simulated if DRY_RUN=True in MetaAPIClient)

### Operator Armed Toggle

- **Location**: Header, top-right
- **OFF (default)**: All executions are DRY_RUN
- **ON (Live Mode)**: Execute button performs real Meta API calls
- **Access**: Director+ only

---

## Key Features

### 1. Multi-Tenant Architecture
- Organizations own multiple Meta Connections
- Each connection exposes multiple Ad Accounts
- Full workspace switcher in UI

### 2. State Machine Workflow
```
DRAFT → VALIDATING → READY → PENDING_APPROVAL → APPROVED → EXECUTING → EXECUTED
                  ↓
               BLOCKED (policy violations)
```

### 3. Policy Guardrails (CP5)
- **BudgetDeltaRule**: ±20% max change
- **CooldownLockRule**: 24h lock after structural changes
- **LearningPhaseProtectionRule**: Blocks changes if CPA < 3x target
- **NoDirectEditActiveAdRule**: Always duplicate, never direct edit
- **ExcessiveFrequencyWarningRule**: Warns at frequency > 3.0

### 4. Audit Trail
- Every action logged with trace_id
- Before/after snapshots
- User attribution
- Export-ready

### 5. Mediterranean Deluxe Design
- Premium design system with Terracotta + Olive + Gold palette
- High whitespace, soft shadows, rounded corners
- Editorial typography (Newsreader + Inter)

---

## API Endpoints

### Organizations
- `GET /api/orgs` — List all organizations
- `POST /api/orgs` — Create organization
- `POST /api/orgs/{id}/operator-armed` — Toggle Operator Armed

### Decisions
- `GET /api/decisions` — List decisions (filterable by state)
- `POST /api/decisions` — Create draft
- `POST /api/decisions/{id}/validate` — Run policy validation
- `POST /api/decisions/{id}/request-approval` — Submit for approval
- `POST /api/decisions/{id}/approve` — Approve (Director+)
- `POST /api/decisions/{id}/reject` — Reject
- `POST /api/decisions/{id}/execute` — Execute (dry_run or live)

---

## Environment Variables

### Required
```env
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/meta_ops_agent

# LLM (for CP1, CP3, CP6)
ANTHROPIC_API_KEY=sk-ant-...
```

### Optional (for live Meta API execution)
```env
META_ACCESS_TOKEN=EAAxxxxx
META_AD_ACCOUNT_ID=act_123456789
```

### Configuration
```env
# Execution mode
DRY_RUN=true  # Set to false for live Meta API calls

# LLM provider
LLM_PROVIDER=anthropic  # or "openai" or "ollama"
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
```

---

## Development

### Run Tests (Core CP0-CP7)
```bash
# All tests
pytest -v

# Specific checkpoint
pytest tests/cp7_test_operator.py -v
```

### Database Migrations (Future)
```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

### Frontend Build
```bash
cd frontend
npm run build
# Output: frontend/dist/
```

---

## Production Deployment

### Backend
1. Set environment variables in production
2. Run migrations: `alembic upgrade head`
3. Start with Gunicorn:
   ```bash
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app
   ```

### Frontend
1. Build: `npm run build`
2. Serve `dist/` with Nginx or Vercel

### Database
- Use managed PostgreSQL (AWS RDS, Supabase, etc.)
- Enable SSL connections
- Regular backups

### Secrets
- Store tokens in AWS Secrets Manager or HashiCorp Vault
- Encrypt `META_ACCESS_TOKEN` at rest (AES-256)
- Rotate credentials every 90 days

---

## Security Notes

### Hard Rules (Non-Negotiable)
1. **Human-in-the-loop**: No auto-execution without approval
2. **Zero surprise**: Always show before/after diffs
3. **Full audit**: Every action logged with trace_id
4. **Guardrails first**: Policy Engine validates before Operator executes
5. **No irreversible**: Rollback support for budget/status changes

### Permissions
- **Viewer**: Read-only access
- **Operator**: Create drafts, validate
- **Director**: Approve, execute, toggle Operator Armed
- **Admin**: Manage users, policies, connections

### Operator Armed Toggle
- Workspace-level setting
- Director+ only
- Session-scoped (resets on logout)
- Visual warning when ON

---

## Roadmap

### Phase 2 (Post-MVP)
- [ ] OAuth integration with Meta
- [ ] Email/Slack notifications for approvals
- [ ] Saturation heatmap visualization
- [ ] Creative Factory UI (generate scripts from BrandMap)
- [ ] Policy editor for Directors
- [ ] Multi-approval workflow (require 2+ approvers)
- [ ] Rollback for all action types
- [ ] Export audit logs to CSV

### Phase 3 (Scale)
- [ ] Billing & usage limits
- [ ] Team collaboration features
- [ ] API rate limiting per org
- [ ] Webhooks for integrations
- [ ] Mobile-responsive UI

---

## Support

For issues or questions:
- Check API docs: http://localhost:8000/docs
- Review state machine transitions in PHASE UX-0 spec
- Consult CP0-CP7 implementation plans

---

## License

Proprietary - All rights reserved.

Built with ❤️ by Antigravity Systems Architecture.
