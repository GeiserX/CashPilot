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

**Operator**: Sergio Fernandez
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
    main.py             # App entrypoint, lifespan, UI routes (no Docker dependency)
    catalog.py          # Loads YAML service definitions, caches, SIGHUP reload
    orchestrator.py     # Docker SDK: deploy, stop, restart, remove, logs
    database.py         # Async SQLite: earnings, config, deployments, workers tables
    worker_api.py       # Worker REST API: heartbeat, container commands, mini-UI
    ui_api.py           # UI API: worker registration, fleet view, earnings
    collectors/         # Earnings collectors (one module per service, UI only)
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
  docker-compose.yml    # Example deployment (UI + worker on same server)
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

CashPilot is split into two **always-separate** components. The UI never touches Docker — all container operations go through workers. This is a core differentiator -- no competitor does multi-server fleet management.

### Components

| Component | Description |
|-----------|-------------|
| **CashPilot UI** | The single web dashboard. Collects all earnings centrally, shows global fleet view, manages workers. **Has NO Docker socket.** Can be hosted anywhere. Only ONE UI instance exists. |
| **CashPilot Worker** | Agent running on each server that has Docker. **Must have Docker socket access** (by design, never non-privileged). Manages local containers, reports status to UI via heartbeats. Has a minimal config page. |

Two separate Docker images:
- **`drumsergio/cashpilot`** — UI image: FastAPI, Jinja2, templates, static assets, collectors, APScheduler. **No Docker SDK.**
- **`drumsergio/cashpilot-worker`** — Worker image: FastAPI (minimal), Docker SDK, heartbeat timer, tiny config page. No collectors, no templates.

**There is no standalone mode.** Every server that runs Docker containers needs a worker. The UI is a pure dashboard/scheduler — it can run on any machine, including one without Docker.

### Core Principles

1. **Separation of concerns.** UI handles: dashboard, earnings collection, scheduling, user auth. Workers handle: Docker container lifecycle, health reporting. They never overlap.
2. **Workers must be privileged.** A worker without Docker socket is useless. If you don't need Docker management, just run the UI alone to track earnings.
3. **Single source of truth.** The UI instance is the only one that collects earnings, stores historical data, and serves the dashboard. Workers never collect earnings.
4. **Earnings are never duplicated.** Since only the UI collects, there is no risk of the same account being counted twice.
5. **Workers are stateless satellites.** A worker knows: (a) which containers to keep running, (b) the UI URL to report to. It has a tiny local SQLite for config persistence but no earnings data.
6. **Drill-down per server and per service.** The UI shows global totals by default. Users can drill down to see which containers run on which server.

### Deployment

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Server A        │     │  Server B        │     │  Server C        │
│  CashPilot UI    │◄────│  CashPilot Worker│     │  CashPilot Worker│
│  CashPilot Worker│◄────│  Reports health  │     │  Reports health  │
│  (2 containers)  │     │  Manages local   │     │  Manages local   │
│  Port 8085 (UI)  │     │  containers      │     │  containers      │
│  Port 8081 (wkr) │     │  Port 8081       │     │  Port 8081       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Authentication

- A single shared **API key** authenticates all workers to the UI.
- Set once in the UI, provided to each worker via `CASHPILOT_API_KEY` env var.
- Workers also need `CASHPILOT_UI_URL` pointing to the UI's address.

### Worker Environment Variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `CASHPILOT_UI_URL` | Yes | -- | URL of the CashPilot UI (e.g. `http://192.168.10.100:8085`) |
| `CASHPILOT_API_KEY` | Yes | -- | Shared API key for worker→UI auth |
| `CASHPILOT_WORKER_NAME` | No | hostname | Human-readable name for this worker in the UI |

### Worker Capabilities

Workers **must** have Docker socket access — this is by design. A worker without Docker socket is useless. If you don't need container management on a server, don't deploy a worker there.

Full container lifecycle: deploy, stop, restart, remove, health checks, logs, resource stats.

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

### `release.yml` -- Auto Release

**Triggers:** Push to `main` (paths: `app/`, `services/`, `Dockerfile*`, `requirements*.txt`)

**What it does:**
1. Reads the latest `v*.*.*` tag
2. Auto-increments patch version (e.g. `v0.1.0` → `v0.1.1`)
3. Creates annotated git tag + GitHub Release with auto-generated notes
4. Skips if commit message contains `[skip ci]`

### `build.yml` -- Docker Build & Push

**Triggers:** Version tags (`v*`) — created by `release.yml` or manually

