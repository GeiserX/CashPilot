"""Optional Prometheus metrics for CashPilot.

Enable by setting CASHPILOT_METRICS_ENABLED=true. Exposes /metrics endpoint
for Prometheus scraping (unauthenticated, standard practice).

Metrics exposed:
  - HTTP: request count, latency by method/path/status
  - Containers: count by status/node, resource usage (CPU/memory), lifecycle events
  - Earnings: balance per platform, total USD
  - Collection: run count, duration histogram, per-platform errors
  - Workers: count by status, heartbeat staleness, Docker availability
  - Health: per-service score, uptime percentage
  - Auth: login attempts, rate-limit hits
  - System: app uptime, build info
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import os
import re
import time

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

METRICS_ENABLED = os.getenv("CASHPILOT_METRICS_ENABLED", "").lower() in ("1", "true", "yes")
# Optional bearer token for /metrics. When set, scrapers must send
# `Authorization: Bearer <token>`; when empty, /metrics stays unauthenticated
# (Prometheus convention) and relies on network isolation / a reverse proxy.
METRICS_TOKEN = os.getenv("CASHPILOT_METRICS_TOKEN", "")

_registry = None
_metrics: dict = {}
_start_time: float = time.time()
_last_refresh: float = 0.0
_REFRESH_TTL: float = 30.0


def _init_metrics():
    global _registry, _metrics
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info

    _registry = CollectorRegistry()

    # -- Build / system info --
    _metrics["build_info"] = Info(
        "cashpilot",
        "CashPilot build information",
        registry=_registry,
    )
    _metrics["uptime_seconds"] = Gauge(
        "cashpilot_uptime_seconds",
        "Seconds since CashPilot process started",
        registry=_registry,
    )

    # -- HTTP request metrics --
    _metrics["http_requests_total"] = Counter(
        "cashpilot_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
        registry=_registry,
    )
    _metrics["http_request_duration_seconds"] = Histogram(
        "cashpilot_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "path"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        registry=_registry,
    )
    _metrics["http_requests_in_progress"] = Gauge(
        "cashpilot_http_requests_in_progress",
        "Number of HTTP requests currently being processed",
        ["method"],
        registry=_registry,
    )

    # -- Container metrics --
    _metrics["containers_total"] = Gauge(
        "cashpilot_containers_total",
        "Number of managed containers by status and node",
        ["status", "node"],
        registry=_registry,
    )
    _metrics["container_info"] = Gauge(
        "cashpilot_container_info",
        "Container presence (1=exists)",
        ["service", "node", "status"],
        registry=_registry,
    )
    _metrics["container_cpu_percent"] = Gauge(
        "cashpilot_container_cpu_percent",
        "Container CPU usage percentage",
        ["service", "node"],
        registry=_registry,
    )
    _metrics["container_memory_mb"] = Gauge(
        "cashpilot_container_memory_mb",
        "Container memory usage in MB",
        ["service", "node"],
        registry=_registry,
    )
    _metrics["container_lifecycle_total"] = Counter(
        "cashpilot_container_lifecycle_total",
        "Container lifecycle events",
        ["action", "service"],
        registry=_registry,
    )

    # -- Earnings metrics --
    _metrics["earnings_balance"] = Gauge(
        "cashpilot_earnings_balance",
        "Latest known balance per platform (in platform currency)",
        ["platform", "currency"],
        registry=_registry,
    )
    _metrics["earnings_balance_usd"] = Gauge(
        "cashpilot_earnings_balance_usd",
        "Latest known balance per platform converted to USD",
        ["platform"],
        registry=_registry,
    )
    _metrics["earnings_total_usd"] = Gauge(
        "cashpilot_earnings_total_usd",
        "Sum of all platform balances in USD",
        registry=_registry,
    )

    # -- Collection metrics --
    _metrics["collection_runs_total"] = Counter(
        "cashpilot_collection_runs_total",
        "Total earnings collection runs by result",
        ["result"],
        registry=_registry,
    )
    _metrics["collection_duration_seconds"] = Histogram(
        "cashpilot_collection_duration_seconds",
        "Duration of earnings collection runs",
        buckets=[1, 5, 10, 30, 60, 120, 300],
        registry=_registry,
    )
    _metrics["collection_errors_total"] = Counter(
        "cashpilot_collection_errors_total",
        "Total collection errors by platform",
        ["platform"],
        registry=_registry,
    )
    _metrics["collection_last_success_timestamp"] = Gauge(
        "cashpilot_collection_last_success_timestamp",
        "Unix timestamp of last successful collection run",
        registry=_registry,
    )
    _metrics["collection_platforms_scraped"] = Gauge(
        "cashpilot_collection_platforms_scraped",
        "Number of platforms successfully scraped in last run",
        registry=_registry,
    )

    # -- Worker metrics --
    _metrics["workers_total"] = Gauge(
        "cashpilot_workers_total",
        "Number of registered workers by status",
        ["status"],
        registry=_registry,
    )
    _metrics["worker_last_heartbeat_seconds"] = Gauge(
        "cashpilot_worker_last_heartbeat_seconds",
        "Seconds since last heartbeat per worker",
        ["worker"],
        registry=_registry,
    )
    _metrics["worker_docker_available"] = Gauge(
        "cashpilot_worker_docker_available",
        "Whether Docker is available on this worker (1=yes, 0=no)",
        ["worker"],
        registry=_registry,
    )
    _metrics["worker_containers_count"] = Gauge(
        "cashpilot_worker_containers_count",
        "Number of containers on each worker",
        ["worker"],
        registry=_registry,
    )
    _metrics["heartbeats_total"] = Counter(
        "cashpilot_heartbeats_total",
        "Total heartbeat messages received from workers",
        ["worker"],
        registry=_registry,
    )

    # -- Health metrics --
    _metrics["health_score"] = Gauge(
        "cashpilot_health_score",
        "Health score per service (0-100)",
        ["service"],
        registry=_registry,
    )
    _metrics["health_uptime_percent"] = Gauge(
        "cashpilot_health_uptime_percent",
        "Uptime percentage per service over last 7 days",
        ["service"],
        registry=_registry,
    )

    # -- Deployment metrics --
    _metrics["services_deployed_total"] = Gauge(
        "cashpilot_services_deployed_total",
        "Total number of services currently deployed",
        registry=_registry,
    )
    _metrics["services_available_total"] = Gauge(
        "cashpilot_services_available_total",
        "Total number of services in the catalog",
        registry=_registry,
    )

    # -- Auth metrics --
    _metrics["login_attempts_total"] = Counter(
        "cashpilot_login_attempts_total",
        "Total login attempts by result",
        ["result"],
        registry=_registry,
    )
    _metrics["login_rate_limited_total"] = Counter(
        "cashpilot_login_rate_limited_total",
        "Total login attempts blocked by rate limiter",
        registry=_registry,
    )


def setup(app: FastAPI) -> None:
    """Mount the /metrics endpoint and HTTP middleware if metrics are enabled."""
    if not METRICS_ENABLED:
        return

    _init_metrics()

    # /metrics exposes earnings and health totals. It requires a bearer token when
    # CASHPILOT_METRICS_TOKEN is set; otherwise it is served UNAUTHENTICATED
    # (Prometheus convention) and must be protected by network isolation / a proxy.
    if METRICS_TOKEN:
        logger.info("Prometheus /metrics is ENABLED and requires a bearer token (CASHPILOT_METRICS_TOKEN).")
    else:
        logger.warning(
            "Prometheus /metrics is ENABLED and served UNAUTHENTICATED — it exposes your "
            "earnings and health data to anyone who can reach this port. Set "
            "CASHPILOT_METRICS_TOKEN to require a bearer token, and/or keep it behind a "
            "reverse proxy with auth; do not expose the port directly to an untrusted network."
        )

    from fastapi import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.middleware.base import BaseHTTPMiddleware

    _metrics["build_info"].info(
        {
            "version": app.version,
            "title": app.title,
        }
    )

    class _MetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/metrics":
                return await call_next(request)

            method = request.method
            path = _normalize_path(request.url.path)

            _metrics["http_requests_in_progress"].labels(method=method).inc()
            start = time.time()
            try:
                response = await call_next(request)
                duration = time.time() - start
                status = str(response.status_code)
                _metrics["http_requests_total"].labels(method=method, path=path, status=status).inc()
                _metrics["http_request_duration_seconds"].labels(method=method, path=path).observe(duration)
                return response
            except Exception:
                duration = time.time() - start
                _metrics["http_requests_total"].labels(method=method, path=path, status="500").inc()
                _metrics["http_request_duration_seconds"].labels(method=method, path=path).observe(duration)
                raise
            finally:
                _metrics["http_requests_in_progress"].labels(method=method).dec()

    app.add_middleware(_MetricsMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(request: Request):
        if METRICS_TOKEN and not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), f"Bearer {METRICS_TOKEN}".encode()
        ):
            return Response(status_code=401, content="Unauthorized")
        _metrics["uptime_seconds"].set(time.time() - _start_time)
        await _refresh_gauges()
        return Response(
            content=generate_latest(_registry),
            media_type=CONTENT_TYPE_LATEST,
        )


_PATH_SLUG_RE = re.compile(r"/api/(?:services|deploy|stop|restart|remove|compose)/[^/]+")
_WORKER_ID_RE = re.compile(r"(/api/workers)/\d+")
# Top-level prefixes the app actually serves. Anything else is scanner/probe noise
# (/wp-admin, /.env, ...) and must not each become its own Prometheus label.
_KNOWN_PREFIXES = ("/api", "/static", "/login", "/logout", "/register", "/onboarding", "/setup", "/metrics")


def _normalize_path(path: str) -> str:
    """Collapse dynamic path segments to bounded labels so per-id paths and scanner
    traffic can't grow Prometheus label cardinality without limit."""
    if path.startswith("/static/"):
        return "/static/{file}"
    # /api/services/{slug}[/action], /api/deploy/{slug}, /api/stop/{slug}, ...
    path = _PATH_SLUG_RE.sub(lambda m: m.group(0).rsplit("/", 1)[0] + "/{slug}", path)
    # /api/workers/{id}[/...]
    path = _WORKER_ID_RE.sub(r"\1/{id}", path)
    # Fold anything outside the app's own route space into one label.
    if path != "/" and not path.startswith(_KNOWN_PREFIXES):
        return "/{other}"
    return path


