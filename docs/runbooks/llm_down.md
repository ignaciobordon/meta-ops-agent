# Runbook: LLM Provider Down (Anthropic/OpenAI)

## Symptoms
- `creatives_generate` jobs failing
- `meta_generate_alerts` partially failing (InsightEngine depends on LLM)
- Circuit breaker for `anthropic` or `openai` in `open` state
- Prometheus: `provider_calls_total{provider="anthropic",status="error"}` spike

## Detection
- Ops Console: anthropic/openai provider card shows OPEN circuit
- Prometheus: `circuit_breaker_state{provider="anthropic"} == 2`
- Logs: `LLM_CALL_FAILED` or `ANTHROPIC_ERROR` entries
- Health check: `anthropic_api` dependency shows degraded

## Impact
- **Creative generation**: Blocked — requires LLM for ad copy
- **Insight engine**: Degrades to rule-based detection only (AnomalyDetector still works)
- **Decision creation**: Manual decisions still work (no LLM dependency)
- **Sync pipeline**: Unaffected (Meta API independent of LLM)
- **Existing creatives**: All previously generated content remains accessible

## Fallback Behavior
- AnomalyDetector operates purely on statistical rules — no LLM needed
- InsightEngine can fall back to rule-based insights if LLM unavailable
- The system continues to sync data and detect anomalies without LLM

## Recovery Steps

1. **Check provider status**
   - Anthropic: https://status.anthropic.com/
   - OpenAI: https://status.openai.com/

2. **Verify API key**
   - Ensure ANTHROPIC_API_KEY is set and valid
   - Check for quota_exceeded errors (billing issue)

3. **Rate limit check**
   - If error is `quota_exceeded`: check billing/usage on provider dashboard
   - Rate limiter prevents burst: `GET /api/ops/providers` shows remaining tokens

4. **Circuit breaker recovery**
   - Auto-resets after cooldown period
   - Monitor via Ops Console or Prometheus

5. **Manual retry**
   - Failed `creatives_generate` jobs: retry from Ops Console
   - `meta_generate_alerts` jobs may need retry for full insight generation

6. **Post-recovery**
   - Verify creative generation works: trigger from UI
   - Check insight engine produces LLM-enriched alerts again
