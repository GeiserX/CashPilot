# Changelog

All notable changes to CashPilot are documented here.

## [Unreleased]

### Fixed
- **ProxyBase migrated to the current client** (#103). ProxyBase retired its Docker Hub image and old GHCR org and moved to `proxybase.org`, so the catalog entry no longer worked. The image is now `ghcr.io/proxybaseorg/peer-cli` (digest-pinned, multi-arch amd64/arm64/armv7 — arm64/Raspberry Pi now supported), credentials are the client's current `ID` (relabelled **Access Token**, masked) and `NAME` env vars, every URL points at `proxybase.org`, and datacenter IPs are now marked as accepted (residential still earns most). Existing ProxyBase deployments must be re-deployed with a fresh Access Token — see the [updated guide](docs/guides/proxybase.md)

### Security
- The compose files now bind the dashboard (and, in the fleet compose, the Docker-socket worker) to **loopback by default** instead of `0.0.0.0`. The dashboard can command the worker and the worker's API is equivalent to root on the host, so neither should be internet-exposed out of the box. Set `CASHPILOT_BIND_ADDR` / `CASHPILOT_WORKER_BIND_ADDR` to a chosen interface (or front the UI with an authenticating reverse proxy / use a VPN) to expose deliberately. **Upgrade note:** if you reached the dashboard from another machine over your LAN, set `CASHPILOT_BIND_ADDR` (e.g. `0.0.0.0` or a specific interface) after updating
- Deleting or demoting a user now durably revokes their outstanding session cookies. Previously the revocation lived only in memory, so after a UI restart (deploy, crash, reboot) a deleted or demoted account's still-valid 30-day cookie was honored again with its old role. Revocations are persisted in a `session_revocations` table (which outlives the deleted user row) and restored into the session-epoch cache at startup
- Write-only secrets: `GET /api/config` and `/api/env-info` no longer return stored credential values — only a set/not-set indicator. `CASHPILOT_SECRET_KEY` is never sent to the browser
- Fleet key no longer sent on page load — revealed only via explicit owner-only action (`POST /api/fleet/api-key/reveal`)
- Changing a password invalidates that user's existing sessions via a per-user epoch; the changer stays logged in
- SSRF hardening on worker URLs: cloud-metadata IPs (IPv4 `169.254.169.254` + IPv6 `fd00:ec2::254`) always blocked; IPv6 loopback/link-local and IPv4-mapped bypasses closed; DNS-rebinding guard re-validates the resolved IP before each request
- New opt-in `strict` worker-URL policy; default `permissive` keeps LAN (RFC1918) and Tailscale (CGNAT `100.64.0.0/10`) workers working with no config

### Performance
- SQLite connection sharing: a single pooled connection per event loop instead of open-per-query — faster dashboard loads and less write contention

### Added
- Self-service password change `POST /api/users/me/password` (all roles, via the avatar menu) and owner reset `POST /api/users/{id}/password`
- `CASHPILOT_WORKER_URL_POLICY`, `CASHPILOT_WORKER_ALLOWED_HOSTS`, and `CASHPILOT_WORKER_ALLOW_METADATA` env vars for worker-URL validation

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