**What it does:**
1. Lints with ruff
2. Builds multi-arch images (linux/amd64 + linux/arm64) via QEMU + Buildx
3. Pushes to Docker Hub as `drumsergio/cashpilot` (UI) and `drumsergio/cashpilot-worker`
4. Tags: `latest` + semver (`v1.0.0` → `1.0.0` + `1.0`)
5. Layer caching via GitHub Actions cache

**Flow:** Push to main → auto-release v0.1.x → tag triggers Docker build → versioned images on Docker Hub.

**Always use tagged images in deployment** (e.g. `drumsergio/cashpilot:0.1.1`), never `:latest`.

**Required GitHub Secrets:**
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

---

## Service Status (Updated 2026-03-27)

### 49 services across 4 categories

| Category | Active | Broken | Dead | Shady | Total |
|----------|--------|--------|------|-------|-------|
| Bandwidth | 14 | 2 | 4 | 0 | 22 |
| DePIN | 8 | 4 | 0 | 2 | 20 |
| Compute | 4 | 1 | 0 | 0 | 6 |
| Storage | 1 | 0 | 0 | 0 | 1 |

### Service Status Table

| Service | Status | Notes |
|---------|--------|-------|
| SpeedShare | **dead** | Confirmed dead in Discord (Mar 2026) |
| PacketShare | **dead** | Site refuses connections |
| Peer2Profit | **dead** | Both domains refuse connections |
| Network3 | **broken** | Up but no SSL, no updates in months |
| WizardGain | **broken** | Under maintenance |
| Dawn Internet | **broken** | Extension works but half-baked. Black Box hardware announced |
| Wipter | **broken** | SSL failing |
| Koii Network | **broken** | Website returns HTTP 402 (paused) |
| earn.cc | **broken** | Server error on signup |
| GagaNode | **shady** | Site poorly made, not recommended |
| BlockMesh | **dropped** | Rebranded to Perceptron Network, unofficial extension requires dev mode. Shady |
| PassiveApp | **active** | Restored from dead (Mar 2026) |
| Titan Network | **active** | Restored from dead (Mar 2026) |
| Spide Network | **active** | Restored from dead (Mar 2026) |

### Services Without Docker Support (Extension/App Only)

| Service | Type | Docker Feasibility | Notes |
|---------|------|-------------------|-------|
| **Grass** | Browser extension | No official image | OTP-only login. `mrcolorrain/grass` lite image broken (Chrome driver error). WebSocket-based approach using `user_id` UUID bypasses login (e.g. `wss://proxy2.wynd.network:4650`) |
| **Gradient** | Browser extension (Next.js) | No official image | Client-side JS reads `?referralCode=` param (camelCase, NOT `?code=`) |
| **Teneo** | Browser extension | No official image | Websocket-based connection |
| **Dawn** | Chrome extension / hardware box | Community Python bots exist (`Justi1980/Dawn-Validator-BOT`, `Jaammerr/The-Dawn-Bot`) that call Dawn's HTTP API directly, no browser needed. Trivially containerizable. |
| **Nodepay** | Browser extension | No official image | Behind Cloudflare protection |
| **BlockMesh** | Browser extension | No official image | Dropped — shady, rebranded to Perceptron Network |
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
| **Repocket** | **No** | -- | No public referral program |
| Bitping | **No** | -- | No referral program exists |
| Storj | **No** | -- | No referral program for node operators |
| ProxyBase | Yes | nXzS3c6iTO | `peer.proxybase.org?referral=nXzS3c6iTO`. **Two dashboards**: `client.proxybase.org` (buyer) vs `peer.proxybase.org` (seller). Docker needs **peer** USER_ID. $0.50/GB residential, $1 min payout |
| Dawn | Yes | 2QLQV97F | Extension-based |
| Spide | Yes | f3bc51 | `spide.network/register.html?f3bc51` |
| PassiveApp | Yes | bqpC4M | `passiveapp.com/i/bqpC4M` |
| Titan | Yes | 2GKKJ495 | `edge.titannet.info/signup?inviteCode=2GKKJ495` |
| URnetwork | Yes | 1Q3G19 | Obtained via API. 50% earnings + 50% referral bonus (cap 5 referrals) |
| Uprock | Yes | 33e8492e | `link.uprock.com/i/33e8492e` |
| Vast.ai | Yes | 452772 | `cloud.vast.ai/?ref_id=452772` |
| Presearch | Yes | 4872322 | `presearch.com/signup?rid=4872322`. Requires 4000 PRE stake |
| Bytelixir | Yes | OYEIRE0VSZBZ | |
| Ebesucher | Yes | geiserx | Browser autosurfing |
| Wipter | Unknown | -- | SSL failing, can't verify. Unofficial Docker may reveal code |
| BlockMesh | **No** | -- | Shady, dev mode required |

