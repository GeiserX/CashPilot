# CashPilot Roadmap

> Living document. Updated as priorities shift. Contributions welcome for any item marked **Help Wanted**.

---

## Principles

- **Minimal footprint** — CashPilot itself should be as slim as possible. The managed services already consume resources; the orchestrator should not add significant overhead.
- **Docker socket optional** — CashPilot works in two modes: direct (socket mounted, full management) and monitor-only (no socket, dashboard + compose export). Never assume the socket is available.
- **YAML is truth** — every service is defined in `services/{category}/{slug}.yml`. UI, deployment, docs, and compose export all derive from these files.

---

## v1.0 — Foundation ✅

The MVP: deploy, monitor, and manage passive income containers from a single web UI.

- [x] YAML-driven service catalog (single source of truth)
- [x] One-click container deployment via Docker SDK
- [x] Container health monitoring (status, uptime, restart)
- [x] Web-based setup wizard with guided account creation
- [x] Dark responsive UI with service cards and filtering (synthwave theme, dark/light toggle)
- [x] Session-based authentication with role system (owner/writer/viewer)
- [x] Onboarding wizard for first-time users (3 setup modes: fresh, monitoring, mixed)
- [x] Credential encryption at rest (Fernet)
- [x] Auto-generated documentation from YAML definitions
- [x] Multi-arch Docker image (amd64 + arm64)
- [x] 49 services across 4 categories (bandwidth: 22, DePIN: 20, compute: 6, storage: 1)
- [x] Compose file export (per-service and bulk) for users without Docker socket access
- [x] Monitor-only mode when Docker socket is not mounted
- [x] CashPilot labels on all managed containers (`cashpilot.managed`, `cashpilot.service`)
- [x] CI/CD pipeline — linting (ruff), CodeQL scanning, auto-releases with version bumping, Docker Hub sync, Dependabot
- [x] Unraid Community Applications template

## v1.1 — Earnings Intelligence ✅

Turn CashPilot from a deployment tool into an earnings optimization platform. All core features complete; only webhook/email notifications remain.

- [x] **Earnings collectors** — 13 services with automated balance tracking
  - [x] Honeygain (JWT auth + /v2/earnings)
  - [x] EarnApp (OAuth cookie auth + /dashboard/api/money/)
  - [x] MystNodes (Tequila API at localhost:4449)
  - [x] Traffmonetizer (Bearer token + /api/dashboard)
  - [x] IPRoyal Pawns (JWT auth + /api/v1/users/me/balance-dashboard)
  - [x] Storj (storagenode local API at port 14002, optional `api_url`)
  - [x] Repocket (email/password auth)
  - [x] ProxyRack (API key auth)
  - [x] Bitping (email/password auth)
  - [x] EarnFM (email/password auth)
  - [x] PacketStream (auth token)
  - [x] Grass (access token + 429 retry logic)
  - [x] Bytelixir (session cookie + remember_web + XSRF persistent auth)
  - [x] Dynamic credential forms in Settings page (auto-generated from collector args)
  - [x] Startup collection trigger (collectors run immediately on container start)
  - [x] Collector alert system — in-app notification dropdown showing failing collectors
- [x] **Earnings dashboard** with Chart.js historical charts
  - [x] Dashboard API: /api/earnings/summary (total, today, month, change %)
  - [x] Daily chart API: /api/earnings/daily?days=N
  - [x] Deployed services API: /api/services/deployed (balance, CPU, memory)
  - [x] Per-service breakdown view with progress bars toward minimum payout
  - [ ] Total portfolio value over time
- [x] **Manual claim buttons** — per-service payout with eligibility checking
  - [x] Each service YAML defines a `cashout` section (method, dashboard_url, min_amount, currency) — all 49 services covered
  - [x] Breakdown table shows balance vs. threshold with progress bars
  - [x] Claim modal checks eligibility, shows balance/threshold, then redirects to service dashboard
  - [x] Supports different payout methods: redirect to external dashboard, API, or manual instructions
  - [x] Zero-threshold services (`min_amount: 0`) correctly eligible when balance > 0
