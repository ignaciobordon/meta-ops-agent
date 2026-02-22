# Runbook: Meta OAuth + Multi-Account (FASE 5.4)

## Prerequisites

### 1. Meta App Setup

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new App (type: **Business**)
3. Add the **Facebook Login** product
4. In Facebook Login → Settings:
   - Valid OAuth Redirect URIs: `http://localhost:8000/api/meta/oauth/callback`
   - For production: `https://yourdomain.com/api/meta/oauth/callback`
5. In App → Settings → Basic:
   - Copy **App ID** → `META_APP_ID`
   - Copy **App Secret** → `META_APP_SECRET`
6. In App → Settings → Advanced:
   - App Mode: **Development** (for testing with test users)
   - For production: Submit for App Review with `ads_read` permission

### 2. Environment Variables

Add to your `.env` file:

```bash
# Meta OAuth (FASE 5.4)
META_APP_ID=your_meta_app_id
META_APP_SECRET=your_meta_app_secret
META_OAUTH_REDIRECT_URI=http://localhost:8000/api/meta/oauth/callback

# Generate a 32-byte encryption key:
#   python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
META_TOKEN_ENCRYPTION_KEY=CHANGE_ME_GENERATE_A_32_BYTE_KEY
```

**Important**: `META_TOKEN_ENCRYPTION_KEY` is separate from `JWT_SECRET`. It encrypts Meta access tokens at rest using AES-256-GCM.

### 3. Install Dependencies

```bash
pip install cryptography>=42.0.0
```

---

## OAuth Flow Walkthrough

### Step 1: Admin Initiates Connection

```bash
# Admin gets the authorization URL
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/meta/oauth/start
```

Response:
```json
{
  "authorization_url": "https://www.facebook.com/v19.0/dialog/oauth?client_id=...&redirect_uri=...&state=...&scope=ads_read",
  "message": "Redirect user to this URL to begin Meta OAuth"
}
```

The frontend redirects the user's browser to this URL.

### Step 2: User Authorizes on Meta

- User sees Meta's OAuth consent screen
- Grants `ads_read` permission
- Meta redirects back to `/api/meta/oauth/callback?code=...&state=...`

### Step 3: Callback Processes Token Exchange

The callback endpoint (no auth required — it's Meta's redirect):
1. Validates the CSRF state token (5-minute TTL)
2. Exchanges the authorization code for a short-lived token
3. Exchanges the short-lived token for a long-lived token (~60 days)
4. Encrypts the long-lived token with AES-256-GCM
5. Fetches `/me` for Meta user info
6. Fetches `/me/adaccounts` to sync ad accounts
7. Persists MetaConnection + AdAccount records
8. Redirects to frontend: `http://localhost:5173/control-panel?meta_connected=true`

### Step 4: Select Active Ad Account

```bash
# List all ad accounts for the org
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/meta/adaccounts

# Select one as active
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ad_account_id": "uuid-of-account"}' \
  http://localhost:8000/api/meta/adaccounts/select

# Verify active account
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/meta/adaccounts/active
```

---

## Endpoint Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/meta/oauth/start` | Admin (CONNECT_META) | Returns Meta authorization URL |
| GET | `/api/meta/oauth/callback` | None (Meta redirect) | Exchanges code for tokens, redirects to frontend |
| GET | `/api/meta/adaccounts` | Any authenticated | Lists org's ad accounts |
| POST | `/api/meta/adaccounts/select` | Any authenticated | Sets active ad account |
| GET | `/api/meta/adaccounts/active` | Any authenticated | Gets current active account |

---

## Database Models

### MetaConnection
| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `org_id` | UUID FK | Organization owner |
| `connected_by_user_id` | UUID FK (nullable) | User who initiated OAuth |
| `access_token_encrypted` | Text | AES-256-GCM encrypted token |
| `token_expires_at` | DateTime | Token expiration (~60 days) |
| `meta_user_id` | String(100) | Meta user ID from `/me` |
| `meta_user_name` | String(255) | Meta user name from `/me` |
| `status` | Enum | `active`, `expired`, `revoked` |
| `connected_at` | DateTime | When OAuth completed |

### AdAccount
| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `connection_id` | UUID FK | Parent MetaConnection |
| `meta_ad_account_id` | String | Meta's `act_XXXXX` ID |
| `name` | String | Account display name |
| `currency` | String | Account currency (e.g., USD) |
| `spend_cap` | Float (nullable) | Spending cap if set |
| `meta_metadata` | JSON (nullable) | Additional Meta fields |
| `synced_at` | DateTime | Last sync timestamp |

### Organization (new column)
| Column | Type | Description |
|--------|------|-------------|
| `active_ad_account_id` | UUID FK (nullable) | Currently selected ad account |

---

## Security Notes

1. **Token encryption**: Meta access tokens are encrypted at rest with AES-256-GCM. The encryption key (`META_TOKEN_ENCRYPTION_KEY`) is independent from `JWT_SECRET`.
2. **CSRF protection**: OAuth state tokens are stored in-memory with a 5-minute TTL. Each state is consumed on use (one-time).
3. **Scope**: Only `ads_read` is requested. No write permissions.
4. **RBAC**: Only admins can initiate OAuth. Any authenticated user can view/select accounts.
5. **Token logging**: Access tokens are NEVER logged. Only connection IDs and user IDs appear in logs.

---

## Troubleshooting

### "META_APP_ID and META_APP_SECRET must be configured"
- Ensure both env vars are set in `.env`
- Restart the backend after changing `.env`

### OAuth callback redirects with `meta_error`
- **Invalid state**: The state token expired (>5 min) or was already consumed. Try initiating OAuth again.
- **connection_failed**: Check backend logs for the actual error (token exchange failure, Meta API down, etc.)

### "User has no associated organization"
- The user must belong to an organization. Register via `/api/auth/register` and ensure org creation.

### Token expired after ~60 days
- The MetaConnection status will be set to `expired` when detected
- Admin needs to re-initiate OAuth via the Connect button
- The frontend shows "Reconnect" when the connection is expired

### Circular FK warning in tests
```
SAWarning: Can't sort tables for DROP; an unresolvable foreign key dependency exists
between tables: ad_accounts, meta_connections, organizations
```
- This is expected due to `Organization.active_ad_account_id` creating a circular reference
- Does not affect functionality; SQLite test teardown handles it fine

### Tests fail with 500 when run in full suite
- Ensure `META_APP_ID` and `META_APP_SECRET` env vars are set BEFORE importing `backend.main`
- The `_get_adapter()` function reads `os.getenv()` at call time to avoid stale settings singleton

---

## Production Considerations

1. **OAuth state storage**: Replace in-memory dict with Redis for multi-process deployments
2. **Token refresh**: Implement automated token refresh before expiry (cron job or background task)
3. **Webhook**: Register Meta webhooks for token invalidation notifications
4. **Rate limits**: Meta Graph API has rate limits — implement exponential backoff
5. **App Review**: Submit Meta app for review to use `ads_read` with non-test users
