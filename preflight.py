"""Pre-flight check before launching flywheel."""
import sqlite3, json, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect("meta_ops.db", timeout=10)
c = conn.cursor()

print("=== PRE-FLIGHT CHECK ===\n")

# 1. Stuck jobs
stuck = c.execute("SELECT COUNT(*) FROM job_runs WHERE status IN ('RUNNING','QUEUED')").fetchone()[0]
print(f"  Stuck jobs:          {stuck} {'(CLEAR)' if stuck == 0 else '!! WARNING !!'}")

# 2. Running flywheel runs
running = c.execute("SELECT COUNT(*) FROM flywheel_runs WHERE status='running'").fetchone()[0]
print(f"  Running runs:        {running} {'(CLEAR)' if running == 0 else '!! WARNING !!'}")

# 3. Latest run
r = c.execute("SELECT id, status FROM flywheel_runs ORDER BY created_at DESC LIMIT 1").fetchone()
if r:
    print(f"  Latest run:          {r[0][:8]} -> {r[1]}")

# 4. Content packs
print("\n  Content packs:")
packs = c.execute("SELECT id, status, goal, channels_json FROM content_packs ORDER BY created_at DESC LIMIT 3").fetchall()
for p in packs:
    vcount = c.execute("SELECT COUNT(*) FROM content_variants WHERE content_pack_id=?", (p[0],)).fetchone()[0]
    try:
        ch_data = json.loads(p[3]) if p[3] else []
        ch_count = len(ch_data) if isinstance(ch_data, list) else 0
    except:
        ch_count = 0
    print(f"    {p[0][:8]} | {p[1]:10s} | goal={str(p[2]):10s} | {ch_count} ch | {vcount} variants")

conn.close()

# 5. Code fixes
print("\n  Code fixes:")
checks = []

with open("backend/src/jobs/task_runner.py") as f:
    txt = f.read()
    checks.append(("Job timeout 900s", '"content_studio_generate": 900' in txt))

with open("backend/src/services/flywheel_service.py") as f:
    txt = f.read()
    checks.append(("Poll timeout 900s", "_POLL_TIMEOUT = 900" in txt))
    checks.append(("Goal diversity", "opp_text = opp_strategy" in txt))
    checks.append(("Multi-channel defaults (6ch)", "ig_carousel" in txt and "fb_ad_copy" in txt))
    checks.append(("Skip broken packs", "variant_count > 0" in txt))
    checks.append(("Clean broken packs", "FLYWHEEL_CLEANED_BROKEN_PACKS" in txt))

with open("backend/src/api/flywheel.py") as f:
    txt = f.read()
    checks.append(("Config null filter", "if v is not None" in txt))
    checks.append(("PDF channel-aware render", "CHANNEL_DISPLAY_FIELDS" in txt))

with open("frontend/src/services/api.ts") as f:
    txt = f.read()
    checks.append(("Frontend listPacks API", "listPacks" in txt))

with open("frontend/src/pages/ContentStudio.tsx") as f:
    txt = f.read()
    checks.append(("Pack history UI", "packHistory" in txt and "handleLoadPack" in txt))

all_ok = True
for name, ok in checks:
    status = "OK" if ok else "MISSING"
    if not ok:
        all_ok = False
    print(f"    {name:30s}  [{status}]")

# 6. Server check
print("\n  Servers:")
import urllib.request
try:
    resp = urllib.request.urlopen("http://localhost:8000/api/health", timeout=5)
    data = json.loads(resp.read())
    print(f"    Backend (8000):   {data['status']} | DB={data['dependencies']['database']['status']}")
except Exception as e:
    print(f"    Backend (8000):   DOWN ({e})")
    all_ok = False

try:
    resp = urllib.request.urlopen("http://localhost:5178/", timeout=5)
    print(f"    Frontend (5178):  UP (status {resp.status})")
except Exception as e:
    print(f"    Frontend (5178):  DOWN ({e})")

print(f"\n{'  ALL SYSTEMS GO - Launch when ready!' if all_ok else '  ISSUES FOUND - check above'}")
