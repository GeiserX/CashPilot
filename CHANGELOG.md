# Changelog

All notable changes to CashPilot are documented here.

## [0.2.49] - 2026-03-31

### Security
- Fix unauthenticated worker-control exposure on default Docker Compose (worker port no longer published)
- Atomic shared fleet key generation with `O_CREAT | O_EXCL` — eliminates skip-auth, ephemeral key mismatch, and worker impersonation vectors
- Bearer auth split: `CASHPILOT_ADMIN_API_KEY` for owner-level, fleet key for writer-level API access
- Worker heartbeat URL pinned to prevent spoofing in no-key mode
- Fleet key first-boot race condition closed with retry-read backoff
- Credential encryption key (`secret_key`) added to secret config redaction
- `PRAGMA foreign_keys=ON` enforced for SQLite CASCADE integrity

### Fixed
- Zero-threshold payout: services with `min_amount: 0` are now correctly eligible when balance > 0
- Storj collector no longer requires manual `api_url` setting — uses built-in default
- Owner self-demotion and last-owner removal guards on `PATCH /api/users/{id}`
- Viewer/writer role gating on dashboard controls (restart, stop, logs), settings sidebar, fleet page, and service detail modal
- Onboarding step 4 CTAs no longer link non-owners to the owner-only settings page
- Collector alert clicks are no-op for non-owners (no /settings dead-end)
- Partial preference updates (nullable fields merged with existing)
- Port parsing preserves TCP/UDP protocol for Docker SDK
- Auto-resolve `worker_id` when only one worker is online
- Catalog cache returns shallow copies to prevent cross-request mutation
- CSS `var(--danger)` replaced with `var(--error)` for deploy failure styling
- Bytelixir API fallback clearly reports HTML scrape failure
- Worker URL override via `CASHPILOT_WORKER_URL` env var
- Fleet page copy-to-clipboard fetches key before copying

### Added
- `app/fleet_key.py` — central fleet key resolution module (env var → shared file → auto-generate)
- `CASHPILOT_WORKER_URL` env var for explicit worker URL override
- `cashpilot_fleet` shared Docker volume for fleet key exchange
- Integration tests for payout eligibility (14 tests against real handler)
- Regression tests for Storj optional `api_url` and fleet key bootstrap (12 tests)

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
