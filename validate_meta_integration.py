"""
Meta Integration Validator — End-to-End Production Readiness Check
Run: python validate_meta_integration.py

Checks:
  1. .env configuration (META_APP_ID, META_APP_SECRET, encryption key)
  2. Token encryption round-trip (AES-256-GCM)
  3. Meta Graph API connectivity (GET /me with app token)
  4. OAuth redirect URI consistency
  5. Token debug introspection (if a live token exists in DB)
  6. Ad account access verification
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

# Setup path so imports work
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# Force .env loading
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def check_env_config():
    """Check that all required Meta env vars are set with real values."""
    print_header("1. Environment Configuration")

    from backend.src.config import settings

    checks = {
        "META_APP_ID": settings.META_APP_ID,
        "META_APP_SECRET": settings.META_APP_SECRET,
        "META_TOKEN_ENCRYPTION_KEY": settings.META_TOKEN_ENCRYPTION_KEY,
        "META_OAUTH_REDIRECT_URI": settings.META_OAUTH_REDIRECT_URI,
        "META_OAUTH_SCOPES": settings.META_OAUTH_SCOPES,
        "JWT_SECRET": settings.JWT_SECRET,
        "FRONTEND_URL": settings.FRONTEND_URL,
    }

    all_ok = True
    for key, value in checks.items():
        if not value:
            print(f"  {FAIL} {key} is empty/missing")
            all_ok = False
        elif value.startswith("REPLACE_") or value.startswith("CHANGE_ME") or value == "your_app_id":
            print(f"  {FAIL} {key} still has placeholder value")
            all_ok = False
        elif key == "JWT_SECRET" and value == "dev-secret-change-in-production":
            print(f"  {WARN} {key} is using dev default — change for production")
        else:
            # Mask secrets in output
            if "SECRET" in key or "KEY" in key:
                display = value[:6] + "..." + value[-4:]
            elif "APP_ID" in key:
                display = value
            else:
                display = value
            print(f"  {PASS} {key} = {display}")

    # Validate encryption key is 32 bytes
    try:
        key_bytes = base64.urlsafe_b64decode(settings.META_TOKEN_ENCRYPTION_KEY or "")
        if len(key_bytes) == 32:
            print(f"  {PASS} META_TOKEN_ENCRYPTION_KEY decodes to 32 bytes (AES-256)")
        else:
            print(f"  {FAIL} META_TOKEN_ENCRYPTION_KEY decodes to {len(key_bytes)} bytes (need 32)")
            all_ok = False
    except Exception as e:
        print(f"  {FAIL} META_TOKEN_ENCRYPTION_KEY is not valid base64: {e}")
        all_ok = False

    return all_ok


def check_token_encryption():
    """Test AES-256-GCM encrypt/decrypt round-trip."""
    print_header("2. Token Encryption (AES-256-GCM)")

    try:
        from backend.src.utils.token_crypto import encrypt_token, decrypt_token

        test_token = "EAABsbCS1234FAKE_TOKEN_FOR_ROUNDTRIP_TEST"
        encrypted = encrypt_token(test_token)
        decrypted = decrypt_token(encrypted)

        if decrypted == test_token:
            print(f"  {PASS} Encrypt/decrypt round-trip successful")
            print(f"  {INFO} Encrypted length: {len(encrypted)} chars")
            return True
        else:
            print(f"  {FAIL} Decrypted value does not match original")
            return False
    except Exception as e:
        print(f"  {FAIL} Encryption test failed: {e}")
        return False


async def check_meta_api_connectivity():
    """Test connectivity to Meta Graph API using app access token."""
    print_header("3. Meta Graph API Connectivity")

    from backend.src.config import settings

    app_id = settings.META_APP_ID
    app_secret = settings.META_APP_SECRET

    if not app_id or not app_secret or app_id.startswith("REPLACE_"):
        print(f"  {FAIL} Cannot test — META_APP_ID or META_APP_SECRET not configured")
        return False

    import httpx

    # Test with app access token (app_id|app_secret)
    app_token = f"{app_id}|{app_secret}"

    try:
        async with httpx.AsyncClient() as client:
            # Test basic API access
            resp = await client.get(
                "https://graph.facebook.com/v21.0/debug_token",
                params={
                    "input_token": app_token,
                    "access_token": app_token,
                },
                timeout=15.0,
            )

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                print(f"  {PASS} Meta Graph API is reachable")
                print(f"  {PASS} App ID confirmed: {data.get('app_id', 'N/A')}")
                print(f"  {INFO} Token type: {data.get('type', 'N/A')}")
                return True
            else:
                error = resp.json().get("error", {})
                print(f"  {FAIL} Meta API returned {resp.status_code}: {error.get('message', resp.text[:200])}")
                if error.get("code") == 190:
                    print(f"  {INFO} This usually means META_APP_ID or META_APP_SECRET is wrong")
                return False
    except httpx.ConnectError:
        print(f"  {FAIL} Cannot connect to graph.facebook.com — check internet connection")
        return False
    except Exception as e:
        print(f"  {FAIL} Unexpected error: {e}")
        return False


def check_oauth_redirect_uri():
    """Validate OAuth redirect URI configuration."""
    print_header("4. OAuth Redirect URI")

    from backend.src.config import settings

    redirect_uri = settings.META_OAUTH_REDIRECT_URI
    frontend_url = settings.FRONTEND_URL

    print(f"  {INFO} Redirect URI: {redirect_uri}")
    print(f"  {INFO} Frontend URL: {frontend_url}")

    if "/api/meta/oauth/callback" not in redirect_uri:
        print(f"  {FAIL} Redirect URI must end with /api/meta/oauth/callback")
        return False

    print(f"  {PASS} Redirect URI format is correct")
    print(f"  {WARN} Make sure this URI is added to your Meta App:")
    print(f"         developers.facebook.com -> Your App -> Facebook Login -> Settings")
    print(f"         -> Valid OAuth Redirect URIs -> Add: {redirect_uri}")
    return True


async def check_live_token():
    """If there's a live token in the DB, validate it against Meta."""
    print_header("5. Live Token Validation (if available)")

    try:
        from backend.src.database.session import SessionLocal
        from backend.src.database.models import MetaConnection, ConnectionStatus, AdAccount
        from backend.src.utils.token_crypto import decrypt_token
        from backend.src.config import settings

        db = SessionLocal()
        try:
            conn = (
                db.query(MetaConnection)
                .filter(MetaConnection.status == ConnectionStatus.ACTIVE)
                .first()
            )

            if not conn:
                print(f"  {INFO} No active Meta connection found in database")
                print(f"  {INFO} This is expected if you haven't completed OAuth yet")
                return True

            print(f"  {INFO} Found connection: {conn.id}")
            print(f"  {INFO} Meta user: {conn.meta_user_name} (ID: {conn.meta_user_id})")
            print(f"  {INFO} Scopes: {conn.scopes}")
            print(f"  {INFO} Token expires: {conn.token_expires_at}")

            # Decrypt token
            access_token = decrypt_token(conn.access_token_encrypted)
            print(f"  {PASS} Token decrypted successfully")

            # Validate against Meta
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://graph.facebook.com/v21.0/me",
                    params={"access_token": access_token, "fields": "id,name"},
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    user_data = resp.json()
                    print(f"  {PASS} Token is VALID on Meta's servers")
                    print(f"  {PASS} Authenticated as: {user_data.get('name')} (ID: {user_data.get('id')})")
                else:
                    error = resp.json().get("error", {})
                    print(f"  {FAIL} Token rejected by Meta: {error.get('message', 'Unknown')}")
                    print(f"  {INFO} Error code: {error.get('code')}, subcode: {error.get('error_subcode')}")
                    return False

                # Debug token for full permission info
                app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
                resp2 = await client.get(
                    "https://graph.facebook.com/v21.0/debug_token",
                    params={"input_token": access_token, "access_token": app_token},
                    timeout=10.0,
                )

                if resp2.status_code == 200:
                    debug_data = resp2.json().get("data", {})
                    print(f"  {PASS} debug_token: is_valid={debug_data.get('is_valid')}")
                    print(f"  {INFO} Scopes granted: {debug_data.get('scopes', [])}")

                    granted = set(debug_data.get("scopes", []))
                    required = set(s.strip() for s in settings.META_OAUTH_SCOPES.split(","))
                    if required.issubset(granted):
                        print(f"  {PASS} All required scopes ({required}) are granted")
                    else:
                        missing = required - granted
                        print(f"  {FAIL} Missing required scopes: {missing}")
                        return False

                # Check ad account access
                resp3 = await client.get(
                    "https://graph.facebook.com/v21.0/me/adaccounts",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,currency,account_status",
                        "limit": 10,
                    },
                    timeout=15.0,
                )

                if resp3.status_code == 200:
                    accounts = resp3.json().get("data", [])
                    print(f"  {PASS} Ad account access confirmed: {len(accounts)} account(s) found")
                    for acct in accounts[:5]:
                        status = "ACTIVE" if acct.get("account_status") == 1 else f"status={acct.get('account_status')}"
                        print(f"       - {acct['id']}: {acct.get('name', 'N/A')} ({acct.get('currency', '?')}) [{status}]")
                    if len(accounts) > 5:
                        print(f"       ... and {len(accounts) - 5} more")
                else:
                    error = resp3.json().get("error", {})
                    print(f"  {FAIL} Cannot access ad accounts: {error.get('message', 'Unknown')}")
                    return False

            return True
        finally:
            db.close()
    except Exception as e:
        print(f"  {FAIL} Error during live validation: {e}")
        return False


async def main():
    print("\n" + "=" * 60)
    print("  META INTEGRATION VALIDATOR — Production Readiness")
    print("=" * 60)

    results = {}

    results["env"] = check_env_config()
    results["encryption"] = check_token_encryption()
    results["api"] = await check_meta_api_connectivity()
    results["redirect"] = check_oauth_redirect_uri()
    results["live_token"] = await check_live_token()

    # Summary
    print_header("SUMMARY")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    for name, ok in results.items():
        status = PASS if ok else FAIL
        print(f"  {status} {name}")

    print(f"\n  Result: {passed}/{total} checks passed")

    if failed > 0:
        print(f"\n  {FAIL} {failed} check(s) failed. Review the output above.")
        print(f"  {INFO} Most common fix: set real META_APP_ID and META_APP_SECRET in .env")
    else:
        print(f"\n  {PASS} All checks passed! Integration is production-ready.")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