- [x] **Service health scoring** — uptime percentage, restart frequency, score 0-100
  - [x] health_events table tracks start/stop/restart/crash/check_ok/check_down
  - [x] 5-minute health check scheduler records container state
  - [x] Health score displayed on service cards (color-coded badge)
  - [x] GET /api/health/scores endpoint
- [ ] **Notifications** — webhook/email alerts for container crashes, earnings drops, payout thresholds (collector alerts are in-app only for now)
- ~~**Auto-claim daily rewards**~~ — deferred; manual claim button covers this (each service has different thresholds and conditions)

## v1.2 — Multi-Node Fleet Management ✅

For power users running CashPilot on multiple servers. Core federation, worker architecture, and security hardening are complete. Remaining items are quality-of-life improvements.

### Architecture: Federated CashPilot Instances

Every node runs a **full CashPilot instance** with its own dashboard and local service management. One instance is designated **master**; the rest are **children** that report upstream via outbound WebSocket.

```
Master CashPilot (fleet view + local management)
        ^                ^                ^
        | WSS            | WSS            | WSS
        |                |                |
  Child CashPilot    Child CashPilot    Child CashPilot
  (server-1)         (server-2)         (server-N)
  bandwidth svcs     Storj + compute    bandwidth svcs
  Docker: direct     Docker: direct     Docker: monitor-only
```

**Why full instances, not headless agents?** Each server may run a different mix of services (bandwidth on one, storage on another, GPU compute on a third). Users need local dashboards for per-server management, and the master aggregates everything into a unified fleet view.

### Instance modes (2x2 matrix)

| | **Docker: direct** (socket mounted) | **Docker: monitor-only** (no socket) |
|---|---|---|
| **Master** | Full management + fleet aggregation | Fleet aggregation + compose export (containers managed externally, e.g. Portainer) |
| **Child** | Local management + reports to master | Earnings tracking only + reports to master (containers managed externally) |

A child in monitor-only mode is useful when containers are managed by Portainer or manual compose, but you still want CashPilot's earnings collection and fleet-wide visibility from the master.

### Features

- [x] **Master/child setting** — via `CASHPILOT_ROLE=master|child` env var (default: master)
  - Master: enables fleet dashboard, accepts WebSocket connections from children
  - Child: connects to master URL via `CASHPILOT_MASTER_URL=ws://...`
  - Both: full local dashboard, local service management (if Docker socket available)
- [x] **Outbound WebSocket** from child to master (works behind any NAT/firewall)
  - Heartbeats every 30s: container list, OS, arch, docker version, earnings
  - Master can push commands: deploy, stop, restart, remove, status
  - Reconnects with exponential backoff (1s → 300s max)
- [x] **Two auth methods** — master key (persistent, derived from secret) + join tokens (HMAC-signed, time-limited, reusable)
  - Child setup: set `CASHPILOT_MASTER_URL` and `CASHPILOT_JOIN_TOKEN`, restart
  - Per-node DB entries via hostname-salted token hashing
- [x] **Fleet dashboard** (master only) — all nodes, their services, live connection state, and remote commands
- [x] **Database: `nodes` table** — id, name, token_hash, last_seen, ip, os, arch, docker_version, docker_mode, role, status
- [x] **Federation API** — 8 endpoints for node management, token generation, fleet summary, remote commands
- [x] **Worker URL override** — `CASHPILOT_WORKER_URL` env var for explicit worker URL
- [x] **Auto-resolve worker_id** — single-worker setups don't need to specify `worker_id`
- [ ] **`node_id` on deployments/earnings** — per-node tracking (nullable for backward compat)
- [ ] **Cross-node deduplication** — warn if the same account runs on multiple nodes (some services ban this)
- [ ] **Bulk deploy** — deploy a service across all/selected nodes with one click
- [ ] **Multi-proxy support** — run multiple instances of a service across different proxies/IPs
- [ ] **Command validation against YAML catalog** — child refuses arbitrary images

