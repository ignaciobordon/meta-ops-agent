# Meta API Live Testing Procedure

## Overview

This document describes how to safely test Meta Ops Agent's integration with the Meta (Facebook) Ads API. All live testing should be performed against a **test ad account** to avoid impacting production campaigns.

---

## 1. Prerequisites

### 1.1 Meta Developer Account Setup

1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Create a Meta App (type: Business)
3. Add the **Marketing API** product to your app
4. Request the following permissions:
   - `ads_management` - Create/modify ads
   - `ads_read` - Read ad performance data
   - `business_management` - Manage business assets
   - `pages_read_engagement` - Read page metrics

### 1.2 Test Ad Account

**Never test against a live production ad account.**

Option A: Use Meta's test ad account:
```
1. Go to Business Settings > Ad Accounts
2. Create a new ad account specifically for testing
3. Name it clearly: "Meta Ops Agent - TEST"
4. Set a low spending limit ($5/day)
```

Option B: Use Meta's Marketing API sandbox:
```
1. In your app dashboard, go to Marketing API > Tools
2. Use the API Explorer with the test ad account
3. All sandbox calls are free and don't create real ads
```

### 1.3 Access Token Generation

```bash
# Step 1: Get short-lived token from Graph API Explorer
# Go to: https://developers.facebook.com/tools/explorer/
# Select your app, request ads_management + ads_read permissions
# Copy the short-lived token

# Step 2: Exchange for long-lived token (60 days)
curl -s "https://graph.facebook.com/v21.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=SHORT_LIVED_TOKEN" | python3 -m json.tool

# Step 3: Store in .env
echo "META_ACCESS_TOKEN=your_long_lived_token" >> .env
```

### 1.4 Environment Configuration

```env
# .env file for testing
META_ACCESS_TOKEN=your_test_token_here
META_AD_ACCOUNT_ID=act_123456789
META_APP_ID=your_app_id
META_APP_SECRET=your_app_secret
META_API_VERSION=v21.0
```

---

## 2. API Connection Verification

### 2.1 Verify Token is Valid

```bash
# Check token info
curl -s "https://graph.facebook.com/v21.0/me?access_token=$META_ACCESS_TOKEN" | python3 -m json.tool

# Expected: { "name": "Your Name", "id": "..." }
```

### 2.2 Verify Ad Account Access

```bash
# List ad accounts accessible with this token
curl -s "https://graph.facebook.com/v21.0/me/adaccounts?\
fields=name,account_id,account_status&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool

# Expected: list of ad accounts with name and status
```

### 2.3 Verify via Application Health Check

```bash
# Start the application
cd backend && python main.py &

# Check health endpoint (includes Meta API dependency check)
curl -s http://localhost:8000/api/health | python3 -m json.tool

# Look for:
# "meta_api": { "status": "healthy", ... }
```

---

## 3. Read Operations Testing

### 3.1 Fetch Ad Account Details

```bash
# Via Meta API directly
curl -s "https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID?\
fields=name,currency,spend_cap,amount_spent,balance&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool

# Via application API
curl -s "http://localhost:8000/api/orgs/{org_id}/ad-accounts" \
  -H "Authorization: Bearer $JWT_TOKEN" | python3 -m json.tool
```

### 3.2 Fetch Campaign Performance

```bash
# Get campaigns with insights
curl -s "https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID/campaigns?\
fields=name,status,daily_budget,lifetime_budget,insights{impressions,clicks,spend,ctr,cpc}&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool
```

### 3.3 Fetch Ad Set Performance

```bash
# Get ad sets with performance data
curl -s "https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID/adsets?\
fields=name,status,daily_budget,bid_amount,targeting,insights{impressions,clicks,spend,ctr,frequency}&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool
```

### 3.4 Fetch Creative Performance (for Saturation Analysis)

```bash
# Get ads with creative details and performance
curl -s "https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID/ads?\
fields=name,status,creative{title,body,image_url},insights{impressions,clicks,spend,ctr,frequency,cpm}&\
date_preset=last_30d&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool
```

---

## 4. Write Operations Testing (Dry-Run First)

### 4.1 Budget Change (Dry-Run)

Test the decision workflow without actually changing anything:

