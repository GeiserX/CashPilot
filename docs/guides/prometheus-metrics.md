# Prometheus Metrics

CashPilot exposes rich Prometheus metrics when enabled, allowing you to monitor your passive income fleet with Grafana, Alertmanager, or any Prometheus-compatible tool.

## Enabling Metrics

Set the environment variable on the UI container:

```yaml
environment:
  CASHPILOT_METRICS_ENABLED: "true"
```

Metrics are exposed at `GET /metrics` (unauthenticated, per Prometheus convention).

> **Security:** The `/metrics` endpoint exposes operational data (earnings balances, worker hostnames, container status). Keep it accessible only from trusted networks (LAN, Tailscale, VPN) or protect it behind a reverse proxy with IP allowlist/authentication.

## Scrape Configuration

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: cashpilot
    scrape_interval: 60s
    static_configs:
      - targets: ["cashpilot-ui:8080"]
```

## Available Metrics

### System

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_uptime_seconds` | Gauge | -- | Seconds since CashPilot process started |
| `cashpilot_info` | Info | `version`, `title` | Build information |

### HTTP

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_http_requests_total` | Counter | `method`, `path`, `status` | Total HTTP requests |
| `cashpilot_http_request_duration_seconds` | Histogram | `method`, `path` | Request latency (buckets: 5ms to 10s) |
| `cashpilot_http_requests_in_progress` | Gauge | `method` | Currently active requests |

### Containers

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_containers_total` | Gauge | `status`, `node` | Container count by status and worker node |
| `cashpilot_container_info` | Gauge | `service`, `node`, `status`, `image` | Container presence (1 = exists) |
| `cashpilot_container_cpu_percent` | Gauge | `service`, `node` | CPU usage per container |
| `cashpilot_container_memory_mb` | Gauge | `service`, `node` | Memory usage in MB per container |
| `cashpilot_container_lifecycle_total` | Counter | `action`, `service` | Lifecycle events (deploy/stop/restart/remove) |

### Earnings

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_earnings_balance` | Gauge | `platform`, `currency` | Latest balance per platform (native currency) |
| `cashpilot_earnings_balance_usd` | Gauge | `platform` | Latest balance per platform (USD) |
| `cashpilot_earnings_total_usd` | Gauge | -- | Sum of all platform balances in USD |

### Collection

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_collection_runs_total` | Counter | `result` | Collection runs (success/error) |
| `cashpilot_collection_duration_seconds` | Histogram | -- | Duration of collection runs (buckets: 1s to 5min) |
| `cashpilot_collection_errors_total` | Counter | `platform` | Per-platform collection errors |
| `cashpilot_collection_last_success_timestamp` | Gauge | -- | Unix timestamp of last successful run |
| `cashpilot_collection_platforms_scraped` | Gauge | -- | Platforms successfully scraped in last run |

### Workers

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_workers_total` | Gauge | `status` | Workers by status (online/offline) |
| `cashpilot_worker_last_heartbeat_seconds` | Gauge | `worker` | Seconds since last heartbeat |
| `cashpilot_worker_docker_available` | Gauge | `worker` | Docker availability (1=yes, 0=no) |
| `cashpilot_worker_containers_count` | Gauge | `worker` | Number of containers per worker |
| `cashpilot_heartbeats_total` | Counter | `worker` | Total heartbeats received |

### Health

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_health_score` | Gauge | `service` | Health score per service (0-100) |
| `cashpilot_health_uptime_percent` | Gauge | `service` | Uptime percentage over last 7 days |
| `cashpilot_services_deployed_total` | Gauge | -- | Number of deployed services |
| `cashpilot_services_available_total` | Gauge | -- | Number of services in catalog |

### Auth

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cashpilot_login_attempts_total` | Counter | `result` | Login attempts (success/failure) |
| `cashpilot_login_rate_limited_total` | Counter | -- | Rate-limited login attempts |

## Example Alerts

```yaml
groups:
  - name: cashpilot
    rules:
      - alert: WorkerOffline
        expr: cashpilot_worker_last_heartbeat_seconds > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Worker {{ $labels.worker }} has not sent a heartbeat in 5+ minutes"

      - alert: CollectionFailing
        expr: increase(cashpilot_collection_runs_total{result="error"}[1h]) > 3
        labels:
          severity: warning
        annotations:
          summary: "Earnings collection has failed 3+ times in the last hour"

      - alert: ServiceDown
        expr: cashpilot_health_score < 50
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Service {{ $labels.service }} health score below 50"

      - alert: EarningsStale
        expr: time() - cashpilot_collection_last_success_timestamp > 7200
        labels:
          severity: warning
        annotations:
          summary: "No successful earnings collection in 2+ hours"

      # THE ONE THAT WATCHES THE WATCHER. Every alert above is computed FROM
      # CashPilot's own metrics, so if CashPilot itself stops, none of them
      # fire -- there is simply no data, and silence reads exactly like health.
      # This is the only rule here that survives the thing it monitors dying.
      - alert: CashPilotDown
        expr: up{job="cashpilot"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Prometheus cannot scrape CashPilot — every other CashPilot alert is now blind"
```

## The container can be "up" and failing

Both images declare a `HEALTHCHECK`, so Docker knows whether the app inside is
actually answering:

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
# cashpilot-ui   Up 2 hours (unhealthy)
```

**Nothing acts on that by default, and that surprises people.**
`restart: unless-stopped` restarts a container that *exits*. A container that
stays running while failing its own healthcheck is not exiting, so it is never
restarted — it sits there, `unhealthy`, indefinitely. (Docker **Swarm** does
reschedule unhealthy tasks; plain Docker and Compose do not.)

Three ways to close that, in increasing order of effort:

**1. Alert on it.** If you already run Prometheus, the `CashPilotDown` rule
above covers the case that matters: a failing healthcheck almost always means
the HTTP endpoint stopped answering, which is the same thing a failed scrape
detects.

**2. Restart it automatically.** A small sidecar watches the Docker socket and
restarts anything that goes unhealthy:

```yaml
  autoheal:
    image: willfarrell/autoheal:1.2.0
    restart: unless-stopped
    environment:
      - AUTOHEAL_CONTAINER_LABEL=autoheal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

Then label the containers you want it to manage with `autoheal: "true"`.

!!! warning "This sidecar holds the Docker socket"

    The socket is root on the host. You are trading one risk for another, and
    on a single-user home server that is usually a reasonable trade — but make
    it deliberately, not by copy-paste. If you would not give a third-party
    image root, alert instead of autohealing.

**3. Watch it by hand.** `docker ps` shows the health state, and it costs
nothing to look at after an upgrade.

## Grafana Dashboard

Import a basic dashboard by querying these panels:

- **Total Earnings (USD):** `cashpilot_earnings_total_usd`
- **Per-Platform Earnings:** `cashpilot_earnings_balance_usd`
- **Container Health Heatmap:** `cashpilot_health_score`
- **Worker Status:** `cashpilot_workers_total`
- **Collection Success Rate:** `rate(cashpilot_collection_runs_total{result="success"}[1h])`
- **HTTP Latency p95:** `histogram_quantile(0.95, rate(cashpilot_http_request_duration_seconds_bucket[5m]))`
