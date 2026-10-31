# CashPilot Roadmap

> Living document. Updated as priorities shift. Contributions welcome for any item marked **Help Wanted**.

---

## Principles

- **Minimal footprint**: CashPilot itself should be as slim as possible. The managed services already consume resources; the orchestrator should not add significant overhead.
- **The UI never holds the Docker socket.** Workers hold it, one per machine, and manage containers there. Without a worker the UI still tracks earnings and exports compose files.
- **YAML is truth**: every service is defined in `services/{category}/{slug}.yml`. UI, deployment, docs, and compose export all derive from these files.

---

## v1.0: Foundation ✅

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
- [x] CI/CD pipeline: linting (ruff), CodeQL scanning, auto-releases with version bumping, Docker Hub sync, Dependabot
- [x] Unraid Community Applications template

## v1.1: Earnings Intelligence ✅

Turn CashPilot from a deployment tool into an earnings optimization platform. All core features complete.

- [x] **Earnings collectors**: 13 services with automated balance tracking
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
  - [x] Collector alert system: in-app notification dropdown showing failing collectors
- [x] **Earnings dashboard** with Chart.js historical charts
  - [x] Dashboard API: /api/earnings/summary (total, today, month, change %)
  - [x] Daily chart API: /api/earnings/daily?days=N
  - [x] Deployed services API: /api/services/deployed (balance, CPU, memory)
  - [x] Per-service breakdown view with progress bars toward minimum payout
  - [ ] Total portfolio value over time
- [x] **Manual claim buttons**: per-service payout with eligibility checking
  - [x] Each service YAML defines a `cashout` section (method, dashboard_url, min_amount, currency); all 49 services covered
  - [x] Breakdown table shows balance vs. threshold with progress bars
  - [x] Claim modal checks eligibility, shows balance/threshold, then redirects to service dashboard
  - [x] Supports different payout methods: redirect to external dashboard, API, or manual instructions
  - [x] Zero-threshold services (`min_amount: 0`) correctly eligible when balance > 0
- [x] **Service health scoring**: uptime percentage, restart frequency, score 0-100
  - [x] health_events table tracks start/stop/restart/crash/check_ok/check_down
  - [x] 5-minute health check scheduler records container state
  - [x] Health score displayed on service cards (color-coded badge)
  - [x] GET /api/health/scores endpoint
- [x] **Notifications**: collector alerts persist and go out by ntfy, webhook or Telegram (`CASHPILOT_NTFY_URL`, `CASHPILOT_WEBHOOK_URL`, `CASHPILOT_TELEGRAM_*`, since v1.4.0). Email is not built.
- [ ] **Auto-claim daily rewards**: automated daily reward collection for services that support it (Honeygain lucky pot, Grass daily check-in, etc.); per-service opt-in with schedule configuration

## v1.2: Multi-Node Fleet Management ✅

For power users running CashPilot on multiple servers. Core federation, worker architecture, and security hardening are complete. Remaining items are quality-of-life improvements.

### Architecture: one UI, one worker per machine

The first design (full CashPilot instances, a master and children joined over WebSocket, join tokens, a `nodes` table) was replaced in v0.1.0 by what ships today: one **UI** that never holds the Docker socket, and one **worker** per machine that holds it. Workers send a REST heartbeat to the UI every 60 seconds (`POST /api/workers/heartbeat`), and the UI sends commands to the worker's HTTP API on port 8081. Since v1.0.0 each worker authenticates with its own key. See [docs/fleet.md](docs/fleet.md).

```
CashPilot UI (fleet view, earnings, no Docker socket)
        ^  |             ^  |             ^  |
  heartbeat | commands   |  |             |  |
        |  v             |  v             |  v
  Worker (server-1)  Worker (server-2)  Worker (server-N)
  Docker socket      Docker socket      Docker socket
```

### Features