```bash
# Step 1: Create a decision pack
curl -X POST http://localhost:8000/api/decisions/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "ad_account_id": "'$AD_ACCOUNT_UUID'",
    "user_id": "'$USER_UUID'",
    "action_type": "budget_change",
    "entity_type": "adset",
    "entity_id": "adset_test_123",
    "entity_name": "Test AdSet",
    "payload": {
      "current_budget": 10.00,
      "new_budget": 11.00
    },
    "rationale": "Test: 10% budget increase",
    "source": "API_Testing"
  }'

# Step 2: Validate (policy check)
curl -X POST http://localhost:8000/api/decisions/{decision_id}/validate \
  -H "Authorization: Bearer $JWT_TOKEN"

# Step 3: Request approval
curl -X POST http://localhost:8000/api/decisions/{decision_id}/request-approval \
  -H "Authorization: Bearer $JWT_TOKEN"

# Step 4: Approve
curl -X POST http://localhost:8000/api/decisions/{decision_id}/approve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"approver_user_id": "'$USER_UUID'"}'

# Step 5: Execute as DRY RUN
curl -X POST http://localhost:8000/api/decisions/{decision_id}/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"dry_run": true}'

# Expected: state = "executed", execution_result.dry_run = true
# NO actual changes made to Meta API
```

### 4.2 Budget Change (Live - Test Account Only)

**Only after dry-run succeeds and on TEST account:**

```bash
# Same flow as above but with dry_run: false
# Ensure operator_armed is enabled for the organization
curl -X POST http://localhost:8000/api/orgs/{org_id}/operator-armed \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"enabled": true}'

# Execute live
curl -X POST http://localhost:8000/api/decisions/{decision_id}/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{"dry_run": false}'

# Verify the change on Meta API directly
curl -s "https://graph.facebook.com/v21.0/{adset_id}?\
fields=daily_budget&\
access_token=$META_ACCESS_TOKEN" | python3 -m json.tool
```

### 4.3 AdSet Pause/Resume Test

```bash
# Create decision to pause an ad set
curl -X POST http://localhost:8000/api/decisions/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "ad_account_id": "'$AD_ACCOUNT_UUID'",
    "user_id": "'$USER_UUID'",
    "action_type": "adset_pause",
    "entity_type": "adset",
    "entity_id": "'$TEST_ADSET_ID'",
    "entity_name": "Test AdSet Pause",
    "payload": {
      "current_status": "ACTIVE",
      "new_status": "PAUSED"
    },
    "rationale": "Testing pause functionality",
    "source": "API_Testing"
  }'

# Follow the validate -> approve -> execute flow
```

---

## 5. Saturation Analysis Testing

### 5.1 Test with Demo Data

```bash
# The saturation endpoint works with both demo CSV and live data
curl -s http://localhost:8000/api/saturation/analyze \
  -H "Authorization: Bearer $JWT_TOKEN" | python3 -m json.tool

# Expected: List of creatives with saturation scores and recommendations
```

### 5.2 Test with Live Meta API Data

```bash
# Fetch live ad performance and run saturation analysis
curl -s "http://localhost:8000/api/saturation/analyze?ad_account_id=$META_AD_ACCOUNT_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" | python3 -m json.tool

# Verify each creative has:
# - saturation_score (0-100)
# - status (fresh/moderate/saturated)
# - recommendation (keep/monitor/refresh/kill)
```

---

## 6. Policy Engine Testing

### 6.1 Test Budget Limits

```bash
# Test: Budget change within limits (10% - should pass)
# Create decision with current_budget: 100, new_budget: 110
# Validate -> should get state: "ready"

# Test: Budget change exceeding limits (100% - should block)
# Create decision with current_budget: 100, new_budget: 200
# Validate -> should get state: "blocked"
```

### 6.2 Test Rate Limiting

```bash
# Send 110 requests rapidly (limit is 100/minute)
for i in $(seq 1 110); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health)
  echo "Request $i: $STATUS"
done

# Requests 101+ should return 429 (Too Many Requests)
```

---

## 7. Error Scenario Testing

### 7.1 Expired Token

```bash
# Use an expired token
curl -s "https://graph.facebook.com/v21.0/me?\
access_token=EXPIRED_TOKEN_HERE" | python3 -m json.tool

# Expected: { "error": { "message": "...", "code": 190 } }
# Application should show "degraded" health status
```

