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
- **Docker Image**: `drumsergio/cashpilot` on Docker Hub
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
    main.py             # App entrypoint, lifespan, 16 routes (4 HTML + 12 API)
    catalog.py          # Loads YAML service definitions, caches, SIGHUP reload
    orchestrator.py     # Docker SDK: deploy, stop, restart, remove, logs
    database.py         # Async SQLite: earnings, config, deployments tables
    collectors/         # Earnings collectors (one module per service)
      base.py           # BaseCollector ABC + EarningsResult dataclass
      honeygain.py      # Honeygain JWT auth + /v2/earnings
      __init__.py       # COLLECTOR_MAP registry + make_collectors() factory
    templates/          # Jinja2: base, dashboard, setup (4-step wizard), catalog, settings, service_detail
    static/
      css/style.css     # Dark theme (#0f1117 bg, #1a1d26 cards, #3b82f6 accent)
      js/app.js         # Vanilla JS, CP namespace, Chart.js, wizard state machine
  services/             # YAML service definitions (SINGLE SOURCE OF TRUTH)
    _schema.yml         # Schema documentation
    bandwidth/          # 13 services (honeygain, iproyal, earnapp, etc.)
    depin/              # 10 services (grass, gradient, teneo, etc.)
    storage/            # 1 service (storj)
    compute/            # 4 services (vast-ai, salad, nosana, golem)
  docs/guides/          # Auto-generated per-service setup guides
  scripts/
    generate_docs.py    # YAML -> README table + guide pages
  Dockerfile            # Multi-stage python:3.12-slim, tini, non-root
  docker-compose.yml    # Production deployment
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

## CI/CD

### `build.yml` -- Docker Build & Push

**Triggers:** Push to `main` or version tags (`v*`)

**What it does:**
1. Builds multi-arch image (linux/amd64 + linux/arm64) via QEMU + Buildx
2. Pushes to Docker Hub as `drumsergio/cashpilot`
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

Only **Honeygain** has a working earnings collector (`app/collectors/honeygain.py`). All other services are `api`, `scrape`, or `manual` stubs. Priority for next collectors:

1. **EarnApp** -- Bright Data SDK API, UUID-based auth
2. **MystNodes** -- Tequila API at `localhost:4449`
3. **Traffmonetizer** -- Token-based API
4. **PacketStream** -- CAPTCHA-protected dashboard (needs manual JWT)
5. **ProxyRack** -- Behind Cloudflare (needs browser session)

### API/Dashboard Access Gotchas

| Service | Issue |
|---------|-------|
| **PacketStream** | CAPTCHA blocks automated login. Need manual JWT from browser session for API access. |
| **ProxyRack** | Dashboard behind Cloudflare. Need API key from browser. Device UUIDs must be manually registered in `peer.proxyrack.com` dashboard. |
| **SpeedShare** | API domain (`api.speedshare.app`) misconfigured -- returns Telegraf metrics exporter output. Service non-functional. |
| **Nodepay** | Behind Cloudflare protection. API access requires browser session cookies. |

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
| `CASHPILOT_SECRET_KEY` | Auto-generated | Fernet encryption key for credentials |
| `CASHPILOT_COLLECTION_INTERVAL` | `3600` | Seconds between earnings collection |
| `CASHPILOT_PORT` | `8080` | Web UI port |

### Current Deployment

| Server | URL | Purpose |
|--------|-----|---------|
| geiserback | `http://192.168.10.110:8085` | Testing/staging instance |

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
2. Run `python scripts/generate_docs.py` to regenerate README + guides
3. Optionally add a collector in `app/collectors/{slug}.py` and register it in `__init__.py`
4. Submit a PR (one service per PR)

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
