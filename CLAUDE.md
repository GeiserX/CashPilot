# CLAUDE.md — CashPilot

## Overview
Self-hosted passive income platform with a web UI that guides setup, deploys Docker containers for 16+ services, and tracks earnings from 40+ bandwidth sharing, DePIN, storage, and GPU compute services in a unified dashboard.

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
| pytest | Testing |
| MkDocs | Documentation |

## Development

```bash
# Local development
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# Run tests
pytest tests/

# Run dev environment
docker compose up -d

# Build docs
mkdocs serve
```

Two containers: `cashpilot-ui` (port 8080, web dashboard + earnings collection) and `cashpilot-worker` (port 8081, Docker agent requiring socket access).

### Adding a New Service

1. Create `services/{category}/{slug}.yml` following `_schema.yml`
2. **Include a `cashout` section** in the YAML — every service must define how users can cash out (API endpoint, redirect URL, or manual instructions). This is mandatory.
3. Manually update README.md service tables and `docs/guides/{slug}.md`
4. Add a collector in `app/collectors/{slug}.py` and register it in `__init__.py`
5. Submit a PR (one service per PR)

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
    exchange_rates.py   # Crypto/fiat conversion (CoinGecko + Frankfurter)
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
  docs/guides/          # Per-service setup guides (manually maintained)
  unraid/               # Unraid-specific deployment templates
  Dockerfile            # UI image: multi-stage python:3.12-slim, tini, non-root
  Dockerfile.worker     # Worker image: minimal deps, no collectors/templates
  docker-compose.yml    # Example deployment (UI + worker on same server)
  docker-compose.fleet.yml  # Multi-server example (UI + remote workers)
  .github/workflows/
    build.yml           # QEMU + Buildx multi-arch, Docker Hub push
    release.yml         # Auto-release on push to main
