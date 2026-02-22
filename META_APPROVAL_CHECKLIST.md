# Meta App Review — Approval Checklist

Checklist and reference for Meta App Review submission for Meta Ops Agent.

---

## App Info

| Field         | Value                                    |
|---------------|------------------------------------------|
| App Name      | Meta Ops Agent                           |
| Type          | Business Tool / Ads Management           |
| Platform      | Web (React SPA + FastAPI backend)        |

---

## Permissions Requested

- [x] `ads_read` — Read ad campaigns, ad sets, ads, and performance metrics
- [ ] `ads_management` — **NOT requested** (read-only mode)

---

## Data Usage

### What data is collected

- Ad account IDs
- Campaign names
- Performance metrics: spend, impressions, clicks, CTR, CPM

### How data is stored

- Encrypted in PostgreSQL
- Tokens encrypted with Fernet (AES symmetric encryption)

### Data retention

- Active while subscription is valid
- Data is removed upon account deletion or subscription expiry

### Data sharing

- **Not shared with third parties**

---

## Privacy & Terms

| Document             | URL                              |
|----------------------|----------------------------------|
| Privacy Policy       | [required for submission]        |
| Terms of Service     | [required for submission]        |
| Data Deletion        | [required for submission]        |

> **Action Required:** These URLs must be live and publicly accessible before submitting for Meta App Review.

---

## OAuth Flow

### Configuration

| Parameter      | Value                                                                                  |
|----------------|----------------------------------------------------------------------------------------|
| Redirect URI (dev)  | `http://localhost:8000/api/meta/oauth/callback`                                  |
| Redirect URI (prod) | `https://yourdomain.com/api/meta/oauth/callback`                                |
| Scopes         | `ads_read`                                                                             |
| State parameter| CSRF protection via `MetaOAuthAdapter`                                                 |

### Flow Description

1. User clicks "Connect Meta Account" in the application
2. Backend generates an OAuth URL with state parameter for CSRF protection
3. User is redirected to Meta's OAuth consent screen
4. User grants `ads_read` permission
5. Meta redirects back to the callback URI with an authorization code
6. Backend exchanges the code for an access token
7. Token is encrypted with Fernet and stored in the database
8. Backend syncs ad account data using the token

---

## Security

### Token Storage

- AES-encrypted in database via Fernet symmetric encryption
- Encryption key stored as environment variable (`FERNET_KEY`), never in source code

### Token Refresh

- Handled server-side automatically
- Long-lived tokens are exchanged before expiry

### Token Expiry Detection

- `GET /api/meta/verify` checks token validity on each call
- Returns `token_valid: false` with `recommended_fix` when token is expired or invalid
- User is prompted to re-authenticate via the OAuth flow

---

## API Endpoints Using Meta Data

| Endpoint                    | Method | Description                                      |
|-----------------------------|--------|--------------------------------------------------|
| `/api/meta/verify`          | GET    | Connection health check (token_valid, scopes, recommended_fix) |
| `/api/meta/adaccounts`      | GET    | List synced ad accounts                          |
| `/api/meta/campaigns`       | GET    | List campaigns (cached from sync)                |
| `/api/meta/insights`        | GET    | Performance metrics (cached from sync)           |

All endpoints require authentication. Meta data is cached locally after sync and served from the database to minimize API calls to Meta.

---

## Test User

For Meta App Review, provide the following:

- [ ] Test user credentials (email + password) with access to the application
- [ ] Test ad account with sample campaign data
- [ ] Ensure the test ad account has at least one active or recently active campaign with performance metrics

> **Action Required:** Create a test user in the application and ensure the test Meta ad account has sufficient sample data for reviewers to verify functionality.

---

## Submission Checklist

- [ ] Privacy Policy URL is live and accessible
- [ ] Terms of Service URL is live and accessible
- [ ] Data Deletion URL is live and accessible
- [ ] OAuth redirect URIs are configured in Meta App Dashboard
- [ ] Test user credentials are prepared
- [ ] Test ad account has sample data
- [ ] App is deployed to a publicly accessible URL (for production review)
- [ ] `ads_read` permission is requested (and only `ads_read`)
- [ ] App description and screenshots are uploaded to Meta App Dashboard
- [ ] Video walkthrough of the app's use of Meta data is recorded (if required)
