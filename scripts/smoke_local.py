"""
Sprint 12 — BLOQUE B: Localhost smoke test runner.
Exercises every critical API path end-to-end against a running server.
Usage: python scripts/smoke_local.py
"""
import sys
import time
import requests

BASE_URL = "http://localhost:8000/api"
TEST_EMAIL = "admin@example.com"
TEST_PASSWORD = "admin123"

results = []
token = None


def step(name, fn):
    """Run a test step and track pass/fail."""
    t0 = time.time()
    try:
        fn()
        elapsed = (time.time() - t0) * 1000
        results.append(("PASS", name, f"{elapsed:.0f}ms"))
        print(f"  [PASS] {name} ({elapsed:.0f}ms)")
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        results.append(("FAIL", name, str(e)[:120]))
        print(f"  [FAIL] {name} ({elapsed:.0f}ms) — {e}")


def auth_headers():
    return {"Authorization": f"Bearer {token}"}


# ── Step 1: Health ────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    assert r.status_code == 200, f"Got {r.status_code}"
    data = r.json()
    assert data.get("status") == "healthy", f"Unexpected: {data}"


# ── Step 2: Login ─────────────────────────────────────────────────────────

def test_login():
    global token
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=10,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("access_token")
    assert token, "No access_token in response"


# ── Step 3: Meta Verify ──────────────────────────────────────────────────

def test_meta_verify():
    r = requests.get(f"{BASE_URL}/meta/verify", headers=auth_headers(), timeout=10)
    assert r.status_code == 200, f"Got {r.status_code}"
    data = r.json()
    assert "connected" in data, f"Missing 'connected' field: {data}"
    assert "api_reachable" in data, f"Missing 'api_reachable' field: {data}"


# ── Step 4: Env Parity ───────────────────────────────────────────────────

def test_env_parity():
    r = requests.get(f"{BASE_URL}/system/env/parity", headers=auth_headers(), timeout=10)
    assert r.status_code == 200, f"Got {r.status_code}"
    data = r.json()
    assert "db_ok" in data, f"Missing 'db_ok' field: {data}"
    assert data["db_ok"] is True, "Database not OK"


# ── Step 5: Creatives Generate → Poll → Terminal ─────────────────────────

def test_creatives_generate():
    r = requests.post(
        f"{BASE_URL}/creatives/generate",
        json={"angle_id": "smoke_test", "brand_map_id": "demo", "n_variants": 1},
        headers=auth_headers(),
        timeout=10,
    )
    assert r.status_code == 202, f"Got {r.status_code}: {r.text[:200]}"
    job_id = r.json().get("job_id")
    assert job_id, "No job_id in 202 response"

    # Poll until terminal
    for _ in range(90):  # max 180s
        time.sleep(2)
        jr = requests.get(
            f"{BASE_URL}/ops/jobs/{job_id}",
            headers=auth_headers(),
            timeout=5,
        )
        if jr.status_code != 200:
            continue
        status = jr.json().get("status")
        if status in ("succeeded", "failed", "dead"):
            error_msg = jr.json().get("last_error_message", "")
            assert status == "succeeded", (
                f"Job {status}: {error_msg[:200]}"
            )
            return
    raise TimeoutError("Creative generation did not complete in 180s")


# ── Step 6: Opportunities Analyze → Poll → Terminal ──────────────────────

def test_opportunities_analyze():
    r = requests.post(
        f"{BASE_URL}/opportunities/analyze",
        headers=auth_headers(),
        timeout=10,
    )
    assert r.status_code == 202, f"Got {r.status_code}: {r.text[:200]}"
    job_id = r.json().get("job_id")
    assert job_id, "No job_id in 202 response"

    for _ in range(90):
        time.sleep(2)
        jr = requests.get(
            f"{BASE_URL}/ops/jobs/{job_id}",
            headers=auth_headers(),
            timeout=5,
        )
        if jr.status_code != 200:
            continue
        status = jr.json().get("status")
        if status in ("succeeded", "failed", "dead"):
            error_msg = jr.json().get("last_error_message", "")
            assert status == "succeeded", (
                f"Job {status}: {error_msg[:200]}"
            )
            return
    raise TimeoutError("Opportunities analysis did not complete in 180s")


# ── Step 7: Report Endpoint Shape ────────────────────────────────────────

def test_report_endpoint():
    r = requests.get(
        f"{BASE_URL}/reports/decisions/00000000-0000-0000-0000-000000000001/docx",
        headers=auth_headers(),
        timeout=10,
    )
    # 404 = decision not found (correct behavior), 200 = valid download
    assert r.status_code in (200, 404), f"Unexpected: {r.status_code}"


# ── Main ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Meta Ops Agent — Localhost Smoke Test")
    print("=" * 60)
    print()

    step("1. GET /api/health", test_health)
    step("2. POST /api/auth/login", test_login)

    if token:
        step("3. GET /api/meta/verify", test_meta_verify)
        step("4. GET /api/system/env/parity", test_env_parity)
        step("5. POST /api/creatives/generate → poll", test_creatives_generate)
        step("6. POST /api/opportunities/analyze → poll", test_opportunities_analyze)
        step("7. GET /api/reports/.../docx (shape)", test_report_endpoint)
    else:
        print("  [SKIP] Steps 3-7 (no auth token)")

    print()
    print("=" * 60)
    passed = sum(1 for r in results if r[0] == "PASS")
    failed = sum(1 for r in results if r[0] == "FAIL")
    print(f"  Results: {passed} passed, {failed} failed, {len(results)} total")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