> **Why WebSocket over alternatives?** Portainer Edge uses HTTP polling + reverse SSH tunnel — more complex. NATS/MQTT add an external broker. Tailscale requires separate installation on every node. SSH fails across NAT. WebSocket is a single persistent bidirectional channel built into FastAPI, works behind any firewall, and scales to 1000+ nodes trivially.

### Security hardening (v0.2.49) ✅

- [x] **Atomic fleet key bootstrap** — `app/fleet_key.py` resolves from env var → shared file → auto-generate with `O_CREAT | O_EXCL` (race-safe)
- [x] **Worker port not published** — Docker Compose uses `expose` instead of `ports` (internal only)
- [x] **Bearer auth split** — `CASHPILOT_ADMIN_API_KEY` for owner-level, fleet key for writer-level API access
- [x] **RBAC enforcement across all UI surfaces** — dashboard controls, fleet page, settings sidebar, onboarding CTAs, service detail modal, collector alerts
- [x] **Owner self-demotion guard** — cannot demote yourself or remove the last owner
- [x] **Catalog cache immutability** — shallow copies prevent cross-request mutation
- [x] **PRAGMA foreign_keys=ON** — SQLite CASCADE integrity enforced
- [x] **Credential redaction** — `secret_key` added to secret config key list
- [x] **Port protocol preservation** — Docker SDK format retains TCP/UDP
- [x] **Test suite** — 425 tests (catalog validation, collector compliance, fleet key bootstrap, eligibility integration)

## v1.3 — Smart Optimization

Let CashPilot make intelligent recommendations.

- [ ] **IP type detection** — automatically detect residential vs. datacenter and warn about incompatible services
- [ ] **Earnings estimator** — based on your location, ISP, and hardware, predict which services will earn the most
- [ ] **Auto-scaling suggestions** — "You could earn $X more by adding Service Y"
- [ ] **Resource usage optimization** — suggest which services to stop if CPU/memory/bandwidth is constrained
- [ ] **Payout tracker** — track minimum payout thresholds and estimated time to next payout per service

## v1.4 — Ecosystem Expansion

Broaden beyond bandwidth sharing.

- [ ] **DePIN browser automation** — headless browser containers for extension-only services (Grass, Gradient, Teneo, etc.)
- [ ] **GPU compute support** — detect available GPUs, deploy compute services (Vast.ai, Salad, Nosana)
- [ ] **Storage sharing** — guided Storj setup with disk allocation UI
- [ ] **VPN relay nodes** — Sentinel dVPN, Mysterium (already supported), Orchid
- [ ] **CDN/edge nodes** — Flux, Theta Edge Node
- [ ] **New service YAML contributions** — community-submitted services via PR (12+ services found in competitors not yet in CashPilot)

## v1.5 — Multi-Platform Agents

Extend CashPilot beyond Docker to monitor passive income apps on any device. Each agent is a lightweight, platform-native app that speaks the existing worker heartbeat protocol.

### Architecture: One protocol, many platforms

```
CashPilot UI (fleet view)
    ^           ^           ^           ^
    | HTTP      | HTTP      | HTTP      | HTTP
    |           |           |           |
Docker Worker  Android     Windows     macOS
(Python,       Agent       Agent       Agent
 existing)     (Kotlin)    (Go/.NET)   (Swift)
```

All agents POST to `/api/worker/heartbeat` with a shared payload schema. The UI distinguishes workers by `device_type` and renders platform-appropriate health data.

### Repos

Each agent lives in its own repo (different language, build system, release artifact):
- **`CashPilot`** — UI + Docker worker (Python, Docker image)
- **`CashPilot-android`** — Android agent (Kotlin/Compose, APK)
- **`CashPilot-windows`** — Windows agent (Go or .NET, tray app + MSI)
- **`CashPilot-macos`** — macOS agent (Swift, menu bar app)

