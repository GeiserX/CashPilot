# CashPilot Roadmap

> Living document. Updated as priorities shift. Contributions welcome for any item marked **Help Wanted**.

---

## Principles

- **Minimal footprint** — CashPilot itself should be as slim as possible. The managed services already consume resources; the orchestrator should not add significant overhead.
- **Docker socket optional** — CashPilot works in two modes: direct (socket mounted, full management) and monitor-only (no socket, dashboard + compose export). Never assume the socket is available.
- **YAML is truth** — every service is defined in `services/{category}/{slug}.yml`. UI, deployment, docs, and compose export all derive from these files.

---

## v1.0 — Foundation (current)

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
- [x] 28 services across 4 categories
- [x] Compose file export (per-service and bulk) for users without Docker socket access
- [x] Monitor-only mode when Docker socket is not mounted
- [x] CashPilot labels on all managed containers (`cashpilot.managed`, `cashpilot.service`)

## v1.1 — Earnings Intelligence

Turn CashPilot from a deployment tool into an earnings optimization platform.

- [ ] **Earnings collectors** for top services
  - [x] Honeygain (JWT auth + /v2/earnings)
  - [ ] EarnApp (Bright Data API)
  - [ ] MystNodes (Tequila API at localhost:4449)
  - [ ] Traffmonetizer (token-based API)
  - [ ] IPRoyal Pawns (API)
  - [ ] Peer2Profit (API)
  - [ ] Storj (storagenode API)
- [ ] **Earnings dashboard** with Chart.js historical charts
  - [ ] Daily/weekly/monthly aggregation
  - [ ] Per-service breakdown
  - [ ] Total portfolio value over time
- [ ] **Service health scoring** — uptime percentage, restart frequency, earnings-per-hour
- [ ] **Notifications** — webhook/email alerts for container crashes, earnings drops, payout thresholds
- [ ] **Auto-claim daily rewards** — automated login + claim for services with daily bonuses (like Honeygain lucky pot)

## v1.2 — Multi-Node Fleet Management

For power users running CashPilot on multiple servers.

Architecture: **outbound WebSocket agent** (no broker, no VPN, no SSH needed).

```
Central CashPilot <--- WSS --- Agent (node-1, Docker socket)
                  <--- WSS --- Agent (node-2, Docker socket)
                  <--- WSS --- Agent (node-N, Docker socket)
```

- [ ] **CashPilot Agent** — lightweight container (`drumsergio/cashpilot-agent`)
  - Single `docker run` with join token — no config files, no port forwarding
  - **Outbound WebSocket** to central instance (works behind any NAT/firewall)
  - Heartbeats every 30-60s: container list, CPU, RAM, disk, uptime
  - Receives commands: deploy, stop, restart, remove, logs, update
  - Accesses local Docker socket only — never exposes it remotely
  - Commands validated against YAML catalog — agent refuses arbitrary images
  - Reconnects with exponential backoff, queues status during disconnection
  - Target: Python (reuses orchestrator logic), ~30 MB image, ~20 MB RAM
  - Phase 1: visibility only (heartbeats). Phase 2: remote management. Phase 3: bulk deploy
- [ ] **Join tokens** — generated in CashPilot UI, HMAC-signed, single-use or time-limited
- [ ] **Fleet dashboard** — all nodes, their services, and aggregate earnings in one view
- [ ] **Database: `nodes` table** — id, name, token_hash, last_seen, ip, os, docker_version, status
- [ ] **`node_id` on deployments/earnings** — per-node tracking (nullable for backward compat)
- [ ] **Cross-node deduplication** — warn if the same account runs on multiple nodes (some services ban this)
- [ ] **Bulk deploy** — deploy a service across all/selected nodes with one click
- [ ] **Multi-proxy support** — run multiple instances of a service across different proxies/IPs

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
- **Dark/light theme toggle** — currently dark-only
- **Localization** — i18n for non-English users
- **Backup/restore** — export and import CashPilot configuration + credentials
- **Home Assistant add-on** — deploy CashPilot as an HA Supervisor add-on

---

## Contributing

Pick any unchecked item and open a PR. For larger features, open an issue first to discuss the approach. Service YAML contributions are the easiest way to help — see `services/_schema.yml` for the format.

## Priority Legend

Items are roughly ordered by impact within each version. The version numbers represent feature milestones, not strict sequential releases — work on v1.2 features can start before v1.1 is complete if it makes sense.
