# Changelog

All notable changes to CashPilot are documented here.

## [0.2.17] - 2026-03-28

### Fixed
- Grass and Bytelixir collectors returning 0 earnings
- Grass 429 rate-limit handling with retry logic
- Bytelixir persistent auth via remember_web + XSRF cookies
- GRASS points no longer incorrectly converted to USD at token price
- Titan Network and Uprock dashboard URLs corrected
- Collector grid columns no longer expand when details open

### Added
- Startup collection trigger (collectors run immediately on container start)

## [0.2.15] - 2026-03-27

### Added
- Dynamic collector credential forms in Settings page
- Show/hide toggle for secret environment variables
- Actual default values displayed for all env vars with Default badge
- Eye toggle for viewing stored credentials on deployed services
- Dashboard links on deployed service cards

### Fixed
- Settings page saveSettings bug
- Worker action/logs API paths
- Hostname prefix and collection interval env vars

## [0.2.12] - 2026-03-27

### Added
- Per-service earnings breakdown with progress bars toward minimum payout
- Manual claim flow with eligibility checking
- Health scoring system (uptime percentage, restart frequency, 0-100 score)
- Storj storagenode earnings collector
- IPRoyal Pawns earnings collector
- Cashout section added to all 39 service YAMLs

### Changed
- Redesigned onboarding UX with setup mode selection

## [0.2.7] - 2026-03-27

### Added
- Earnings dashboard with Chart.js historical charts
- Earnings collectors for EarnApp, MystNodes, and Traffmonetizer
- Dashboard API endpoints (summary, daily, deployed services)
- 12 new service YAMLs from competitor analysis (39 total)

### Changed
- Synthwave UI overhaul: navy-purple palette, rose/cyan accents, frosted glass
- Dark/light theme toggle added to navbar

## [0.2.0] - 2026-03-27

### Added
- Federated multi-node fleet management (master/child architecture)
- Outbound WebSocket from child to master (works behind NAT)
- Two auth methods: master key + HMAC-signed join tokens
- Fleet dashboard with remote commands (deploy, stop, restart)
- CI/CD: linting, CodeQL scanning, auto-releases, Dependabot
- Ruff formatting across entire codebase

### Fixed
- Alpine Docker build GID 999 conflict
- bcrypt 72-byte password limit on Python 3.14

## [0.1.0] - 2026-03-27

### Added
- YAML-driven service catalog (single source of truth)
- One-click container deployment via Docker SDK
- Container health monitoring (status, uptime, restart)
- Web-based setup wizard with guided account creation
- Dark responsive UI with service cards and filtering
- Session-based authentication with role system (owner/writer/viewer)
- Credential encryption at rest (Fernet)
- Multi-arch Docker image (amd64 + arm64)
- 27 services across 4 categories
- Compose file export for users without Docker socket
- Monitor-only mode when Docker socket is not mounted
- SECURITY.md with vulnerability reporting process
- ROADMAP.md with versioned feature plan