async def _refresh_gauges() -> None:
    """Update all gauge values from current DB/worker state (cached 30s)."""
    global _last_refresh
    now = time.time()
    if now - _last_refresh < _REFRESH_TTL:
        return
    _last_refresh = now

    import json
    from datetime import UTC, datetime

    from app import database, exchange_rates

    m = _metrics

    # -- Containers & Workers --
    m["containers_total"].clear()
    m["container_info"].clear()
    m["container_cpu_percent"].clear()
    m["container_memory_mb"].clear()

    workers = await database.list_workers()
    status_counts: dict[str, int] = {}
    container_counts: dict[tuple[str, str], int] = {}

    for w in workers:
        st = w.get("status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1
        name = w.get("name", "worker")
        last_heartbeat = w.get("last_heartbeat")
        if last_heartbeat:
            try:
                dt = datetime.fromisoformat(last_heartbeat)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                m["worker_last_heartbeat_seconds"].labels(worker=name).set(now - dt.timestamp())
            except (ValueError, TypeError):
                pass

        sys_info = {}
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            sys_info = json.loads(w.get("system_info", "{}"))  # type: ignore[arg-type]
        docker_avail = 1 if sys_info.get("docker_available") else 0
        m["worker_docker_available"].labels(worker=name).set(docker_avail)

        container_count = 0
        if w.get("status") == "online":
            containers = []
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                containers = json.loads(w.get("containers", "[]"))  # type: ignore[arg-type]
            container_count = len(containers)
            for c in containers:
                slug = c.get("slug", "unknown")
                c_status = c.get("status", "unknown")
                m["container_info"].labels(service=slug, node=name, status=c_status).set(1)
                key = (c_status, name)
                container_counts[key] = container_counts.get(key, 0) + 1
                cpu = c.get("cpu_percent", 0)
                mem = c.get("memory_mb", 0)
                if cpu or mem:
                    m["container_cpu_percent"].labels(service=slug, node=name).set(cpu)
                    m["container_memory_mb"].labels(service=slug, node=name).set(mem)
        m["worker_containers_count"].labels(worker=name).set(container_count)

    for (status, node), count in container_counts.items():
        m["containers_total"].labels(status=status, node=node).set(count)

    m["workers_total"].clear()
    for st, count in status_counts.items():
        m["workers_total"].labels(status=st).set(count)

    # -- Earnings --
    summary = await database.get_earnings_summary()
    m["earnings_balance"].clear()
    m["earnings_balance_usd"].clear()
    total_usd = 0.0
    for row in summary:
        platform = row.get("platform", "unknown")
        balance = row.get("balance", 0.0)
        currency = row.get("currency", "USD")
        m["earnings_balance"].labels(platform=platform, currency=currency).set(balance)
        usd_val = exchange_rates.to_usd(balance, currency)
        if usd_val is not None:
            m["earnings_balance_usd"].labels(platform=platform).set(usd_val)
            total_usd += usd_val
    m["earnings_total_usd"].set(total_usd)

    # -- Deployments --
    deployments = await database.get_deployments()
    m["services_deployed_total"].set(len(deployments))

    with contextlib.suppress(Exception):
        from app.catalog import get_services

        if get_services:
            m["services_available_total"].set(len(get_services()))

    # -- Health --
    scores = await database.get_health_scores()
    m["health_score"].clear()
    m["health_uptime_percent"].clear()
    for entry in scores:
        m["health_score"].labels(service=entry["slug"]).set(entry["score"])
        if entry.get("uptime_pct") is not None:
            m["health_uptime_percent"].labels(service=entry["slug"]).set(entry["uptime_pct"])


# ---------------------------------------------------------------------------
# Instrumentation hooks (called from app code)
# ---------------------------------------------------------------------------


def record_collection_start() -> float:
    """Call at the start of a collection run. Returns the start time."""
    return time.time()


def record_collection_end(start_time: float, success: bool, platforms_scraped: int = 0) -> None:
    """Record collection duration and result."""
    if not METRICS_ENABLED or not _metrics:
        return
    duration = time.time() - start_time
    _metrics["collection_duration_seconds"].observe(duration)
    _metrics["collection_runs_total"].labels(result="success" if success else "error").inc()
    if success:
        _metrics["collection_last_success_timestamp"].set(time.time())
    _metrics["collection_platforms_scraped"].set(platforms_scraped)


def record_collection_error(platform: str) -> None:
    """Increment error counter for a platform."""
    if not METRICS_ENABLED or not _metrics:
        return
    _metrics["collection_errors_total"].labels(platform=platform).inc()


def record_container_lifecycle(action: str, service: str) -> None:
    """Record a container lifecycle event (deploy, stop, restart, remove)."""
    if not METRICS_ENABLED or not _metrics:
        return
    _metrics["container_lifecycle_total"].labels(action=action, service=service).inc()


def record_login(success: bool) -> None:
    """Record a login attempt."""
    if not METRICS_ENABLED or not _metrics:
        return
    _metrics["login_attempts_total"].labels(result="success" if success else "failure").inc()


def record_rate_limit() -> None:
    """Record a rate-limited login attempt."""
    if not METRICS_ENABLED or not _metrics:
        return
    _metrics["login_rate_limited_total"].inc()


def record_heartbeat(worker: str) -> None:
    """Record a heartbeat received from a worker."""
    if not METRICS_ENABLED or not _metrics:
        return
    _metrics["heartbeats_total"].labels(worker=worker).inc()
