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
- [x] Dark responsive UI with service cards and filtering
- [x] Session-based authentication with role system (owner/writer/viewer)
- [x] Onboarding wizard for first-time users
- [x] Credential encryption at rest (Fernet)
- [x] Auto-generated documentation from YAML definitions
- [x] Multi-arch Docker image (amd64 + arm64)
- [x] 27 services across 4 categories
- [x] Compose file export (per-service and bulk) for users without Docker socket access
- [x] Monitor-only mode when Docker socket is not mounted
- [x] CashPilot labels on all managed containers (`cashpilot.managed`, `cashpilot.service`)

## v1.1 — Earnings Intelligence

Turn CashPilot from a deployment tool into an earnings optimization platform.

- [ ] **Earnings collectors** for top services
  - [x] Honeygain (JWT auth + /v2/earnings)
  - [x] EarnApp (OAuth cookie auth + /dashboard/api/money/)
  - [x] MystNodes (Tequila API at localhost:4449)
  - [x] Traffmonetizer (Bearer token + /api/dashboard)
  - [ ] IPRoyal Pawns (API)
  - [ ] Storj (storagenode API)
- [ ] **Earnings dashboard** with Chart.js historical charts
  - [ ] Daily/weekly/monthly aggregation
  - [ ] Per-service breakdown
  - [ ] Total portfolio value over time
- [ ] **One-click cashout buttons** — per-service payout trigger from the dashboard
  - [ ] Each service YAML defines a `cashout` section (API endpoint, method, min payout, currency)
  - [ ] Dashboard shows "Cash Out" button per service when balance >= minimum payout
  - [ ] Supports different payout methods: API call, redirect to external dashboard, or instructions
  - [ ] Must be implemented for every new service added to the catalog
- [ ] **Service health scoring** — uptime percentage, restart frequency, earnings-per-hour
- [ ] **Notifications** — webhook/email alerts for container crashes, earnings drops, payout thresholds
- [ ] **Auto-claim daily rewards** — automated login + claim for services with daily bonuses (like Honeygain lucky pot)

## v1.2 — Multi-Node Fleet Management (in progress)

For power users running CashPilot on multiple servers. Core federation is implemented and deployed.

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
- [ ] **`node_id` on deployments/earnings** — per-node tracking (nullable for backward compat)
- [ ] **Cross-node deduplication** — warn if the same account runs on multiple nodes (some services ban this)
- [ ] **Bulk deploy** — deploy a service across all/selected nodes with one click
- [ ] **Multi-proxy support** — run multiple instances of a service across different proxies/IPs
- [ ] **Command validation against YAML catalog** — child refuses arbitrary images

> **Why WebSocket over alternatives?** Portainer Edge uses HTTP polling + reverse SSH tunnel — more complex. NATS/MQTT add an external broker. Tailscale requires separate installation on every node. SSH fails across NAT. WebSocket is a single persistent bidirectional channel built into FastAPI, works behind any firewall, and scales to 1000+ nodes trivially.

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
- [ ] **Mobile phone earning** — track and manage earnings from always-on Android phones running passive income apps (Honeygain, EarnApp, IPRoyal, Mysterium, etc.). Research containerized Android environments, ADB-based app management, and phone-as-a-node fleet integration

## v2.0 — Platform

Transform CashPilot into a passive income operating system.

- [ ] **Plugin system** — custom collectors, deployers, and UI widgets without forking
- [ ] **Full REST API** — documented OpenAPI schema for external integrations and automation
- [ ] **Helm chart** — deploy CashPilot on Kubernetes clusters
- [ ] **Mobile app** — React Native companion for monitoring on the go
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