### Shared protocol extensions

- [ ] **`device_type` field on workers** — `docker`, `android`, `windows`, `macos` (DB + API + Fleet UI)
- [ ] **Per-app health in heartbeat** — `apps: [{slug, running, net_tx_24h, net_rx_24h, last_active}]`
- [ ] **`android_package` field in service YAMLs** — maps slugs to Android package names for notification matching
- [ ] **Fleet UI: platform icons** — distinguish Docker containers from native apps in the dashboard
- [ ] **Mixed-source earnings** — merge earnings for the same service running on Docker + Android (deduplicate or sum)

### Android agent (first priority)

17 services have Android apps: Honeygain, EarnApp, IPRoyal, Mysterium, PacketStream, Traffmonetizer, Repocket, Peer2Profit, Bytelixir, ByteBenefit, Grass, Gaganode, Titan, Nodle, PassiveApp, Uprock, Wipter.

Detection strategy (no root required, Android 8+):

| API | What it proves | Latency |
|---|---|---|
| **NotificationListenerService** | App's foreground service is alive (persistent notification present) | Instant callback |
| **NetworkStatsManager** | App is transferring data (bytes tx/rx per app) | ~2h buckets |
| **UsageStatsManager** | App was recently active (last foreground time) | ~2h buckets |

User grants 3 one-time toggles: Notification Access, Usage Access, Battery Optimization exemption.

- [ ] **Android app scaffold** — Kotlin/Compose, foreground service, heartbeat sender
- [ ] **NotificationListenerService** — detect running/stopped state of monitored apps
- [ ] **NetworkStatsManager** — per-app bandwidth as earning health proxy
- [ ] **UsageStatsManager** — detect apps killed by battery optimizer
- [ ] **Config UI** — CashPilot server URL, monitored apps, heartbeat interval
- [ ] **Distribution** — F-Droid or direct APK (NotificationListener permission triggers extra Play Store scrutiny)

### Windows agent (future)

Many services have Windows-native clients. Detection via Win32 process enumeration + per-process network counters (no elevation needed for own-user processes). Tray app with heartbeat.

### macOS agent (future)

Similar to Windows — process list via `sysctl`/`proc`, network stats via `nettop`. Menu bar app.

## v2.0 — Platform

Transform CashPilot into a passive income operating system.

- [ ] **Plugin system** — custom collectors, deployers, and UI widgets without forking
- [ ] **Full REST API** — documented OpenAPI schema for external integrations and automation
- [ ] **Helm chart** — deploy CashPilot on Kubernetes clusters
- [ ] **Service marketplace** — community-curated service definitions with ratings and reviews
- [ ] **Earnings export** — CSV/JSON export for tax reporting and accounting
- [ ] **Multi-currency support** — track crypto earnings (MYST, ATH, GRASS tokens) alongside USD
- [ ] **Two-factor authentication** — TOTP support for the web UI

## Future Ideas (unscheduled)

- **Portainer integration** — import/export from existing Portainer stacks
- **Terraform provider** — infrastructure-as-code for CashPilot deployments
- **Earning benchmarks** — anonymous, opt-in community benchmarks by region/ISP
- **Referral code manager** — track which referral codes are active and their conversion rates
- **Uptime SLA tracking** — per-service uptime guarantees vs. actual
- **Localization** — i18n for non-English users
- **Backup/restore** — export and import CashPilot configuration + credentials
- **Home Assistant add-on** — deploy CashPilot as an HA Supervisor add-on

---

## Contributing

Pick any unchecked item and open a PR. For larger features, open an issue first to discuss the approach. Service YAML contributions are the easiest way to help — see `services/_schema.yml` for the format.

## Priority Legend

Items are roughly ordered by impact within each version. The version numbers represent feature milestones, not strict sequential releases — work on v1.2 features can start before v1.1 is complete if it makes sense.
