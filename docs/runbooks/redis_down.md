# Runbook: Redis Down

## Symptoms
- Health check shows `redis` dependency as `degraded` or `unhealthy`
- System enters RESTRICTED mode (see `GET /api/health`)
- Celery workers cannot connect to broker
- New jobs cannot be enqueued
- Rate limiting and circuit breakers fall back to permissive defaults

## Detection
- Health check: `redis` dependency status = `unhealthy`
- Prometheus: system mode gauge indicates restricted
- Logs: `REDIS_UNAVAILABLE` or connection refused errors
- `get_system_mode()` returns `RESTRICTED`
- Docker: `docker compose ps redis` shows unhealthy

## Impact

### Blocked (Requires Redis)
- **Job enqueueing**: Celery broker unavailable → new jobs cannot be dispatched
- **Job execution**: Workers cannot pick up tasks from queues
- **Scheduled job processing**: MetaJobScheduler cannot enqueue to Celery

### Degraded (Fallback Active)
- **Rate limiting**: Falls back to "allow all" — no provider rate limiting
- **Circuit breakers**: Falls back to "closed" — all requests allowed
- **Execution locks**: Falls back to "acquired" — no distributed lock protection
- **Idempotency**: DB constraint still enforced; Redis lock layer skipped

### Unaffected
- **API reads**: All GET endpoints work normally (database-backed)
- **Database**: PostgreSQL independent of Redis
- **Health checks**: Continue to report status
- **Existing data**: All synced data, decisions, outcomes accessible
- **Authentication**: JWT-based, no Redis dependency

## Recovery Steps

1. **Check Redis service**
   ```bash
   docker compose ps redis
   docker compose logs redis --tail=50
   ```

2. **Restart Redis**
   ```bash
   docker compose restart redis
   ```

3. **Verify connectivity**
   ```bash
   docker compose exec redis redis-cli ping
   # Should return: PONG
   ```

4. **Check data persistence**
   - Redis data volume: `redisdata`
   - Circuit breaker states persist across restarts
   - Rate limiter windows reset (acceptable — short-lived)

5. **Restart Celery workers** (if they lost broker connection)
   ```bash
   docker compose restart celery-default celery-io celery-llm
   ```

6. **Verify system mode**
   - `GET /api/health` should show redis: healthy
   - `get_system_mode()` should return NORMAL

7. **Process backlog**
   - Any ScheduledJobs that came due during outage will be picked up
     on next `process_meta_jobs()` cycle
   - Jobs stuck in QUEUED can be verified via Ops Console
   - Dead jobs from the outage period: retry from Ops Console

## Prevention
- Redis healthcheck in docker-compose monitors availability
- `redis:7-alpine` image is lightweight and stable
- Volume mount ensures data survives container restarts
- All Redis-dependent code has graceful degradation paths