### Collector Implementation Status

Working collectors (12/12 deployed services):
- **Honeygain** -- JWT auth, `/v1/users/tokens` + `/v1/users/balances`
- **EarnApp** -- XSRF rotation + cookie auth, `/money` endpoint. **Auto-redeem** available: Amazon ($50 min), Wise ($10 min), PayPal ($10 min)
- **MystNodes** -- Cloud API (`my.mystnodes.com/api/v2`), email/password auth. **Supports per-node earnings** via `GET /api/v2/node` (30-day MYST per node, need price conversion for USD).
- **Traffmonetizer** -- JWT token, `data.traffmonetizer.com/api/app_user/get_balance`
- **IPRoyal** -- Email/password auth
- **Repocket** -- Firebase auth (Google Identity Toolkit)
- **Bitping** -- JWT cookie auth, `/api/v2/payouts/earnings`. No per-device API.
- **Earn.fm** -- Supabase auth, `/v2/harvester/view_balance`
- **PacketStream** -- Manual JWT cookie, HTML scraping `window.userData`
- **ProxyRack** -- API key auth, POST `/api/balance`. Per-device bandwidth (not earnings) via POST `/api/bandwidth` with `device_id` param.
- **Storj** -- API URL-based
- **Grass** -- Bearer token from localStorage (`app.grass.io`), `api.getgrass.io`. Returns GRASS token balance (converted to USD via CoinGecko).
- **Bytelixir** -- Laravel session cookie (expires ~3.5h), `dash.bytelixir.com`. hCaptcha blocks automated login. v0.2.17: `unquote()` handles URL-encoded cookies automatically.

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
| **Grass** | Token must be extracted from browser localStorage at `app.grass.io`. Returns GRASS tokens (converted via exchange rates). |
| **Bytelixir** | Laravel session cookie. hCaptcha blocks automated login. Must manually extract cookie from browser. With "Remember Me" ticked, sessions last days/weeks. |

---

## Deployment

### Current Deployment

3-server fleet: 1 UI instance + 2 workers. Workers send heartbeats to UI every 60s.
Fleet API key set via `CASHPILOT_API_KEY` env var on all instances.

### Performance & Deployment Learnings

- **`container.stats(stream=False)` is slow** (~1-2s per container). Never call in request path. Use `get_status_cached()` for page loads; background health check refreshes every 5 min.
- **`--read-only` breaks Docker socket access**: The entrypoint needs to modify `/etc/group` to add the `cashpilot` user to the Docker socket's group. Drop `--read-only` or add tmpfs for `/etc`.
- **Cross-subnet workers**: If worker and UI are on different subnets, ensure Tailscale subnet routing: the UI server must `tailscale set --advertise-routes=<UI-subnet>` and the worker server must `tailscale set --accept-routes=true`. Worker uses `CASHPILOT_UI_URL` with the UI's LAN IP (not Tailscale IP).
- **SQLite data retention**: 400-day retention. Daily job purges `earnings` and `health_events` older than 400 days.
- **Collection interval**: 1 hour. Earnings cache in SQLite, served instantly.
- **Worker heartbeat data**: Container status comes from workers' heartbeat data stored in SQLite. `_get_all_worker_containers()` consolidates all online workers' container lists into a flat list for display.
- **Health check deduplication**: When a service runs on multiple nodes, record only one health event per slug per check cycle (best status wins: running > restarting > exited). Without this, multi-instance services get penalised with duplicate `check_down` events.
- **Google Fonts render-blocking**: Use async preload pattern (`<link rel="preload" as="style" onload="this.rel='stylesheet'">`) to avoid blocking page render.
- **First earnings collection baseline**: When a service is first onboarded, insert a synthetic baseline record for the prior day with the same balance, so the first delta is 0 (not the full cumulative balance).

### Service-Specific Deployment Notes

