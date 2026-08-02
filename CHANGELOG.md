# Changelog

All notable changes to CashPilot are documented here.

## [Unreleased]

### Fixed
- **The example compose files no longer use `:latest`** (CashPilot-jz3). Following the quickstart gave you whatever was pushed most recently, with no way to know what you were running and a breaking change possible on a routine `docker compose pull` — contradicting both the project's own 'semver tags, never `latest`' rule and the pinning claim in the security posture. They now pin the **major.minor** tag (`drumsergio/cashpilot:1.4`), which is already published by the build: patch fixes still arrive automatically, but moving to a new minor or major is a deliberate edit. A test now fails if `:latest` or an untagged image reappears, or if the UI and worker are pinned to different tags. **Upgrade note:** existing deployments are unaffected until you edit your compose file; to keep tracking every release as before, set the tag back to `:latest` deliberately
- **A service that is running but no longer earning now says so** (CashPilot-kbs). A container can be up and its collector can authenticate happily while the balance never moves — every other view looks healthy, so nothing surfaced it and the user found out by eventually noticing they had stopped being paid. Balances that have not moved for 7 recorded days now raise a distinct `flatline` alert and are listed at `GET /api/earnings/flatlines`. The detection is deliberately conservative, because a report that cries wolf is a report nobody reads: a service with too little history is not flagged, a balance that has always been zero is not flagged (that is a setup problem, not a service that stopped), and a collection outage cannot masquerade as a flat balance because the window counts distinct recorded days. The existing alert cooldown means one notification per service, not one per collection cycle
- **A redeploy no longer silently replaces a container with a different one** (CashPilot-tkd). Every redeploy rebuilt the spec from catalog YAML, and nothing recorded what was actually deployed. If the running container had diverged from the catalog — a bind mount where the catalog declares a named volume, a host path that only existed because of an env substitution — the redeploy produced a *different* container, and the worker destroys the old one before anything can compare them. That is the root cause of the whole 'lost node identity' class of bug: not key management, but memory. CashPilot now records the full resolved spec at deploy time (Fernet-encrypted, since env carries credentials) and rebuilds an existing service from that record. The catalog still supplies the image, so upgrades land, and anything you type on the deploy form still wins, so a credential can be corrected. Where the record and the catalog disagree, the difference is reported back rather than resolved silently. Storj now redeploys without retyping `IDENTITY_DIR`/`STORAGE_DIR`, and supplying a path variable still relocates the data on purpose. The unused `env_vars_encrypted` column is superseded by `spec_encrypted`, added by an automatic migration
- **A credential that is about to expire now says so, before your earnings stop** (CashPilot-aug). Several collectors need a value copied out of a browser and some die within hours — Bytelixir's session cookie lasts about 2 hours, so a collector set up in the morning was dead by the afternoon with no explanation. The only symptom was earnings quietly not being recorded, which looks exactly like a provider outage. Config entries now record when they were last set, expected credential lifetimes are declared per service with the reason in plain words, and `GET /api/credentials/health` reports each stored credential as `fresh`, `expiring_soon`, `likely_expired` or `no_known_expiry` — never returning the credential value itself. Where a service offers a durable alternative to a short-lived cookie (Bytelixir's year-long `remember_web`), the report says so while the short-lived one is still the only thing configured
- **A payout on one platform no longer erases earnings on another** (CashPilot-glc). Daily and summary earnings were computed by summing every platform's balance delta and only then clamping the total at zero. On a day a payout landed, that platform's balance fell, and the drop cancelled real earnings on other platforms before the clamp ever ran — so a day you actually earned could report zero. Each platform's delta is now clamped at zero *before* summing, so a payout counts as 'nothing earned there today' and never eats into the rest. A pure payout day reads as zero, never negative. The remaining half of the ledger work — a payouts table, drop detection, a lifetime-earned vs current-balance split, and a projected payout date — is tracked as a follow-on
- **ProxyBase migrated to the current client** (#103). ProxyBase retired its Docker Hub image and old GHCR org and moved to `proxybase.org`, so the catalog entry no longer worked. The image is now `ghcr.io/proxybaseorg/peer-cli` (digest-pinned, multi-arch amd64/arm64/armv7 — arm64/Raspberry Pi now supported), credentials are the client's current `ID` (relabelled **Access Token**, masked) and `NAME` env vars, every URL points at `proxybase.org`, and datacenter IPs are now marked as accepted (residential still earns most). Existing ProxyBase deployments must be re-deployed with a fresh Access Token — see the [updated guide](docs/guides/proxybase.md)

### Security
- **Deleting a container's volumes can no longer destroy irreplaceable state by accident** (CashPilot-efx). `remove` with `delete_volumes=true` force-deleted every named volume with no guard whatsoever — the only genuinely irreversible path in the codebase. Some services keep state behind those mounts that has no server-side copy and no backup: Storj's proof-of-work node identity (which carries the held payout balance), Mysterium's node keystore, Anyone Protocol's relay identity key, and ProxyBase Markets' generated wallet, where the volume literally is the money. Services now declare `critical_volumes` in their catalog YAML (by mount target, with a short description of what is lost), and the **worker** refuses the delete with a 409 listing exactly which volumes were protected and why. Enforcement lives in the worker rather than the UI so all deploy/remove entry points are covered. Nothing is removed when the guard fires — the check runs before the container is touched. Pass `allow_delete_critical=true` to proceed deliberately. A slug the worker cannot find in its catalog is treated as unsafe rather than unprotected, so a trimmed image can never silently unlock an irreversible delete
- **Stored credentials can no longer be silently destroyed, and the encryption key is now documented truthfully** (CashPilot-1ii). Three problems compounded: the README and SECURITY.md both described `CASHPILOT_SECRET_KEY` as the credential-encryption key, but `app/database.py` never read it (that variable signs sessions and lives at `/data/.secret_key`, a different key from `/data/.fernet_key`) — so there was no supported way to supply or restore the encryption key at all; an unwritable `/data` made the app log a warning and continue with an in-memory key, so every restart minted a new one and silently orphaned every stored credential; and a corrupt key file was overwritten with a fresh key, destroying the one artifact that could still decrypt existing values. Now: `CASHPILOT_ENCRYPTION_KEY` supplies or restores the key, an existing `/data/.fernet_key` always takes precedence (so setting the variable on a running instance is safe, and a divergence is logged), the key file is created `0o600` rather than chmod-ed after writing, a corrupt key file is preserved instead of replaced, and startup refuses outright when the key cannot be persisted. **Upgrade note:** if your data directory is not writable, CashPilot will now refuse to start instead of quietly losing credentials on the next restart — fix the mount, or set `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` if a throwaway instance is genuinely what you want. Back up `/data/.fernet_key`: without it, stored credentials cannot be decrypted
- CI supply-chain hardening: the build/release/Docker-Hub-sync workflows pin their third-party GitHub Actions (`docker/*`, `softprops/action-gh-release`, `peter-evans/dockerhub-description`) to commit SHAs instead of mutable version tags. Both Docker images now declare a `HEALTHCHECK`, and the worker's Docker Hub description is synced alongside the UI's
- First-run owner creation is now atomic (`INSERT ... WHERE NOT EXISTS`), so two registrations racing on a single setup token can no longer both create an owner — the loser gets a 409 and is directed to log in
- `/metrics` can now require a bearer token: set `CASHPILOT_METRICS_TOKEN` and scrapers must send `Authorization: Bearer <token>` (constant-time compared). With no token set it stays unauthenticated (Prometheus convention), as before
- Closed a DNS-rebinding TOCTOU in the worker-URL SSRF guard: the UI now connects to the exact IP that passed validation (carrying the original hostname in the `Host` header) instead of letting httpx re-resolve the name at request time, so a record that resolved safe during validation can't flip to a metadata/loopback address for the actual request
- The compose files now bind the dashboard (and, in the fleet compose, the Docker-socket worker) to **loopback by default** instead of `0.0.0.0`. The dashboard can command the worker and the worker's API is equivalent to root on the host, so neither should be internet-exposed out of the box. Set `CASHPILOT_BIND_ADDR` / `CASHPILOT_WORKER_BIND_ADDR` to a chosen interface (or front the UI with an authenticating reverse proxy / use a VPN) to expose deliberately. **Upgrade note:** if you reached the dashboard from another machine over your LAN, set `CASHPILOT_BIND_ADDR` (e.g. `0.0.0.0` or a specific interface) after updating
- Deleting or demoting a user now durably revokes their outstanding session cookies. Previously the revocation lived only in memory, so after a UI restart (deploy, crash, reboot) a deleted or demoted account's still-valid 30-day cookie was honored again with its old role. Revocations are persisted in a `session_revocations` table (which outlives the deleted user row) and restored into the session-epoch cache at startup
- Write-only secrets: `GET /api/config` and `/api/env-info` no longer return stored credential values — only a set/not-set indicator. `CASHPILOT_SECRET_KEY` is never sent to the browser
- Fleet key no longer sent on page load — revealed only via explicit owner-only action (`POST /api/fleet/api-key/reveal`)
- Changing a password invalidates that user's existing sessions via a per-user epoch; the changer stays logged in
- SSRF hardening on worker URLs: cloud-metadata IPs (IPv4 `169.254.169.254` + IPv6 `fd00:ec2::254`) always blocked; IPv6 loopback/link-local and IPv4-mapped bypasses closed; DNS-rebinding guard re-validates the resolved IP before each request
- New opt-in `strict` worker-URL policy; default `permissive` keeps LAN (RFC1918) and Tailscale (CGNAT `100.64.0.0/10`) workers working with no config

### Performance
- SQLite connection sharing: a single pooled connection per event loop instead of open-per-query — faster dashboard loads and less write contention
- bcrypt password hashing/verification now runs off the event loop (`asyncio.to_thread`), so a login or password change no longer blocks every other request on the single uvicorn loop for ~200-500ms
- Added an index on `earnings(date)` (date-filtered history/summary queries no longer full-scan), and the "all-time" history query is defensively capped so a long-lived DB can't return an unbounded row set
- Prometheus HTTP metrics bound their `path` label: `/api/workers/{id}` collapses per-id paths and unknown/scanner paths fold into a single `/{other}` label, so probe traffic can't grow label cardinality without limit

### Added
- **A pre-deploy reality check tells you what a service will actually do for you** (CashPilot-w58). The catalog shows one generic earnings range, so there was no way to tell before deploying whether a service would work in *your* situation — and several will not. Users found out weeks later, when it had earned nothing. `GET /api/services/{slug}/preflight` now answers that in one or two plain sentences with a clear verdict: a duplicate deployment where only one device per IP is allowed says so and warns that some providers forfeit the balance; a storage node states the disk commitment and that part of the balance is held back and forfeited if the node is abandoned early; GPU and residential-IP requirements are named as preconditions. It **never blocks a deploy** — the goal is informed consent, not a nanny — and it lists what it did *not* check (egress IP type, connection speed, free disk) so a clean result is never mistaken for a guarantee about things nobody looked at
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