### 7.2 Insufficient Permissions

```bash
# Try to modify ads with read-only token
# Application should return clear error message
```

### 7.3 API Rate Limiting (Meta's limits)

```
Meta API limits:
- Standard: 200 calls/hour per ad account
- Business: higher limits based on access tier

Monitor via: https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID?fields=rate_limit_setting
```

---

## 8. End-to-End Smoke Test Checklist

Run this checklist before each deployment:

```
Pre-flight:
[ ] META_ACCESS_TOKEN is valid (check with /me endpoint)
[ ] Test ad account is accessible
[ ] Application starts without errors
[ ] Health endpoint shows all dependencies green

Read operations:
[ ] Can fetch ad account details
[ ] Can fetch campaign list
[ ] Can fetch ad set performance
[ ] Can fetch creative performance data

Decision workflow:
[ ] Can create a draft decision
[ ] Policy validation works (passes valid, blocks invalid)
[ ] Approval flow works (request -> approve)
[ ] Dry-run execution succeeds
[ ] Audit trail recorded for all actions

Saturation analysis:
[ ] Demo CSV analysis returns results
[ ] Saturation scores are in valid range (0-100)
[ ] Recommendations are actionable (keep/monitor/refresh/kill)

Error handling:
[ ] Invalid token returns clear error
[ ] Rate limiting works (429 after limit)
[ ] Non-existent resources return 404
[ ] Invalid state transitions return 400

Monitoring:
[ ] Health endpoint reports correct status
[ ] Prometheus metrics endpoint returns data
[ ] Logs contain trace IDs for all operations
```

---

## 9. Token Refresh Schedule

Meta access tokens expire. Set up automated refresh:

```bash
#!/bin/bash
# /opt/meta-ops-agent/scripts/refresh_token.sh
# Run weekly via cron

CURRENT_TOKEN=$(grep META_ACCESS_TOKEN /opt/meta-ops-agent/.env | cut -d= -f2)

# Check if token is still valid
RESULT=$(curl -s "https://graph.facebook.com/v21.0/me?access_token=$CURRENT_TOKEN")
if echo "$RESULT" | grep -q "error"; then
    echo "$(date): Token expired or invalid - manual intervention required"
    # Send alert
    exit 1
fi

# Check remaining token lifetime
TOKEN_INFO=$(curl -s "https://graph.facebook.com/v21.0/debug_token?\
input_token=$CURRENT_TOKEN&\
access_token=$CURRENT_TOKEN")

EXPIRES=$(echo "$TOKEN_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['expires_at'])")
NOW=$(date +%s)
DAYS_LEFT=$(( (EXPIRES - NOW) / 86400 ))

if [ $DAYS_LEFT -lt 7 ]; then
    echo "$(date): Token expires in $DAYS_LEFT days - refresh needed"
    # Attempt to refresh long-lived token
    NEW_TOKEN=$(curl -s "https://graph.facebook.com/v21.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=$META_APP_ID&\
client_secret=$META_APP_SECRET&\
fb_exchange_token=$CURRENT_TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

    if [ -n "$NEW_TOKEN" ]; then
        sed -i "s|META_ACCESS_TOKEN=.*|META_ACCESS_TOKEN=$NEW_TOKEN|" /opt/meta-ops-agent/.env
        sudo systemctl restart meta-ops-agent
        echo "$(date): Token refreshed successfully"
    else
        echo "$(date): Token refresh FAILED - manual intervention required"
        exit 1
    fi
fi
```

Crontab entry:
```
0 6 * * 1 /opt/meta-ops-agent/scripts/refresh_token.sh >> /var/log/meta-ops-token.log 2>&1
```

---

## 10. Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| 401 Unauthorized | Token validity | Regenerate token via Graph Explorer |
| 403 Forbidden | Permission scopes | Re-request ads_management permission |
| Rate limited (code 32) | API call frequency | Reduce polling interval, check rate_limit_setting |
| No data returned | Date range | Ensure campaigns have recent activity |
| Webhook not firing | Callback URL | Verify HTTPS URL is publicly accessible |
| Budget not changing | Operator Armed | Enable operator_armed for the organization |