```

### Key Design Decisions

- **YAML is the source of truth.** Every service lives in `services/{category}/{slug}.yml`. The web UI, container deployment, earnings collection, and documentation ALL derive from these files. Never hardcode service-specific logic in `app/`.
- **Container naming:** All managed containers are `cashpilot-{slug}` with labels `cashpilot.managed=true` and `cashpilot.service={slug}`.
- **Data directory:** `/data` volume holds SQLite DB and persistent config. Never write outside `/data` at runtime.
- **Credentials:** Encrypted at rest via `CASHPILOT_SECRET_KEY` (Fernet). The key is auto-generated if not provided.
- **README table is manually maintained.** Update the tables in README.md directly when adding/changing services.

## UI + Worker Architecture

CashPilot is split into two **always-separate** components. The UI never touches Docker — all container operations go through workers.

### Components

| Component | Description |
|-----------|-------------|
| **CashPilot UI** | The single web dashboard. Collects all earnings centrally, shows global fleet view, manages workers. **Has NO Docker socket.** Can be hosted anywhere. Only ONE UI instance exists. |
| **CashPilot Worker** | Agent running on each server that has Docker. **Must have Docker socket access**. Manages local containers, reports status to UI via heartbeats. Has a minimal config page. |

Two separate Docker images:
- **`drumsergio/cashpilot`** — UI image: FastAPI, Jinja2, templates, static assets, collectors, APScheduler. **No Docker SDK.**
- **`drumsergio/cashpilot-worker`** — Worker image: FastAPI (minimal), Docker SDK, heartbeat timer, tiny config page. No collectors, no templates.

**There is no standalone mode.** Every server that runs Docker containers needs a worker. The UI is a pure dashboard/scheduler.

### Core Principles

1. **Separation of concerns.** UI handles: dashboard, earnings collection, scheduling, user auth. Workers handle: Docker container lifecycle, health reporting.
2. **Workers must be privileged.** A worker without Docker socket is useless.
3. **Single source of truth.** The UI instance is the only one that collects earnings and stores historical data.
4. **Earnings are never duplicated.** Since only the UI collects, there is no risk of double-counting.
5. **Workers are stateless satellites.** A worker knows which containers to keep running and the UI URL to report to.
6. **Drill-down per server and per service.** The UI shows global totals by default with per-server drill-down.

### Deployment Topology

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Server A        │     │  Server B        │     │  Server C        │
│  CashPilot UI    │◄────│  CashPilot Worker│     │  CashPilot Worker│
│  CashPilot Worker│◄────│  Reports health  │     │  Reports health  │
│  Port 8085 (UI)  │     │  Port 8081       │     │  Port 8081       │
│  Port 8081 (wkr) │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### Authentication & Credential Flow

- A single shared **API key** authenticates all workers to the UI (`CASHPILOT_API_KEY` env var).
- Credentials are Docker-native: UI sends full container spec (image, env vars, volumes, ports) to worker on deploy. Worker passes to Docker API. Docker stores env vars in container config. Restarts preserve env vars natively.

### Worker Environment Variables

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `CASHPILOT_UI_URL` | Yes | -- | URL of the CashPilot UI |
| `CASHPILOT_API_KEY` | Yes | -- | Shared API key for worker-to-UI auth |
| `CASHPILOT_WORKER_NAME` | No | hostname | Human-readable name for this worker |

### Dashboard UI Features

- **Expandable instance rows**: Multi-node services show expand chevron with per-instance status, CPU/memory, and action buttons.
- **Per-instance actions**: Sub-row buttons target the correct node via `?worker_id=X` query parameter.
- **CPU/Memory averaging**: Multi-instance services show average (prefixed with `~`) in main row, individual in sub-rows.
- **Notification bell**: Polls `/api/collector-alerts` every 60s. Red badge with count on collector failures.
- **External services**: Services deployed outside Docker appear with "External" badge, no container actions.

### Multi-Currency & Exchange Rates

- `app/exchange_rates.py` fetches crypto-to-USD from CoinGecko (free) and USD-to-fiat from Frankfurter API. Cached, refreshed every 15 min.
- Each collector returns native currency in `EarningsResult.currency` (MYST, GRASS, USD, etc.).
- Frontend converts via `/api/exchange-rates`. Display currency auto-detected from locale, user-overridable in Settings.

## Key Rules
- Never hardcode credentials; all secrets via environment variables
- Docker images: `drumsergio/cashpilot` with semver tags, never `:latest`
- Worker requires Docker socket access (`/var/run/docker.sock`)
- Always use bind mounts (not named volumes) on Unraid
- License: GPL-3.0

## CI/CD

### `release.yml` — Auto Release

Triggers on push to `main` (paths: `app/`, `services/`, `Dockerfile*`, `requirements*.txt`). Auto-increments patch version, creates annotated git tag + GitHub Release. Skips if commit message contains `[skip ci]`.

**CRITICAL: NEVER manually create tags or GitHub releases.** The workflow handles version bumping automatically. Manual tags cause `already_exists` conflicts and skip Docker builds.

### `build.yml` — Docker Build & Push

Triggers on version tags (`v*`). Lints with ruff, builds multi-arch (amd64 + arm64) via QEMU + Buildx, pushes to Docker Hub.

**Required GitHub Secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`

## Deployment Notes

### Performance Learnings

- **`container.stats(stream=False)` is slow** (~1-2s per container). Never call in request path. Use `get_status_cached()` for page loads; background health check refreshes every 5 min.
- **`--read-only` breaks Docker socket access**: The entrypoint modifies `/etc/group`. Drop `--read-only` or add tmpfs for `/etc`.
- **Cross-subnet workers**: Ensure Tailscale subnet routing between UI and worker subnets.
- **SQLite data retention**: 400-day retention with daily purge job.
- **Collection interval**: 1 hour. Earnings cached in SQLite, served instantly.
- **Health check deduplication**: Multi-instance services record only one health event per slug per check cycle (best status wins).
- **Google Fonts**: Use async preload pattern to avoid blocking page render.
- **First earnings baseline**: On onboarding, insert synthetic baseline record for prior day so first delta is 0.

### Service-Specific: MystNodes / Mysterium

- `MYSTNODES_API_KEY` env var required to link node to cloud account.
- Node identity lives in Docker volume (`mysterium-data:/var/lib/mysterium-node/keystore/`). Deleting volume = new identity.
- Registration is blockchain-based (Polygon). Hermes "internal error" = temporary server issue.
- Image: `mysteriumnetwork/myst` (NOT `mysteriumnet/myst`).

## Collector Implementation Status