- [x] **Worker heartbeat**: every 60s, with the container list, system info (OS, arch, disk, GPU), status; a worker with no heartbeat for 180s is marked offline
- [x] **Remote commands**: deploy, stop, start, restart, remove, through `POST /api/workers/{id}/command`
- [x] **Per-worker fleet keys** (v1.0.0): the shared `CASHPILOT_API_KEY` only enrolls a worker, which then gets its own key
- [x] **Fleet dashboard**: all workers, their services, online/offline state, and remote commands
- [x] **Worker URL override**: `CASHPILOT_WORKER_URL` env var for explicit worker URL
- [x] **Auto-resolve worker_id**: single-worker setups don't need to specify `worker_id`
- [ ] **Per-worker deployments and earnings**: deployment specs are stored per worker (`deployment_specs`), but earnings are still per account. MystNodes alone exposes a per-node breakdown (`/api/services/{slug}/per-node-earnings`)
- [ ] **Cross-node deduplication**: warn if the same account runs on multiple nodes (some services ban this). The fleet already groups workers by public IP and warns before a deploy onto an IP that already runs the service (v1.9.0, `/api/fleet/egress-groups`)
- [ ] **Bulk deploy**: deploy a service across all/selected nodes with one click
- [ ] **Multi-proxy support**: run multiple instances of a service across different proxies/IPs. A service can run more than once per worker where the provider pays per device (v1.45.0)
- [ ] **Command validation against YAML catalog**: worker refuses arbitrary images. Today the worker checks capabilities, devices and host networking against the slug's catalog entry, not the image

### Security hardening (v0.2.49) ✅

- [x] **Atomic fleet key bootstrap**: `app/fleet_key.py` resolves from env var → shared file → auto-generate with `O_CREAT | O_EXCL` (race-safe)
- [x] **Worker port not published**: `docker-compose.yml` uses `expose` instead of `ports`; `docker-compose.fleet.yml` publishes it on loopback only (`CASHPILOT_WORKER_BIND_ADDR`)
- [x] **Bearer auth split**: `CASHPILOT_ADMIN_API_KEY` for owner-level, fleet key for writer-level API access
- [x] **RBAC enforcement across all UI surfaces**: dashboard controls, fleet page, settings sidebar, onboarding CTAs, service detail modal, collector alerts
- [x] **Owner self-demotion guard**: cannot demote yourself or remove the last owner
- [x] **Catalog cache immutability**: shallow copies prevent cross-request mutation
- [x] **PRAGMA foreign_keys=ON**: SQLite CASCADE integrity enforced
- [x] **Credential redaction**: `secret_key` added to secret config key list
- [x] **Port protocol preservation**: Docker SDK format retains TCP/UDP
- [x] **Test suite**: 425 tests (catalog validation, collector compliance, fleet key bootstrap, eligibility integration)

## v1.3: Smart Optimization

Let CashPilot make intelligent recommendations.

- [ ] **IP type detection**: automatically detect residential vs. datacenter and warn about incompatible services. Each worker guesses `residential` or `hosting` from its hardware since v1.9.0 (`CASHPILOT_WORKER_NETWORK` overrides it)
- [ ] **Earnings estimator**: based on your location, ISP, and hardware, predict which services will earn the most
- [ ] **Auto-scaling suggestions**: "You could earn $X more by adding Service Y"
- [ ] **Resource usage optimization**: suggest which services to stop if CPU/memory/bandwidth is constrained. Net profit after power cost (v1.7.0) and per-machine economics (v1.10.0) are shipped
- [x] **Payout tracker**: payouts, minimum thresholds and distance to the next cashout per service (v1.10.0, `/api/earnings/payouts`, `/api/services/{slug}/payout-progress`)

## v1.4: Ecosystem Expansion

Broaden beyond bandwidth sharing.

- [ ] **DePIN browser automation**: headless browser containers for extension-only services (Grass, Gradient, Teneo, etc.)
- [ ] **GPU compute support**: detect available GPUs, deploy compute services (Vast.ai, Salad, Nosana). Workers report their GPU since v1.13.0
- [ ] **Storage sharing**: guided Storj setup with disk allocation UI
- [ ] **VPN relay nodes**: Sentinel dVPN, Mysterium (already supported), Orchid
- [ ] **CDN/edge nodes**: Flux, Theta Edge Node
- [ ] **New service YAML contributions**: community-submitted services via PR (12+ services found in competitors not yet in CashPilot)

## v1.5: Multi-Platform Agents

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

All agents POST to `/api/workers/heartbeat` with a shared payload schema. The UI distinguishes workers by `device_type` and renders platform-appropriate health data.

### Repos

Each agent lives in its own repo (different language, build system, release artifact):
- **`CashPilot`**: UI + Docker worker (Python, Docker image)
- **`CashPilot-android`**: Android agent (Kotlin/Compose, APK)
- **`CashPilot-windows`**: Windows agent (Go or .NET, tray app + MSI)
- **`CashPilot-macos`**: macOS agent (Swift, menu bar app)

