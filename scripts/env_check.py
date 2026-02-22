"""
Sprint 12 — BLOQUE A: Environment validation script.
Validates that all required services and configuration are present.
Usage: python scripts/env_check.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

REQUIRED_VARS = [
    "JWT_SECRET",
]

RECOMMENDED_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "META_APP_ID",
    "META_APP_SECRET",
]


def check_env_vars():
    """Check required and recommended env vars."""
    try:
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
    except ImportError:
        pass

    missing_required = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    missing_recommended = [v for v in RECOMMENDED_VARS if not os.environ.get(v)]

    print("--- Environment Variables ---")
    if missing_required:
        print(f"  [FAIL] Missing REQUIRED: {', '.join(missing_required)}")
    else:
        print("  [OK] All required vars present")

    if missing_recommended:
        print(f"  [WARN] Missing recommended: {', '.join(missing_recommended)}")
    else:
        print("  [OK] All recommended vars present")

    return len(missing_required) == 0


def check_redis():
    """Check Redis connectivity."""
    print("--- Redis ---")
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(url)
        r.ping()
        print("  [OK] Redis connected")
        return True
    except ImportError:
        print("  [WARN] redis package not installed")
        return False
    except Exception as e:
        print(f"  [WARN] Redis not reachable ({e})")
        return False


def check_db():
    """Check database connectivity."""
    print("--- Database ---")
    try:
        from sqlalchemy import text
        from backend.src.database.session import SessionLocal
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        print("  [OK] Database connected")
        return True
    except Exception as e:
        print(f"  [WARN] Database error: {e}")
        return False


def check_llm_keys():
    """Check LLM API keys."""
    print("--- LLM Keys ---")
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if has_anthropic or has_openai:
        providers = []
        if has_anthropic:
            providers.append("Anthropic")
        if has_openai:
            providers.append("OpenAI")
        print(f"  [OK] LLM providers: {', '.join(providers)}")
        return True
    else:
        print("  [FAIL] No LLM keys (need ANTHROPIC_API_KEY or OPENAI_API_KEY)")
        return False


def check_data_files():
    """Check required data files."""
    print("--- Data Files ---")
    brand_file = project_root / "data" / "demo_brand.txt"
    if brand_file.exists():
        print("  [OK] demo_brand.txt present")
        return True
    else:
        print("  [WARN] data/demo_brand.txt not found")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("  Meta Ops Agent — Environment Check")
    print("=" * 50)
    print()
    results = [
        check_env_vars(),
        check_redis(),
        check_db(),
        check_llm_keys(),
        check_data_files(),
    ]
    print()
    print("=" * 50)
    passed = sum(1 for r in results if r)
    total = len(results)
    if all(results):
        print(f"  ALL {total} CHECKS PASSED")
    else:
        print(f"  {passed}/{total} CHECKS PASSED")
    print("=" * 50)
    sys.exit(0 if all(results) else 1)