#### MystNodes / Mysterium
- **MMN API key is critical**: The Mysterium container must have `MYSTNODES_API_KEY` env var or `[mmn] api-key` in `config-mainnet.toml` to link the node to the user's MystNodes cloud account.
- **Node identity is per-volume**: The Mysterium keystore lives in the Docker volume (`mysterium-data:/var/lib/mysterium-node/keystore/`). Deleting the volume or creating a new container without the same volume generates a NEW blockchain identity.
- **Registration is blockchain-based**: New identities must be registered on Polygon. This is triggered by Hermes and requires the MMN API key. If Hermes returns "internal error", it's a temporary server-side issue.
- **Per-node earnings**: The MystNodes cloud API (`GET /api/v2/node?page=1&itemsPerPage=100`) returns per-node 30-day earnings in MYST. The `earningsTotal` endpoint returns MYST token balance (not USD).
- **Image name**: `mysteriumnetwork/myst` (NOT `mysteriumnet/myst`).

### Multi-Currency & Exchange Rates

CashPilot stores earnings in each service's **native currency** (USD, MYST, GRASS, STORJ, etc.) and converts for display.

- **`app/exchange_rates.py`**: Fetches crypto→USD rates from CoinGecko (free, no key) and USD→fiat from Frankfurter API. Cached in memory, refreshed every 15 min + on startup.
- **CoinGecko IDs**: `mysterium` (MYST), `grass` (GRASS). Add new tokens to `CRYPTO_IDS` dict.
- **Frontend conversion**: `app.js` fetches `/api/exchange-rates`, stores rates client-side. `formatCurrency(val, nativeCurrency)` converts native→USD→display currency. `formatNative(val, currency)` shows original token amount alongside converted value.
- **Display currency**: Auto-detected from `navigator.language` locale (e.g. `es` → EUR). User can override in Settings. Persisted in `localStorage('cp-display-currency')`.
- **Dashboard totals**: Backend converts all non-USD balances to USD via `exchange_rates.to_usd()` for the summary total.
- **Collector currencies**: Each collector returns its native currency in `EarningsResult.currency`. MystNodes returns `MYST`, Grass returns `GRASS`, all others return `USD`.

### Worker Deployment

**Always use the dedicated worker image** (`drumsergio/cashpilot-worker`), never the UI image for workers. The worker image runs `app.worker_api:app` on port 8081.

**Important**: The `entrypoint.sh` does NOT switch modes — it only sets up Docker socket permissions. Mode is determined by which Docker image runs (`Dockerfile` → `app.main:app`, `Dockerfile.worker` → `app.worker_api:app`).

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
4. Add a collector in `app/collectors/{slug}.py` and register it in `__init__.py` 
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

---

## URnetwork API (Collector Reference)

Base URL: `https://api.bringyour.com`

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/auth/login-with-password` | None | Login: `{"user_auth":"email","password":"pass"}` → `{network:{by_jwt:"..."}}` |
| `GET` | `/auth/refresh` | Bearer JWT | Refresh JWT token |
| `GET` | `/account/referral-code` | Bearer JWT | Returns `{referral_code, total_referrals}` |
| `POST` | `/referral-code/validate` | None | Validate code: `{"referral_code":"ABC123"}` → `{is_valid, is_capped}` |

Referral system: 50% of referred user's earnings + 50% of their referral bonus. Capped at 5 referrals per referrer.

---

## Services Requiring Special Setup

### GPU Required (not viable for NUCs/home servers without discrete GPU)

- **Salad**: Windows desktop app. NVIDIA GPU required. No Docker.
- **Nosana**: NVIDIA RTX 30/40/50 or A-series. Ubuntu 20.04+. Solana wallet required.
- **io.net**: NVIDIA GPU with 8GB+ VRAM. Docker supported. Sign up at `worker.io.net/worker/devices`.

### Hardware Purchase Required

- **Helium**: Approved hotspot hardware ($200-500). No personal approval needed — just buy and set up.
- **Deeper Network**: Deeper Connect router ($350-400). Has affiliate program. Moken is unrelated/dead.
- **Flux**: Cumulus tier: 1,000 FLUX stake (~$400-600), 2 cores, 8GB RAM, 220GB SSD, 25 Mbps.

### No Account/Signup (just run software)

- **Golem**: `curl -sSf https://join.golem.network/as-provider | bash -`. Linux x86-64 only. Set own GLM/hour price.
- **Anyone Protocol**: Docker or native. `anyone.io/mine`. Needs Ethereum wallet.
- **Sentinel dVPN**: `docs.sentinel.co/dvpn-node-setup`. Need ~50 DVPN for gas. Set own bandwidth price.

### Enterprise-Only (not viable for home)

- **Filecoin**: Datacenter infrastructure required. Enterprise-grade. Penalties for downtime.

---

*Generated by [LynxPrompt](https://lynxprompt.com) CLI*