Working collectors (12/12 deployed services):
- **Honeygain** — JWT auth, `/v1/users/tokens` + `/v1/users/balances`
- **EarnApp** — XSRF rotation + cookie auth, `/money`. Auto-redeem: Amazon ($50), Wise ($10), PayPal ($10)
- **MystNodes** — Cloud API (`my.mystnodes.com/api/v2`), email/password auth. Per-node earnings via `GET /api/v2/node`
- **Traffmonetizer** — JWT token, `data.traffmonetizer.com/api/app_user/get_balance`
- **IPRoyal** — Email/password auth
- **Repocket** — Firebase auth (Google Identity Toolkit)
- **Bitping** — JWT cookie auth, `/api/v2/payouts/earnings`
- **Earn.fm** — Supabase auth, `/v2/harvester/view_balance`
- **PacketStream** — Manual JWT cookie, HTML scraping `window.userData`
- **ProxyRack** — API key auth, POST `/api/balance`
- **Storj** — API URL-based
- **Grass** — Bearer token from localStorage, `api.getgrass.io`. GRASS token converted via CoinGecko
- **Bytelixir** — Laravel session cookie (~3.5h), `dash.bytelixir.com`. hCaptcha blocks automated login

### Per-Node/Per-Device Earnings

| Service | Per-Device Earnings | Notes |
|---------|:------------------:|-------|
| MystNodes | **Yes** | `GET /api/v2/node` returns per-node 30d MYST earnings |
| ProxyRack | Bandwidth only | `POST /api/bandwidth` with `device_id` — no per-device USD |
| All others | No | Account-level balance only |

### API/Dashboard Access Gotchas

| Service | Issue |
|---------|-------|
| **PacketStream** | CAPTCHA blocks login. Need manual JWT from browser. |
| **ProxyRack** | Cloudflare-protected dashboard. Need API key from browser. |
| **Nodepay** | Behind Cloudflare. Requires browser session cookies. |
| **Grass** | Token from browser localStorage at `app.grass.io`. |
| **Bytelixir** | hCaptcha blocks login. Manually extract cookie. "Remember Me" sessions last days/weeks. |

## Service Status

### 49 services across 4 categories

| Category | Active | Broken | Dead | Shady | Total |
|----------|--------|--------|------|-------|-------|
| Bandwidth | 14 | 2 | 4 | 0 | 22 |
| DePIN | 8 | 4 | 0 | 2 | 20 |
| Compute | 4 | 1 | 0 | 0 | 6 |
| Storage | 1 | 0 | 0 | 0 | 1 |

### Services Without Docker Support (Extension/App Only)

| Service | Type | Notes |
|---------|------|-------|
| Grass | Browser extension | OTP-only login. WebSocket approach using `user_id` UUID bypasses login |
| Gradient | Browser extension | `?referralCode=` param (camelCase) |
| Teneo | Browser extension | WebSocket-based |
| Dawn | Chrome extension / hardware | Community Python bots (HTTP API) exist, containerizable |
| Nodepay | Browser extension | Behind Cloudflare |
| Wipter | Desktop/mobile only | No web login/dashboard |
| Titan | Desktop/mobile | WebUI cannot generate device ID |
| Golem | Provider node | Complex setup |
| Nosana | Solana-based | Requires Solana wallet + GPU |
| Salad | Desktop app | Requires GPU passthrough |
| Vast.ai | Provider dashboard | Requires GPU passthrough |

### URnetwork API Reference

Base URL: `https://api.bringyour.com`

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/auth/login-with-password` | None | Login → `{network:{by_jwt:"..."}}` |
| `GET` | `/auth/refresh` | Bearer JWT | Refresh token |
| `GET` | `/account/referral-code` | Bearer JWT | Returns referral code + total referrals |

### Services Requiring Special Setup

**GPU Required:** Salad (NVIDIA), Nosana (RTX 30/40/50), io.net (8GB+ VRAM)
**Hardware Required:** Helium (hotspot $200-500), Deeper Network (router $350-400), Flux (1000 FLUX stake)
**No Account Needed:** Golem, Anyone Protocol (`AgreeToTerms 1` in anonrc, port 9001 forwarded), Sentinel dVPN (~50 DVPN for gas)

## Contribution Rules

- One PR per feature or fix
- Service YAMLs must follow `services/_schema.yml`
- Never hardcode service-specific logic in `app/` — belongs in YAML or collector
- Keep Docker image under 100 MB
- All Python code must pass `ruff` linting

## What NOT to Build Yet

- Auto-discovery (mDNS, Tailscale API)
- Worker-to-worker communication
- Multi-UI failover
- Android service worker

*Generated by [LynxPrompt](https://lynxprompt.com) CLI*
