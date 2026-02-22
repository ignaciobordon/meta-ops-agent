"""
FASE 4.2: Prometheus Metrics
Production-grade observability with Prometheus metrics.
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from time import time

from backend.src.config import settings


class PrometheusMetrics:
    """
    Prometheus metrics collector for Meta Ops Agent.

    Tracks:
    - HTTP requests (count, duration, status)
    - Decision state transitions
    - Engine execution times
    - Error rates
    """

    def __init__(self):
        # HTTP Metrics
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )

        self.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )

        self.http_request_in_progress = Gauge(
            'http_requests_in_progress',
            'Number of HTTP requests currently being processed',
            ['method', 'endpoint']
        )

        # Decision Metrics
        self.decisions_created_total = Counter(
            'decisions_created_total',
            'Total decisions created',
            ['action_type']
        )

        self.decision_state_transitions_total = Counter(
            'decision_state_transitions_total',
            'Total decision state transitions',
            ['from_state', 'to_state']
        )

        self.decisions_by_state = Gauge(
            'decisions_by_state',
            'Current number of decisions by state',
            ['state']
        )

        # Engine Metrics
        self.engine_execution_duration_seconds = Histogram(
            'engine_execution_duration_seconds',
            'Engine execution duration in seconds',
            ['engine_name'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
        )

        self.engine_errors_total = Counter(
            'engine_errors_total',
            'Total engine execution errors',
            ['engine_name', 'error_type']
        )

        # Rate Limiting Metrics
        self.rate_limit_exceeded_total = Counter(
            'rate_limit_exceeded_total',
            'Total rate limit violations',
            ['client_id']
        )

        # Database Metrics
        self.database_queries_total = Counter(
            'database_queries_total',
            'Total database queries',
            ['query_type']
        )

        self.database_query_duration_seconds = Histogram(
            'database_query_duration_seconds',
            'Database query duration in seconds',
            ['query_type'],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
        )

        # Application Metrics
        self.app_info = Gauge(
            'app_info',
            'Application information',
            ['version', 'environment']
        )

        # Sprint 7: Job Run Metrics
        self.job_runs_total = Counter(
            'job_runs_total',
            'Total job runs by type and final status',
            ['job_type', 'status']
        )

        self.job_run_duration_seconds = Histogram(
            'job_run_duration_seconds',
            'Job run execution duration in seconds',
            ['job_type'],
            buckets=[0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0]
        )

        # Sprint 7: Provider Metrics
        self.provider_calls_total = Counter(
            'provider_calls_total',
            'Total external provider API calls',
            ['provider', 'status']
        )

        self.provider_latency_seconds = Histogram(
            'provider_latency_seconds',
            'Provider API call latency in seconds',
            ['provider'],
            buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )

        self.rate_limit_blocks_total = Counter(
            'rate_limit_blocks_total',
            'Total requests blocked by provider rate limiting',
            ['provider']
        )

        self.circuit_breaker_state_gauge = Gauge(
            'circuit_breaker_state',
            'Circuit breaker state (0=closed, 1=half_open, 2=open)',
            ['provider', 'org_id']
        )

        # Sprint 9: LLM Router Metrics
        self.llm_requests_total = Counter(
            'llm_requests_total',
            'Total LLM requests via router',
            ['provider', 'task_type', 'status']
        )

        self.llm_latency_seconds = Histogram(
            'llm_latency_seconds',
            'LLM request latency in seconds',
            ['provider', 'task_type'],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0]
        )

        self.llm_fallbacks_total = Counter(
            'llm_fallbacks_total',
            'Total LLM fallback events',
            ['from_provider', 'to_provider', 'task_type']
        )

        # CI AutoLoop Metrics
        self.ci_runs_total = Counter(
            'ci_runs_total',
            'Total CI AutoLoop runs by type and status',
            ['run_type', 'status']
        )

        self.ci_run_duration_seconds = Histogram(
            'ci_run_duration_seconds',
            'CI AutoLoop run duration in seconds',
            ['run_type'],
            buckets=[0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0]
        )

        self.ci_items_collected_total = Counter(
            'ci_items_collected_total',
            'Total CI items collected across all runs',
            ['source']
        )

        self.ci_opportunities_detected_total = Counter(
            'ci_opportunities_detected_total',
            'Total CI opportunities detected',
            []
        )

        self.ci_alerts_created_total = Counter(
            'ci_alerts_created_total',
            'Total CI alerts created',
            ['alert_type']
        )

        self.ci_tick_orgs_gauge = Gauge(
            'ci_tick_orgs_processed',
            'Number of orgs processed in last CI tick',
            []
        )

        # Set application info
        self.app_info.labels(
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
        ).set(1)


# Global metrics instance
metrics = PrometheusMetrics()


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to automatically track HTTP metrics.
    """

    async def dispatch(self, request: Request, call_next):
        # Extract endpoint pattern (remove IDs)
        endpoint = self._normalize_endpoint(request.url.path)
        method = request.method

        # Track in-progress requests
        metrics.http_request_in_progress.labels(
            method=method,
            endpoint=endpoint
        ).inc()

        # Start timer
        start_time = time()

        try:
            # Process request
            response = await call_next(request)

            # Calculate duration
            duration = time() - start_time

            # Record metrics
            metrics.http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=response.status_code
            ).inc()

            metrics.http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

            return response

        except Exception as e:
            # Record error
            duration = time() - start_time

            metrics.http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status=500
            ).inc()

            metrics.http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)

            raise

        finally:
            # Decrement in-progress counter
            metrics.http_request_in_progress.labels(
                method=method,
                endpoint=endpoint
            ).dec()

    def _normalize_endpoint(self, path: str) -> str:
        """
        Normalize endpoint path for metrics (remove IDs).

        Examples:
            /api/decisions/123 -> /api/decisions/{id}
            /api/saturation/angle/foo -> /api/saturation/angle/{id}
        """
        parts = path.split('/')

        # Replace UUIDs and numeric IDs with {id}
        normalized = []
        for part in parts:
            if not part:
                continue

            # Check if part looks like an ID
            if self._looks_like_id(part):
                normalized.append('{id}')
            else:
                normalized.append(part)

        return '/' + '/'.join(normalized)

    def _looks_like_id(self, s: str) -> bool:
        """Check if string looks like an ID (UUID or numeric)."""
        # Numeric ID
        if s.isdigit():
            return True

        # UUID pattern (simplified check)
        if len(s) == 36 and s.count('-') == 4:
            return True

        # Hex ID (8+ chars of hex)
        if len(s) >= 8 and all(c in '0123456789abcdefABCDEF-' for c in s):
            return True

        return False


