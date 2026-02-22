# RUNBOOK LOCAL — SAFE MODE (FASE 5.3 + 5.4)

**Objetivo**: Levantar el sistema localmente, bootstrap desde el browser, y operar en SAFE MODE (DRY_RUN).

---

## 1. Prerequisitos

```bash
# Python 3.11+
python --version

# Node.js 18+
node --version
```

---

## 2. Setup Backend

```bash
cd meta-ops-agent

# Crear .env (si no existe)
cp .env.template .env
# Editar .env:
#   DATABASE_URL=sqlite:///./meta_ops_agent.db
#   JWT_SECRET=<cualquier string largo>
#   META_TOKEN_ENCRYPTION_KEY=<32 bytes base64, ver .env.template>

# Instalar dependencias Python
pip install -r requirements.txt

# Iniciar backend (crea DB automaticamente en startup)
PYTHONPATH=. python -m uvicorn backend.main:app --reload --port 8000
```

**Verificacion**: `curl http://localhost:8000/api/health` devuelve `status: healthy` o `degraded`.

---

## 3. Setup Frontend

```bash
cd frontend

# Instalar dependencias
npm install

# Iniciar dev server
npm run dev
```

**Verificacion**: Abrir http://localhost:5173 — redirige a `/login`.

---

## 4. Bootstrap (primera vez, DB vacia)

Con DB vacia, la pantalla de login detecta automaticamente que no hay organizaciones y muestra el formulario de **bootstrap**.

### Via Browser (recomendado)
1. Abrir http://localhost:5173/login
2. Se muestra el formulario "Set up your organization"
3. Llenar:
   - Organization Name: `My Company`
   - Admin Name: `Admin`
   - Admin Email: `admin@example.com`
   - Password: `admin123`
4. Click "Create Organization & Admin"
5. Redirige automaticamente al Dashboard

### Via curl (alternativa)
```bash
# Check si necesita bootstrap
curl -s http://localhost:8000/api/auth/bootstrap-check | python -m json.tool
# Esperado: {"needs_bootstrap": true, "org_count": 0}

# Bootstrap: crea org + admin + devuelve JWT
curl -s -X POST http://localhost:8000/api/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "My Company",
    "admin_email": "admin@example.com",
    "admin_password": "admin123",
    "admin_name": "Admin"
  }' | python -m json.tool

# Guardar el access_token del response
TOKEN="<access_token del response>"
```

---

## 5. Login (subsiguientes sesiones)

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123"}' | python -m json.tool
```

O simplemente abrir http://localhost:5173/login e ingresar credenciales.

---

## 6. Verificacion de flujos en UI

### 6a. Dashboard
- Navegar a Dashboard
- Verificar KPIs: `Pending: 0, Executed: 0, Blocked: 0, Dry Runs: 0`
- Los valores son reales (DB queries, no mocks)

### 6b. Control Panel — Crear Decision
1. Ir a Control Panel
2. **Operator Armed** debe estar en OFF (safe mode)
3. Si hay ad accounts conectados (via Meta OAuth o seed), seleccionar uno
4. Llenar formulario:
   - Entity ID: `test_adset_001`
   - Entity Name: `Test Budget Change`
   - Current Budget: `100`
   - New Budget: `110`
   - Rationale: `Testing safe mode workflow`
5. Click "Create Draft"
6. Redirige a Decision Queue

### 6c. Decision Queue — Ciclo completo
1. Ver decision en estado `draft`
2. Click **Validate** → estado cambia a `ready` (10% budget change, under 20% threshold)
3. Click **Request Approval** → estado cambia a `pending_approval`
4. Click **Approve** → estado cambia a `approved`
5. Click **Dry Run First** → estado cambia a `executed` (DRY_RUN, no Meta API calls)
6. Verificar en Dashboard: `Executed: 1, Dry Runs: 1`

### 6d. Decision Queue — Policy Block
1. Crear otra decision con budget `100 → 150` (50% change)
2. Click **Validate**
3. Estado cambia a `blocked` con mensaje: "Budget change 50.0% exceeds max allowed 20%"
4. No se puede avanzar (terminal state)

### 6e. Audit Log
- Navegar a Audit Log
- Verificar que las ejecuciones aparecen con trace_id
- Click "View Details" para expandir cambios JSON

### 6f. Opportunities
- Navegar a Opportunities
- Muestra gaps estrategicos del demo brand file
- Click "Create Campaign" navega al Control Panel

### 6g. Saturation
- Navegar a Saturation
- Muestra analisis de los 5 angulos del demo CSV
- Scores y status son reales (del SaturationEngine)

### 6h. Policies
- Navegar a Policies
- 6 reglas reales del DEFAULT_RULES registry

---

## 7. Seed con datos demo (alternativa al bootstrap)

```bash
cd meta-ops-agent
PYTHONPATH=. python backend/seed_demo.py
# Crea: org "Audit Corp", user "admin@audit.com" (password: "demo123"), ad account, meta connection
```

---

## 8. Tests automatizados

```bash
cd meta-ops-agent

# Todos los tests (131 tests)
python -m pytest tests/ -v --ignore=tests/test_integration_pipeline.py

# Solo auth + RBAC (28 tests)
python -m pytest tests/test_auth_rbac.py -v

# Solo Meta OAuth (18 tests)
python -m pytest tests/test_meta_oauth.py -v

# Frontend type check + build
cd frontend && npm run build
```

**Esperado**: 131 tests PASSED, frontend build SUCCESS.

---

## 9. Checklist de verificacion SAFE MODE

| Check | Como verificar | Esperado |
|-------|---------------|----------|
| Bootstrap desde UI | DB vacia → /login → formulario bootstrap | Crea org+admin, redirige a Dashboard |
| Login persiste | Refresh pagina | Token en localStorage, no pide login |
| Dashboard KPIs reales | GET /api/dashboard/kpis | Valores de DB, no mocks |
| Create decision desde UI | Control Panel → formulario | user_id viene del auth context |
| Validate + policy check | Decision Queue → Validate | BudgetDeltaRule evalua correctamente |
| Dry run ejecuta | Decision Queue → Dry Run First | state=executed, audit entry creada |
| Policy block funciona | Budget change >20% → Validate | state=blocked (terminal) |
| Audit log con detalles | Audit Log → View Details | Expande JSON de cambios |
| Logout funciona | Sidebar → Sign Out | Limpia tokens, redirige a /login |
| Protected routes | Acceder /dashboard sin token | Redirige a /login |
| Token refresh | Access token expira (60min) | Auto-refresh transparente |

---

## Troubleshooting

| Problema | Solucion |
|----------|----------|
| `ModuleNotFoundError: backend.src...` | Ejecutar con `PYTHONPATH=.` desde la raiz |
| Port 8000 en uso | `--port 8001` y set `VITE_API_URL=http://localhost:8001/api` en `.env` del frontend |
| 401 en todos los endpoints | Verificar JWT_SECRET en `.env` del backend |
| Bootstrap disabled | Ya existe una org. Usar `/login` en vez de bootstrap |
| Frontend no conecta | Verificar CORS origins en `backend/main.py` incluyen tu port |
| Token refresh falla | Verificar que refresh_token no esta expirado (7 dias) |
