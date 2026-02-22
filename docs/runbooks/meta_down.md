# Runbook: Meta API Down

## Symptoms
- `meta_sync_assets` and `meta_sync_insights` jobs failing with `transient` errors
- Circuit breaker for `meta` provider in `open` state
- `GET /api/ops/providers` shows `circuit_state: open` for meta
- Health check shows degraded status
- Alerts not being generated (depend on fresh insights)

## Detection
- Prometheus: `provider_calls_total{provider="meta",status="error"}` spike
- Prometheus: `circuit_breaker_state{provider="meta"} == 2` (open)
- Ops Console: meta provider card shows OPEN circuit + high failure count
- Logs: `META_API_ERROR` or `CIRCUIT_OPEN` entries

## Impact
- **Asset sync**: Campaigns/adsets/ads not refreshed (stale data, ~5 min lag tolerance)
- **Insights sync**: Spend/impressions/CTR not updated (stale data, ~15 min lag tolerance)
- **Live monitor**: Drift detection paused — no new drift alerts
- **Alert generation**: No new anomaly/insight alerts
- **Decisions**: Can still be created/approved but based on stale data
- **Existing data**: All previously synced data remains accessible

## Recovery Steps

1. **Check Meta API status**
   - Visit https://developers.facebook.com/status/
   - Check for known outages or degraded performance

2. **Verify credentials**
   - Ensure META_APP_ID and META_APP_SECRET are set
   - Check if access tokens have expired (look for `auth_required` error codes)
   - If token expired: user must re-authenticate via OAuth flow

3. **Monitor circuit breaker**
   - Circuit breaker auto-resets after cooldown (default: 60s)
   - On half_open, a single probe request is sent
   - If probe succeeds → closes circuit → normal flow resumes
   - If probe fails → back to open → waits another cooldown

4. **Manual intervention (if persistent)**
   - Check Redis for circuit state: `GET cb:meta:{org_id}`
   - Force reset: `DEL cb:meta:{org_id}` (circuit defaults to closed)
   - Retry failed jobs from Ops Console: `POST /api/ops/jobs/{id}/retry`

5. **Post-recovery**
   - Jobs in `retry_scheduled` will auto-resume
   - Jobs in `dead` state require manual retry from Ops Console
   - Verify sync lag returns to normal via `/api/meta/sync/status`
