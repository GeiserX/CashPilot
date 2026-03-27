# AGENTS.md - AI Agent Instructions for CashPilot

> **PLAN MODE**: Use Plan Mode frequently! Before implementing complex features, multi-step tasks, or making significant changes, switch to Plan Mode to think through the approach, consider edge cases, and outline the implementation strategy.

> **IMPORTANT**: Do NOT update this file unless the user explicitly says to. Only the user can authorize changes to AGENTS.md.

> **SECURITY WARNING**: This repository is PUBLIC at [github.com/GeiserX/CashPilot](https://github.com/GeiserX/CashPilot). **NEVER commit secrets, API keys, passwords, tokens, or any sensitive data.** Referral codes are NOT secrets (they are public affiliate links). All actual secrets must be stored in:
> - GitHub Secrets (for CI/CD)
> - Environment variables at deploy time
> - Local `.env` files (gitignored)

---

## Project Overview

**CashPilot** is a self-hosted passive income orchestrator. Deploy once, manage everything from a single web dashboard. It deploys, monitors, and manages Docker containers for bandwidth-sharing, DePIN, storage, and GPU compute services. Think of it as Portainer meets a passive-income aggregator.

- **Repository**: https://github.com/GeiserX/CashPilot
- **Docker Images**: `drumsergio/cashpilot` (UI) and `drumsergio/cashpilot-worker` on Docker Hub
- **License**: GPL-3.0

### What Makes This Different

No existing project combines all of these:
1. Browser-based setup wizard (no CLI needed)
2. One-click container deployment for 25+ services
3. Real-time earnings dashboard with historical tracking
4. Container health monitoring (CPU, memory, network)
5. YAML-driven service catalog (single source of truth)

### Competitors

| Project | GitHub | Stars | Last Active | Services | What It Does | What It Lacks |
|---------|--------|:-----:|:-----------:|:--------:|-------------|---------------|
| [money4band](https://github.com/MRColorR/money4band) | MRColorR | 380 | Mar 2026 | 20 | CLI wizard generating docker-compose. Recently added basic web monitoring dashboard. Multi-proxy support, auto-updater, pre-built binaries. | Web dashboard is monitoring-only, no guided signup, no earnings aggregation, no one-click deploy from browser. |
| [CashFactory](https://github.com/OlivierGaland/CashFactory) | OlivierGaland | 394 | Apr 2025 | 11 | Docker compose template with bookmark page (uhttpd) + bundled Portainer. Setup script. | "Web UI" is just bookmark links to external dashboards. No earnings tracking. x86 only. Slowing down. |
| [InternetIncome](https://github.com/engageub/InternetIncome) | engageub | 219 | Mar 2026 | 27+ | Bash script for multi-proxy scaling. Largest service breadth. Core feature: multi-IP/multi-VPN operation. | No web UI. No earnings dashboard. No compose file. Pure bash. |
| [income-generator](https://github.com/XternA/income-generator) | XternA | 193 | Mar 2026 | 25 | Polished CLI tool (`igm` command). Auto-claim daily rewards, dynamic resource limits, encrypted creds. | Terminal-only, no web dashboard, no earnings aggregation, no guided setup. |
| [home-assistant-passive-income](https://github.com/bvlinsky/home-assistant-passive-income) | bvlinsky | 93 | Mar 2026 | 10 | Home Assistant add-ons for passive income services. | HA-only deployment. No standalone UI. Limited services. |
| [EarnApp-Docker](https://github.com/fazalfarhan01/earnapp-docker) | fazalfarhan01 | 45 | Apr 2022 | 1 | Single-service Docker wrapper for EarnApp. | Dead (4 years). Only one service. |

**CashPilot's differentiation:** Web-based setup wizard, one-click deployment from browser, earnings dashboard with historical charts, container health monitoring, YAML-driven extensible catalog. No other project has a web UI that guides users from signup through deployment and monitoring.

### Services in Competitors Missing from CashPilot

| Service | Found In | Category | Notes |
|---------|----------|----------|-------|
| ProxyBase | money4band, income-generator, InternetIncome | Bandwidth | Crypto payout |
| PacketShare | money4band | Bandwidth | Bandwidth sharing |
| WizardGain | income-generator, InternetIncome | Bandwidth | Crypto payout |
| AntGain | income-generator, InternetIncome | Bandwidth | Unlimited devices |
| Spide | income-generator | Bandwidth | Bandwidth sharing |
| Ebesucher | InternetIncome | Bandwidth | Traffic exchange/surfbar |
| URnetwork | InternetIncome | Bandwidth | VPN/bandwidth |
| Adnade | InternetIncome | Bandwidth | Ad-based earning |
| Uprock | InternetIncome | DePIN | Crypto, internet sharing |
| PassiveApp | InternetIncome, income-generator | DePIN | Crypto/PayPal |
| Bytebenefit | InternetIncome, income-generator | Bandwidth | PayPal/Stripe |
| Bytelixir | InternetIncome, income-generator | Bandwidth | Bandwidth |

---

## Owner Context

**Operator**: Sergio Fernandez Rubio
**Trade Name**: GeiserCloud
**GitHub**: GeiserX

### Communication Style
- Be direct and efficient -- don't over-explain
- Do the work, don't ask permission for clear tasks
- Wait for explicit deploy instruction -- do NOT push or deploy until told
- Use exact values when provided

### Preferences
- Clean, readable code without over-engineering
- Self-hosted solutions over SaaS
- GitOps with Portainer for infrastructure
- Docker Hub for images (`drumsergio/cashpilot`)
- Do NOT add `Co-Authored-By` lines to commits
- Do NOT add "Generated with Claude Code" attribution anywhere
- **Never modify CLAUDE.md files** -- use hooks or memory instead
- Always commit as GeiserX (`--author="GeiserX <9169332+GeiserX@users.noreply.github.com>"`)

---

## Tech Stack

| Technology | Purpose |
|---|---|
| FastAPI | Backend framework (Python 3.12, async) |
| Jinja2 | Server-rendered HTML templates |
| SQLite | Database (aiosqlite, zero-config, stored in `/data`) |
| Docker SDK for Python | Container lifecycle management via socket |
| PyYAML | Service definition parsing |
| APScheduler | Periodic earnings collection |
| httpx | Async HTTP client for earnings collectors |
| cryptography (Fernet) | At-rest encryption for stored credentials |
| Chart.js | Frontend earnings charts |
| tini | PID 1 init (Dockerfile) |

---

## Architecture

### Directory Structure

```
cashpilot/
  app/                  # FastAPI application
    main.py             # App entrypoint, lifespan, mode routing (standalone/ui/worker)
    catalog.py          # Loads YAML service definitions, caches, SIGHUP reload
    orchestrator.py     # Docker SDK: deploy, stop, restart, remove, logs
    database.py         # Async SQLite: earnings, config, deployments, workers tables
    worker_api.py       # Worker REST API: heartbeat, container commands, mini-UI
    ui_api.py           # UI API: worker registration, fleet view, earnings
    collectors/         # Earnings collectors (one module per service, UI/standalone only)
      base.py           # BaseCollector ABC + EarningsResult dataclass
      honeygain.py      # Honeygain JWT auth + /v2/earnings
      __init__.py       # COLLECTOR_MAP registry + make_collectors() factory
    templates/          # Jinja2: base, dashboard, setup (4-step wizard), catalog, settings, service_detail
    static/
      css/style.css     # Dark theme (#0f1117 bg, #1a1d26 cards, #3b82f6 accent)
      js/app.js         # Vanilla JS, CP namespace, Chart.js, wizard state machine
  services/             # YAML service definitions (SINGLE SOURCE OF TRUTH)
    _schema.yml         # Schema documentation
    bandwidth/          # 12 services (honeygain, iproyal, earnapp, etc.)
    depin/              # 10 services (grass, gradient, teneo, etc.)
    storage/            # 1 service (storj)
    compute/            # 4 services (vast-ai, salad, nosana, golem)
  docs/guides/          # Auto-generated per-service setup guides
  scripts/
    generate_docs.py    # YAML -> README table + guide pages
  Dockerfile            # UI image: multi-stage python:3.12-slim, tini, non-root
  Dockerfile.worker     # Worker image: minimal deps, no collectors/templates
  docker-compose.yml    # Standalone deployment (UI + embedded worker)
  docker-compose.fleet.yml  # Multi-server example (UI + remote workers)
  .github/workflows/
    build.yml           # QEMU + Buildx multi-arch, Docker Hub push
```

### Key Design Decisions

- **YAML is the source of truth.** Every service lives in `services/{category}/{slug}.yml`. The web UI, container deployment, earnings collection, and documentation ALL derive from these files. Never hardcode service-specific logic in `app/`.
- **Container naming:** All managed containers are `cashpilot-{slug}` with labels `cashpilot.managed=true` and `cashpilot.service={slug}`.
- **Data directory:** `/data` volume holds SQLite DB and persistent config. Never write outside `/data` at runtime.
- **Credentials:** Encrypted at rest via `CASHPILOT_SECRET_KEY` (Fernet). The key is auto-generated if not provided.
- **README table is auto-generated.** Markers: `<!-- SERVICES_TABLE_START -->` / `<!-- SERVICES_TABLE_END -->`. Run `python scripts/generate_docs.py` to regenerate. **Never edit the table directly.**

---

## Architecture: CashPilot UI + CashPilot Worker

CashPilot is split into two components that can run together (default) or separately across multiple servers. This is a core differentiator -- no competitor does multi-server fleet management.

### Components

| Component | Description |
|-----------|-------------|
| **CashPilot UI** | The single web dashboard. Collects all earnings centrally, shows global fleet view, manages workers. Only ONE UI instance exists -- deploying a second is rejected if workers are already connected to another. |
| **CashPilot Worker** | Lightweight agent running on each server. Manages local containers (deploy/stop/restart/health). Reports status to the UI. Has a minimal config page (connection status, running services). Configured via env vars. |

Two separate Docker images to minimize worker footprint:
- **`drumsergio/cashpilot`** — Full UI image (~90 MB): FastAPI, Jinja2, templates, static assets, collectors, APScheduler, Docker SDK.
- **`drumsergio/cashpilot-worker`** — Lightweight worker image (~40 MB): FastAPI (minimal), Docker SDK, heartbeat timer, tiny config page. No collectors, no templates, no Chart.js.

The UI image in `standalone` mode (default) includes an embedded worker — no need to run both images on the same server.

### Core Principles

1. **Single source of truth.** The UI instance is the only one that collects earnings, stores historical data, and serves the dashboard. Workers never collect earnings -- they only manage containers and report health.
2. **Earnings are never duplicated.** Since only the UI collects, there is no risk of the same Honeygain account being counted twice across servers. The UI queries each service API once and gets the global balance.
3. **Workers are stateless satellites.** A worker knows: (a) which containers to keep running, (b) the UI URL to report to. It has a tiny local SQLite for config persistence but no earnings data.
4. **Default must work perfectly.** A single `docker-compose.yml` with no extra config deploys UI + Worker on the same server. Multi-server is opt-in.
5. **Drill-down per server and per service.** The UI shows global totals by default. Users can drill down to see which containers run on which server, container health per server, and service-level details.

### Deployment Modes

```
┌─────────────────────────────────────────────┐
│  Mode: standalone (default)                 │
│  One server, one container                  │
│  UI + Worker combined, Docker socket mounted│
│  No federation config needed                │
└─────────────────────────────────────────────┘

┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Server A (UI)   │     │  Server B        │     │  Server C        │
│  CashPilot UI    │◄────│  CashPilot Worker│     │  CashPilot Worker│
│  + local Worker  │◄────│  Reports health  │     │  Reports health  │
│  Collects all    │     │  Manages local   │     │  Manages local   │
│  earnings        │     │  containers      │     │  containers      │
│  Port 8080 (UI)  │     │  Port 8081 (cfg) │     │  Port 8081 (cfg) │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Authentication

- A single shared **API key** authenticates all workers to the UI.
- Set once in the UI, provided to each worker via `CASHPILOT_API_KEY` env var.
- Workers also need `CASHPILOT_UI_URL` pointing to the UI's address.

### Worker Environment Variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `CASHPILOT_MODE` | No | `standalone` | `standalone`, `ui`, or `worker` |
| `CASHPILOT_UI_URL` | Worker only | -- | URL of the CashPilot UI (e.g. `http://192.168.10.100:8080`) |
| `CASHPILOT_API_KEY` | Worker only | -- | Shared API key for worker→UI auth |
| `CASHPILOT_WORKER_NAME` | No | hostname | Human-readable name for this worker in the UI |

### Worker Capabilities

- **With Docker socket** (default): Full container lifecycle -- deploy, stop, restart, remove, health checks, logs, resource stats.
- **Without Docker socket**: Read-only monitoring. Can check if expected containers exist and are running via `docker ps` equivalent. Cannot manage containers. Useful for locked-down environments.

### Worker Mini-UI

Each worker exposes a minimal web page on port 8081 showing:
- Connection status (connected to UI at `X`, last heartbeat `Y` ago)
- List of local containers managed by CashPilot (name, status, uptime)
- Worker name and version
- No earnings data, no charts, no service catalog -- that's all in the UI.

### Data Flow

1. **Worker → UI (heartbeat):** Every 60s, each worker sends: container list, health status, resource usage (CPU/mem/net per container). The UI stores this in its DB.
2. **UI → Worker (commands):** The UI can instruct a worker to deploy, stop, restart, or remove a container. Commands are sent via REST API calls to the worker.
3. **UI earnings collection:** The scheduler in the UI runs collectors for all configured services. Results go into the UI's SQLite DB. Workers are not involved in earnings.
4. **Offline handling:** If a worker goes offline, the UI shows "last seen X ago" for that server's containers. Historical data is retained. The worker reconnects automatically when back online.

### Credential Flow (Option C — Docker-native)

The worker **never handles or stores credentials**. The flow:

1. User configures service credentials in the UI (stored encrypted in UI's SQLite).
2. When UI tells a worker to deploy a container, it sends the full container spec (image, env vars, volumes, ports) in the API call.
3. The worker passes this spec to the Docker API to create the container. Docker stores the env vars in the container config.
4. For container restarts: `docker restart` preserves env vars natively — no credential re-send needed.
5. For full redeploys (remove + create): the UI resends the full spec.

This is how Portainer works. The worker is a dumb executor — it never decrypts, stores, or inspects credentials.

### Dashboard UI Features

- **Expandable instance rows**: Services with multiple instances (multi-node) show an expand chevron. Clicking reveals sub-rows with per-instance status, CPU/memory, and action buttons (restart/stop/logs). Local instance is always listed first.
- **Per-instance actions**: Sub-row action buttons target the correct node. Local containers use the orchestrator directly. Worker containers proxy via `?worker_id=X` query parameter to `_proxy_worker_command()` / `_proxy_worker_logs()`.
- **Greyed-out actions**: If a worker doesn't have Docker socket access (`system_info.docker_available == false`), its action buttons are disabled.
- **CPU/Memory averaging**: Multi-instance services show average CPU/memory in the main row (prefixed with `~`), individual values in sub-rows.
- **Notification bell**: Always visible in topbar. Polls `/api/collector-alerts` every 60s. Shows red badge with count when collectors fail. Clicking an alert navigates to Settings and highlights the relevant collector section.
- **External services**: Services deployed outside Docker (Grass, Bytelixir on Android) appear with "External" badge. No container actions, no CPU/memory.

### What NOT to Build Yet

- Auto-discovery (mDNS, Tailscale API) -- workers are manually configured via env vars.
- Worker-to-worker communication -- workers only talk to the UI.
- Multi-UI failover -- there is exactly one UI instance.
- Android service worker -- for tracking Grass/Bytelixir running on Android (future roadmap).

---

## CI/CD

### `build.yml` -- Docker Build & Push

**Triggers:** Push to `main` or version tags (`v*`)

**What it does:**
1. Builds multi-arch image (linux/amd64 + linux/arm64) via QEMU + Buildx
2. Pushes to Docker Hub as `drumsergio/cashpilot` (UI) and `drumsergio/cashpilot-worker`
3. Tags: `latest` on main, semver on tags (`v1.0.0` -> `1.0.0` + `1.0`)
4. Layer caching via GitHub Actions cache

**Required GitHub Secrets:**
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

---

## Service Status & Known Issues

### Broken / Non-Functional Services

| Service | Status | Issue | Notes |
|---------|--------|-------|-------|
| **SpeedShare** | `broken` | API at `api.speedshare.app` returns Telegraf metrics exporter output instead of JSON | Landing page loads but login/dashboard/earnings all broken. Service appears abandoned (last build Feb 2024). |
| **Network3** | `broken` | Service appears non-functional | Marked broken in YAML. |
| **Peer2Profit** | `dead` | Registrations closed. Only via Telegram bot `peer2profit_app_bot` which is not accepting new users. | YAML removed. |
| **GagaNode** | `dead` | Support Telegram inactive 4+ months. Dashboard barely functional. | YAML changed to dead. |
| **Titan Network** | `dead` | Rebranded to proxytitan.com. Business-only, no consumer signups. | YAML changed to dead. |
| **Dawn Internet** | `broken` | Chrome extension not working as of Mar 2025. | YAML changed to broken. |

### Services Without Docker Support (Extension/App Only)

| Service | Type | Docker Feasibility | Notes |
|---------|------|-------------------|-------|
| **Grass** | Browser extension | No official image | Community Python bots exist but not containerized |
| **Gradient** | Browser extension (Next.js) | No official image | Client-side JS reads `?referralCode=` param (camelCase, NOT `?code=`) |
| **Teneo** | Browser extension | No official image | Websocket-based connection |
| **Dawn** | Chrome extension / hardware box | Community Python bots exist (`Justi1980/Dawn-Validator-BOT`, `Jaammerr/The-Dawn-Bot`) that call Dawn's HTTP API directly, no browser needed. Trivially containerizable. |
| **Nodepay** | Browser extension | No official image | Behind Cloudflare protection |
| **BlockMesh** | Browser extension | No official image | -- |
| **Wipter** | Desktop/mobile app only | No Docker or API | Web registration at `/en/register` (accepts referral code), but **no web login/dashboard** -- `/login`, `/en/login`, `/dashboard`, `app.wipter.com` all 404/refused. Earnings visible only in desktop app. |
| **GagaNode** | Desktop app | No official Docker image | -- |
| **Titan** | Desktop app | No official Docker image | -- |
| **Golem** | Provider node | Complex setup, not containerized via CashPilot | -- |
| **Nosana** | Solana-based | Requires Solana wallet + GPU | -- |
| **Salad** | Desktop app | Requires GPU passthrough | -- |
| **Vast.ai** | Provider dashboard | Requires GPU passthrough | -- |

### Referral Program Status

| Service | Has Referral? | Code Set? | Notes |
|---------|:------------:|:---------:|-------|
| Honeygain | Yes | SERGIB4014 | 25% lifetime |
| IPRoyal Pawns | Yes | 19266874 | 10% lifetime |
| ProxyLite | Yes | KMUPRZIZ | 15% lifetime |
| Traffmonetizer | Yes | 2111758 | 10% lifetime + $5 signup |
| EarnApp | Yes | TSMD9wSm | 10% lifetime |
| PacketStream | Yes | 7xgZ | $0.10/GB from referrals |
| Earn.fm | Yes | GEISYB91 | Percentage-based |
| ProxyRack | Yes | Set | Percentage-based |
| MystNodes | Yes | Set | 5% bonus |
| Grass | Yes | kn8FNEPnUr2tMqE | 20% of points |
| Gradient | Yes | YSKMY7 | Bonus points. URL param: `?referralCode=` |
| Teneo | Yes | CAqef | 2000 pts per referral |
| Nodepay | Yes | 0wzzyznen64j9zx | Bonus points |
| **Repocket** | **No** | -- | No public referral program. `repocket.co` 301s to `repocket.com`. `/refer-a-friend` returns 404. |
| **SpeedShare** | Unknown | -- | Dashboard broken, can't verify |
| Bitping | **No** | -- | No referral program exists |
| ~~Peer2Profit~~ | **Removed** | -- | Dead. Registrations closed, only via Telegram bot `peer2profit_app_bot` which is not accepting new users. |
| Wipter | Yes | Not set | 10% + $5 signup. Code only visible in desktop app. |
| Storj | No | -- | No referral program for node operators |
| BlockMesh | **No** | -- | No referral program exists |
| Dawn | Yes | Not set | Chrome extension broken as of Mar 2025. Code from dashboard/extension when working. |
| ~~GagaNode~~ | **Removed** | -- | Dead. Support Telegram inactive 4+ months. Dashboard barely functional. |
| ~~Titan~~ | **Removed** | -- | Business-only (proxytitan.com). No consumer/user signups. Not a passive income service. |

### Collector Implementation Status

Working collectors (12/12 deployed services):
- **Honeygain** -- JWT auth, `/v1/users/tokens` + `/v1/users/balances`
- **EarnApp** -- XSRF rotation + cookie auth, `/money` endpoint
- **MystNodes** -- Cloud API (`my.mystnodes.com/api/v2`), email/password auth. **Supports per-node earnings** via `GET /api/v2/node` (30-day MYST per node, need price conversion for USD).
- **Traffmonetizer** -- JWT token, `data.traffmonetizer.com/api/app_user/get_balance`
- **IPRoyal** -- Email/password auth
- **Repocket** -- Firebase auth (Google Identity Toolkit)
- **Bitping** -- JWT cookie auth, `/api/v2/payouts/earnings`. No per-device API.
- **Earn.fm** -- Supabase auth, `/v2/harvester/view_balance`
- **PacketStream** -- Manual JWT cookie, HTML scraping `window.userData`
- **ProxyRack** -- API key auth, POST `/api/balance`. Per-device bandwidth (not earnings) via POST `/api/bandwidth` with `device_id` param.
- **Storj** -- API URL-based
- **Grass** -- Bearer token from localStorage (`app.grass.io`), `api.getgrass.io`. Returns points, not USD.
- **Bytelixir** -- Laravel session cookie (expires ~3.5h), `dash.bytelixir.com`. hCaptcha blocks automated login.

#### Per-Node/Per-Device Earnings Support

Only MystNodes has a real per-node earnings API. Research on all 12 services:

| Service | Per-Device Earnings | Notes |
|---------|:------------------:|-------|
| MystNodes | **Yes** | `GET /api/v2/node` returns per-node 30d MYST earnings. Implemented in `mystnodes.py:get_per_node_earnings()` |
| ProxyRack | Bandwidth only | `POST /api/bandwidth` with `device_id` returns daily GB. No per-device USD. |
| Bitping | No | No per-device REST API. gRPC only internally. |
| Traffmonetizer | Unconfirmed | May have device stats endpoint, not documented. |
| All others | No | Account-level balance only. |

### API/Dashboard Access Gotchas

| Service | Issue |
|---------|-------|
| **PacketStream** | CAPTCHA blocks automated login. Need manual JWT from browser session for API access. |
| **ProxyRack** | Dashboard behind Cloudflare. Need API key from browser. Device UUIDs must be manually registered in `peer.proxyrack.com` dashboard. |
| **SpeedShare** | API domain (`api.speedshare.app`) misconfigured -- returns Telegraf metrics exporter output. Service non-functional. |
| **Nodepay** | Behind Cloudflare protection. API access requires browser session cookies. |
| **Grass** | Token must be extracted from browser localStorage at `app.grass.io`. Returns points (GRASS_POINTS), not USD. |
| **Bytelixir** | Laravel session cookie expires ~3.5h. hCaptcha blocks automated login. Must manually extract cookie from browser. Most session-fragile service. |

---

## Deployment

### Docker Compose (recommended)

```yaml
services:
  cashpilot:
    image: drumsergio/cashpilot:latest
    container_name: cashpilot
    ports:
      - "8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - cashpilot_data:/data
    environment:
      - TZ=Europe/Madrid
      - CASHPILOT_SECRET_KEY=<generate-a-random-secret>
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true

volumes:
  cashpilot_data:
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone |
| `CASHPILOT_MODE` | `standalone` | `standalone` (UI+Worker), `ui` (UI only), or `worker` (Worker only) |
| `CASHPILOT_SECRET_KEY` | Auto-generated | Fernet encryption key for credentials (UI/standalone only) |
| `CASHPILOT_COLLECTION_INTERVAL` | `3600` | Seconds between earnings collection (UI/standalone only) |
| `CASHPILOT_PORT` | `8080` | Web UI port (UI/standalone) or mini-UI port (worker, default 8081) |
| `CASHPILOT_UI_URL` | -- | URL of UI instance (worker mode only, required) |
| `CASHPILOT_API_KEY` | -- | Shared API key for worker↔UI auth (required in multi-server) |
| `CASHPILOT_WORKER_NAME` | hostname | Human-readable worker name shown in UI fleet view |

### Current Deployment

3-server fleet: 1 UI instance + 2 workers. Workers send heartbeats to UI every 60s.
Fleet API key set via `CASHPILOT_API_KEY` env var on all instances.

### Performance & Deployment Learnings

- **`container.stats(stream=False)` is slow** (~1-2s per container). Never call in request path. Use `get_status_cached()` for page loads; background health check refreshes every 5 min.
- **`--read-only` breaks Docker socket access**: The entrypoint needs to modify `/etc/group` to add the `cashpilot` user to the Docker socket's group. Drop `--read-only` or add tmpfs for `/etc`.
- **Cross-subnet workers**: If worker and UI are on different subnets, use a VPN/overlay IP (e.g. Tailscale MagicDNS) for `CASHPILOT_UI_URL`. Worker may need `--network host` for VPN routing.
- **SQLite data retention**: 400-day retention. Daily job purges `earnings` and `health_events` older than 400 days.
- **Collection interval**: 1 hour. Earnings cache in SQLite, served instantly.
- **Docker availability check caches result**: If startup races and returns False, the cache stays False. Fixed by warming cache in background on startup via `run_in_executor`.
- **Cache mutation bug**: `orchestrator.get_status_cached()` returns a reference to the module-level `_status_cache` list. Always copy with `list()` before appending worker containers, or the cache grows infinitely.
- **Health check deduplication**: When a service runs on multiple nodes, record only one health event per slug per check cycle (best status wins: running > restarting > exited). Without this, multi-instance services get penalised with duplicate `check_down` events.
- **Google Fonts render-blocking**: Use async preload pattern (`<link rel="preload" as="style" onload="this.rel='stylesheet'">`) to avoid blocking page render.
- **First earnings collection baseline**: When a service is first onboarded, insert a synthetic baseline record for the prior day with the same balance, so the first delta is 0 (not the full cumulative balance).

### Service-Specific Deployment Notes

#### MystNodes / Mysterium
- **MMN API key is critical**: The Mysterium container must have `MYSTNODES_API_KEY` env var or `[mmn] api-key` in `config-mainnet.toml` to link the node to the user's MystNodes cloud account.
- **Node identity is per-volume**: The Mysterium keystore lives in the Docker volume (`mysterium-data:/var/lib/mysterium-node/keystore/`). Deleting the volume or creating a new container without the same volume generates a NEW blockchain identity.
- **Registration is blockchain-based**: New identities must be registered on Polygon. This is triggered by Hermes and requires the MMN API key. If Hermes returns "internal error", it's a temporary server-side issue.
- **Per-node earnings**: The MystNodes cloud API (`GET /api/v2/node?page=1&itemsPerPage=100`) returns per-node 30-day earnings in MYST. The `earningsTotal` endpoint returns pre-converted USD total.
- **Image name**: `mysteriumnetwork/myst` (NOT `mysteriumnet/myst`).

---

## Development

### Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Docker socket must be accessible for container management.

### Adding a New Service

1. Create `services/{category}/{slug}.yml` following `_schema.yml`
2. **Include a `cashout` section** in the YAML — every service must define how users can cash out (API endpoint, redirect URL, or manual instructions). This is mandatory, not optional.
3. Run `python scripts/generate_docs.py` to regenerate README + guides
4. Optionally add a collector in `app/collectors/{slug}.py` and register it in `__init__.py`
5. Submit a PR (one service per PR)

### Documentation Generation

```bash
python scripts/generate_docs.py
```

Reads all YAMLs from `services/`, generates:
- README.md service table (between `<!-- SERVICES_TABLE_START -->` / `<!-- SERVICES_TABLE_END -->` markers)
- `docs/guides/{slug}.md` for each service
- `docs/guides/README.md` index

---

## Contribution Rules

- One PR per feature or fix. Do not bundle unrelated changes.
- Service YAMLs must follow `services/_schema.yml`. Missing required fields will fail CI.
- **Never edit the service table in README.md directly.** It is auto-generated.
- Never hardcode service-specific logic in `app/`; it belongs in the YAML or the collector.
- Keep the Docker image small (target under 100 MB). No dev dependencies in the final stage.
- All Python code must pass linting (`ruff`) with no errors.

---

## Agent Checklist

Before completing any task, verify:

- [ ] Service YAMLs follow `_schema.yml` structure
- [ ] `python scripts/generate_docs.py` runs without errors after YAML changes
- [ ] README table matches YAML content (auto-generated, not hand-edited)
- [ ] No secrets committed (referral codes are OK, credentials are NOT)
- [ ] Commit author is GeiserX (`--author="GeiserX <9169332+GeiserX@users.noreply.github.com>"`)
- [ ] No `Co-Authored-By` lines in commit messages
- [ ] After pushing, wait for all GitHub Actions runs to pass (`gh run watch`) before considering the task done
