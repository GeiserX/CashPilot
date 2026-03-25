# CashPilot Roadmap

> Living document. Updated as priorities shift. Contributions welcome for any item marked **Help Wanted**.

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

## v1.1 — Earnings Intelligence

Turn CashPilot from a deployment tool into an earnings optimization platform.

- [ ] **Earnings collectors** for top services
  - [ ] Honeygain (done)
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

## v1.2 — Multi-Node Fleet Management

For power users running CashPilot on multiple servers.

- [ ] **Remote node agents** — lightweight agent that reports back to a central CashPilot instance
- [ ] **Fleet dashboard** — see all nodes, their services, and aggregate earnings in one view
- [ ] **Node health map** — geographic visualization of your fleet
- [ ] **Cross-node service deduplication** — warn if the same account runs on multiple nodes (some services ban this)
- [ ] **Bulk deploy** — deploy a service across all nodes with one click

## v1.3 — Smart Optimization

Let CashPilot make intelligent recommendations.

- [ ] **Earnings estimator** — based on your location, ISP, and hardware, predict which services will earn the most
- [ ] **Auto-scaling suggestions** — "You could earn $X more by adding Service Y"
- [ ] **IP type detection** — automatically detect residential vs. datacenter and warn about incompatible services
- [ ] **Resource usage optimization** — suggest which services to stop if CPU/memory/bandwidth is constrained
- [ ] **Payout tracker** — track minimum payout thresholds and estimated time to next payout per service

## v1.4 — Ecosystem Expansion

Broaden beyond bandwidth sharing.

- [ ] **DePIN browser automation** — headless browser containers for extension-only services (Grass, Gradient, Teneo, etc.)
- [ ] **GPU compute support** — detect available GPUs, deploy compute services (Vast.ai, Salad, Nosana)
- [ ] **Storage sharing** — guided Storj setup with disk allocation UI
- [ ] **VPN relay nodes** — Sentinel dVPN, Mysterium (already supported), Orchid
- [ ] **CDN/edge nodes** — Flux, Theta Edge Node
- [ ] **New service YAML contributions** — community-submitted services via PR

## v2.0 — Platform

Transform CashPilot into a passive income operating system.

- [ ] **Plugin system** — custom collectors, deployers, and UI widgets without forking
- [ ] **REST API** — full CRUD API for external integrations and automation
- [ ] **Mobile app** — React Native companion for monitoring on the go
- [ ] **Service marketplace** — community-curated service definitions with ratings and reviews
- [ ] **Earnings export** — CSV/JSON export for tax reporting and accounting
- [ ] **Multi-currency support** — track crypto earnings (MYST, ATH, GRASS tokens) alongside USD
- [ ] **Two-factor authentication** — TOTP support for the web UI

## Future Ideas (unscheduled)

- **Portainer integration** — import/export from existing Portainer stacks
- **Kubernetes support** — deploy services as K8s pods for enterprise users
- **Terraform provider** — infrastructure-as-code for CashPilot deployments
- **Earning benchmarks** — anonymous, opt-in community benchmarks by region/ISP
- **Referral code manager** — track which referral codes are active and their conversion rates
- **Uptime SLA tracking** — per-service uptime guarantees vs. actual
- **Dark/light theme toggle** — currently dark-only
- **Localization** — i18n for non-English users
- **Backup/restore** — export and import CashPilot configuration + credentials

---

## Contributing

Pick any unchecked item and open a PR. For larger features, open an issue first to discuss the approach. Service YAML contributions are the easiest way to help — see `services/_schema.yml` for the format.

## Priority Legend

Items are roughly ordered by impact within each version. The version numbers represent feature milestones, not strict sequential releases — work on v1.2 features can start before v1.1 is complete if it makes sense.