### Shared protocol extensions

- [ ] **`device_type` field on workers**: `docker`, `android`, `windows`, `macos` (DB + API + Fleet UI)
- [x] **Per-app health in heartbeat**: `apps: [{slug, running, net_tx_24h, net_rx_24h, last_active}]` (v0.2.57; `running` may be unknown since v1.14.1)
- [ ] **`android_package` field in service YAMLs**: maps slugs to Android package names for notification matching
- [ ] **Fleet UI: platform icons**: distinguish Docker containers from native apps in the dashboard
- [ ] **Mixed-source earnings**: merge earnings for the same service running on Docker + Android (deduplicate or sum)

### Android agent (first priority)

17 services have Android apps: Honeygain, EarnApp, IPRoyal, Mysterium, PacketStream, Traffmonetizer, Repocket, Peer2Profit, Bytelixir, ByteBenefit, Grass, Gaganode, Titan, Nodle, PassiveApp, Uprock, Wipter.

Detection strategy (no root required, Android 8+):

| API | What it proves | Latency |
|---|---|---|
| **NotificationListenerService** | App's foreground service is alive (persistent notification present) | Instant callback |
| **NetworkStatsManager** | App is transferring data (bytes tx/rx per app) | ~2h buckets |
| **UsageStatsManager** | App was recently active (last foreground time) | ~2h buckets |

User grants 3 one-time toggles: Notification Access, Usage Access, Battery Optimization exemption.

- [x] **Android app scaffold**: Kotlin/Compose, foreground service, heartbeat sender. Shipped as [CashPilot-android](https://github.com/GeiserX/CashPilot-android); the UI recognises it by `device_type: android` or `os: Android` and checks its releases for updates
- [ ] **NotificationListenerService**: detect running/stopped state of monitored apps
- [ ] **NetworkStatsManager**: per-app bandwidth as earning health proxy
- [ ] **UsageStatsManager**: detect apps killed by battery optimizer
- [ ] **Config UI**: CashPilot server URL, monitored apps, heartbeat interval
- [ ] **Distribution**: F-Droid or direct APK (NotificationListener permission triggers extra Play Store scrutiny)

Windows and macOS are covered today by CashPilot Desktop, a paired client that heartbeats with `device_type: desktop` and can hand over the history it collected before pairing (`POST /api/workers/earnings-import`). The two sections below are the original plan.

### Windows agent (future)

Many services have Windows-native clients. Detection via Win32 process enumeration + per-process network counters (no elevation needed for own-user processes). Tray app with heartbeat.

### macOS agent (future)

Similar to Windows: process list via `sysctl`/`proc`, network stats via `nettop`. Menu bar app.

## v2.0: Platform

Transform CashPilot into a passive income operating system.

- [ ] **Plugin system**: custom collectors, deployers, and UI widgets without forking
- [ ] **Full REST API**: documented OpenAPI schema for external integrations and automation
- [ ] **Helm chart**: deploy CashPilot on Kubernetes clusters
- [ ] **Service marketplace**: community-curated service definitions with ratings and reviews
- [ ] **Earnings export**: CSV/JSON export for tax reporting and accounting
- [x] **Multi-currency support**: track crypto earnings (MYST, ATH, GRASS tokens) alongside USD. Each reading stores its currency and FX rate (v1.3.11), converted through CoinGecko and Frankfurter
- [ ] **Two-factor authentication**: TOTP support for the web UI

## Future Ideas (unscheduled)

- **Portainer integration**: import/export from existing Portainer stacks
- **Terraform provider**: infrastructure-as-code for CashPilot deployments
- **Earning benchmarks**: anonymous, opt-in community benchmarks by region/ISP
- **Referral code manager**: track which referral codes are active and their conversion rates
- **Uptime SLA tracking**: per-service uptime guarantees vs. actual
- **Localization**: i18n for non-English users
- **Backup/restore**: export and import CashPilot configuration + credentials
- **Home Assistant add-on**: deploy CashPilot as an HA Supervisor add-on

---

## Contributing

Pick any unchecked item and open a PR. For larger features, open an issue first to discuss the approach. Service YAML contributions are the easiest way to help; see `services/_schema.yml` for the format.

## Priority Legend

Items are roughly ordered by impact within each version. The version numbers represent feature milestones, not strict sequential releases. Work on v1.2 features can start before v1.1 is complete if it makes sense.
