# Runbook: LLM Router Multi-Provider

## Overview

The LLM Router (`backend/src/llm/router.py`) provides unified access to Anthropic and OpenAI APIs with automatic fallback, circuit breaker, and rate limiting. All three engines (BrandMapBuilder, Factory, Scorer) route through `LLMRouter.generate()`.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | At least one key | - | Anthropic API key |
| `OPENAI_API_KEY` | At least one key | - | OpenAI API key |
| `LLM_DEFAULT_PROVIDER` | No | Auto-detected | `anthropic` or `openai` |
| `LLM_FALLBACK_PROVIDER` | No | `openai` | Fallback when primary fails |
| `LLM_TIMEOUT_SECONDS` | No | `30` | Per-call timeout |
| `LLM_PROVIDER` | No (legacy) | - | Sprint <=8 compat, maps to `LLM_DEFAULT_PROVIDER` |

**Auto-detection logic** (when `LLM_DEFAULT_PROVIDER` is empty):
1. If `LLM_PROVIDER` is set (legacy) -> use it
2. Else if `ANTHROPIC_API_KEY` is set -> `anthropic`
3. Else if `OPENAI_API_KEY` is set -> `openai`
4. Else -> `anthropic` (will fail at call time)

---

## Diagnostics Endpoint

```
GET /api/system/llm/diagnostics
Authorization: Bearer <admin_token>
```

Returns:
- `default_provider`, `fallback_provider`
- `anthropic_key_present`, `openai_key_present` (bool, never exposes keys)
- `timeout_seconds`
- `router_ready` (bool)
- `circuit_breakers` per provider (state, failure_count)
- `rate_limiters` per provider (remaining, total)

---

## Verify LLM Works Locally

```bash
# 1. Check .env has at least one key
grep -E "ANTHROPIC_API_KEY|OPENAI_API_KEY" .env

# 2. Start backend
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 3. Hit diagnostics (requires admin JWT)
curl -s http://localhost:8000/api/system/llm/diagnostics \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python -m json.tool

# 4. Test creative generation
curl -X POST http://localhost:8000/api/creatives/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"angle_id": "social_proof", "brand_map_id": "demo", "n_variants": 1}'
```

---

## Verify LLM Works in Docker

```bash
# 1. Ensure .env is populated
# 2. Start all services
docker compose up -d

# 3. Check celery-llm worker logs
docker compose logs celery-llm --tail=50

# 4. Verify env vars propagated
docker compose exec celery-llm env | grep -E "ANTHROPIC|OPENAI|LLM_"

# 5. Hit diagnostics
curl -s http://localhost:8000/api/system/llm/diagnostics \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Troubleshooting

### "All LLM providers failed"
- Check both API keys are set
- Check circuit breaker state via diagnostics endpoint
- Check rate limiter remaining tokens
- Review logs for `LLM_PRIMARY_FAILED` / `LLM_FALLBACK_FAILED`

### Worker not processing LLM jobs
- Verify celery-llm container has `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
- Check `docker compose logs celery-llm` for import errors
- Ensure `creatives_generate` job type routes to `llm` queue

### Circuit breaker stuck OPEN
- Wait for recovery timeout (default 60s)
- Or manually reset via Redis: `DEL cb:anthropic:global` / `DEL cb:openai:global`

### Timeout errors
- Increase `LLM_TIMEOUT_SECONDS` in .env
- Check Celery task time limits in `celery_app.py` (default: 300s soft / 360s hard for LLM tasks)

---

## Architecture

```
API Request
  -> LLMRouter.generate(LLMRequest)
    -> _call_with_resilience(primary_provider)
      -> PersistentCircuitBreaker.allow_request?
      -> ProviderRateLimiter.acquire?
      -> provider.generate() with thread timeout
      -> Track metrics (Prometheus)
    -> On failure: fallback to secondary provider
    -> On total failure: raise LLMProviderError
```

Task types and default models:
| Task Type | Anthropic Model | OpenAI Model |
|---|---|---|
| `brand_map` | claude-haiku-4-5 | gpt-4o-2024-08-06 |
| `creative_factory` | claude-sonnet-4-5 | gpt-4o-2024-08-06 |
| `scoring` | claude-haiku-4-5 | gpt-4o-2024-08-06 |