# Middleware instance for easy import
metrics_middleware = MetricsMiddleware


def track_decision_created(action_type: str):
    """Track decision creation."""
    metrics.decisions_created_total.labels(action_type=action_type).inc()


def track_state_transition(from_state: str, to_state: str):
    """Track decision state transition."""
    metrics.decision_state_transitions_total.labels(
        from_state=from_state,
        to_state=to_state
    ).inc()


def track_engine_execution(engine_name: str, duration: float):
    """Track engine execution time."""
    metrics.engine_execution_duration_seconds.labels(
        engine_name=engine_name
    ).observe(duration)


def track_engine_error(engine_name: str, error_type: str):
    """Track engine error."""
    metrics.engine_errors_total.labels(
        engine_name=engine_name,
        error_type=error_type
    ).inc()


def track_rate_limit_exceeded(client_id: str):
    """Track rate limit violation."""
    metrics.rate_limit_exceeded_total.labels(client_id=client_id).inc()


def track_job_run(job_type: str, status: str, duration: float = 0.0):
    """Track job run completion."""
    metrics.job_runs_total.labels(job_type=job_type, status=status).inc()
    if duration > 0:
        metrics.job_run_duration_seconds.labels(job_type=job_type).observe(duration)


def track_provider_call(provider: str, status: str, latency: float = 0.0):
    """Track external provider API call."""
    metrics.provider_calls_total.labels(provider=provider, status=status).inc()
    if latency > 0:
        metrics.provider_latency_seconds.labels(provider=provider).observe(latency)


def track_rate_limit_block(provider: str):
    """Track a rate-limit block event."""
    metrics.rate_limit_blocks_total.labels(provider=provider).inc()


def track_llm_request(provider: str, task_type: str, status: str, latency: float = 0.0):
    """Track an LLM router request."""
    metrics.llm_requests_total.labels(provider=provider, task_type=task_type, status=status).inc()
    if latency > 0:
        metrics.llm_latency_seconds.labels(provider=provider, task_type=task_type).observe(latency)


def track_llm_fallback(from_provider: str, to_provider: str, task_type: str):
    """Track an LLM fallback event."""
    metrics.llm_fallbacks_total.labels(
        from_provider=from_provider, to_provider=to_provider, task_type=task_type
    ).inc()


def set_circuit_breaker_state(provider: str, org_id: str, state: str):
    """Update circuit breaker state gauge (0=closed, 1=half_open, 2=open)."""
    state_map = {"closed": 0, "half_open": 1, "open": 2}
    metrics.circuit_breaker_state_gauge.labels(
        provider=provider, org_id=org_id
    ).set(state_map.get(state, 0))


def track_ci_run(run_type: str, status: str, duration: float = 0.0):
    """Track a CI AutoLoop run."""
    metrics.ci_runs_total.labels(run_type=run_type, status=status).inc()
    if duration > 0:
        metrics.ci_run_duration_seconds.labels(run_type=run_type).observe(duration)


def track_ci_items_collected(source: str, count: int):
    """Track CI items collected."""
    if count > 0:
        metrics.ci_items_collected_total.labels(source=source).inc(count)


def track_ci_opportunities_detected(count: int):
    """Track CI opportunities detected."""
    if count > 0:
        metrics.ci_opportunities_detected_total.inc(count)


def track_ci_alerts_created(alert_type: str, count: int = 1):
    """Track CI alerts created."""
    metrics.ci_alerts_created_total.labels(alert_type=alert_type).inc(count)


def track_ci_tick_orgs(count: int):
    """Set the number of orgs processed in the last CI tick."""
    metrics.ci_tick_orgs_gauge.set(count)


async def metrics_endpoint(request: Request):
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format.
    Mount at /metrics for Prometheus scraping.
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
