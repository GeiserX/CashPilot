# Changelog

Every release, grouped by what changed. Generated from commit history.

> **Upgrading?** Read [UPGRADING.md](UPGRADING.md) first. This file lists what
> changed; that one lists what you have to *do*. They are not the same, and this
> file cannot be trusted to flag breaking changes — only one commit in the
> project's history carries a breaking-change marker.

Releases before `1.0.0` were recorded by hand and are kept verbatim in
[docs/changelog-0.x-handwritten.md](docs/changelog-0.x-handwritten.md).

## Unreleased

### Documentation

- Generate CHANGELOG.md from the ~200 releases that already happened
- Explain GPU passthrough, and pin that it stays optional (#248)

## [1.13.0] - 2026-08-05

### Documentation

- The quickstart no longer contradicts the security page (#246)
- One configuration reference, and it states which source wins (#245)

### Features

- Workers report disk and GPU, and say when they cannot tell (#247)

## [1.12.1] - 2026-08-05

### Documentation

- Add UPGRADING.md, and pin the compose examples to 1.12 (#243)

### Fixes

- A container ID never overwrites a worker's real name (#244)

## [1.12.0] - 2026-08-05

### Features

- The heartbeat response carries what the worker's platforms earned (#242)

### Fixes

- Stop publishing agent working files on the public docs site (#241)

## [1.11.36] - 2026-08-05

### Fixes

- The claim modal said "Service not found" about services that exist (#240)

## [1.11.35] - 2026-08-05

### Fixes

- Show the version the app is actually running (#239)

## [1.11.34] - 2026-08-05

### Fixes

- The two container inventories no longer disagree (#238)

## [1.11.33] - 2026-08-05

### Fixes

- Three ways the fleet page misled the person reading it (#237)

## [1.11.32] - 2026-08-05

### Fixes

- Stop asserting a zero nobody measured, and say why Settings is empty (#236)

## [1.11.31] - 2026-08-05

### CI

- Make five guards report what they actually checked (#234)

### Fixes

- Unknown watts must suppress the net, not price it at zero (#235)

## [1.11.30] - 2026-08-05

### Fixes

- Bound the window in which the shared key still works for a worker (#233)

## [1.11.29] - 2026-08-05

### Fixes

- Collect credentials that were stored before saving them began tracking (#232)

## [1.11.28] - 2026-08-05

### Fixes

- Exchange-rate staleness was computed, published, and read by nobody (#231)

## [1.11.27] - 2026-08-05

### Fixes

- A fresh install and an upgraded one had different config schemas (#230)
- One ERROR per request when /fleet is not writable (#229)

## [1.11.26] - 2026-08-05

### Fixes

- The lockout alarm skipped the lockout it was most needed for (#228)

## [1.11.25] - 2026-08-05

### Fixes

- Two affirmatives nobody had earned (#227)

## [1.11.24] - 2026-08-04

### Fixes

- A container nobody could measure reported 0.00% CPU (#226)
- The release was announced before the images existed (#225)

## [1.11.23] - 2026-08-04

### Fixes

- Ticking two nodes behind one connection warned about nothing (#224)

## [1.11.22] - 2026-08-04

### Fixes

- The wizard's expected end state was a dashboard reading zero (#223)

## [1.11.21] - 2026-08-04

### Fixes

- The LAN-isolation warning named the wrong service, twice (#222)

## [1.11.20] - 2026-08-04

### Fixes

- A worker named "toString" was never flagged as a duplicate (#221)

## [1.11.19] - 2026-08-04

### Fixes

- Two worker rows, one name, and no way to tell them apart (#220)

## [1.11.18] - 2026-08-04

### Fixes

- The running-costs feature had no way to configure it (#219)

## [1.11.17] - 2026-08-04

### Fixes

- Neither image knew what version it was, so skew was undetectable (#218)
- The header plane was white and the wordmark was not the brand pink (#217)

## [1.11.16] - 2026-08-04

### Fixes

- The test suite ran against a resolution nothing else used (#216)
- Two more route sweeps were quietly shrinking on Starlette 1.3 (#215)

## [1.11.15] - 2026-08-04

### Fixes

- The fleet-offline recovery message named the wrong variable (#214)

## [1.11.14] - 2026-08-04

### Fixes

- A service was called idle before it had a chance to earn (#213)

## [1.11.13] - 2026-08-04

### Fixes

- A container you started yourself got live buttons that 404 (#212)

## [1.11.12] - 2026-08-04

### Fixes

- The credential checker was correct, complete, and had no caller (#211)

## [1.11.11] - 2026-08-04

### Fixes

- A worker that cannot read Docker fabricated downtime for every service (#210)

## [1.11.10] - 2026-08-04

### Fixes

- A correct balance was thrown away and reported as a collector failure (#209)

## [1.11.9] - 2026-08-04

### Fixes

- The one credential needing a shell command had no hint on screen (#208)

## [1.11.8] - 2026-08-04

### Fixes

- Three catalog entries stated their payout minimum in two units (#207)

## [1.11.7] - 2026-08-04

### Fixes

- Every wizard-deployed host registered as "cashpilot-{hostname}" (#206)

## [1.11.6] - 2026-08-04

### Fixes

- Flatline alerts reached the database, the notifier, and nobody else (#205)

## [1.11.5] - 2026-08-04

### Fixes

- An upgraded install kept its provider credentials in plaintext forever (#204)

## [1.11.4] - 2026-08-04

### Fixes

- The release workflow could not pass its own test suite (#203)
- The dashboard asserted $0.00 before anything had ever looked (#202)
- An unreachable host reported its containers as running (#201)
- A dollar balance was compared against a token minimum at 1:1 (#200)
- Fleet running costs subtracted a EUR tariff from a USD gross (#199)
- Removing a worker no longer locks the host out permanently (#197)
- Net earnings subtracted a EUR cost from a USD gross (beads batch 13) (#196)
- An undocumented payout minimum is not zero, and settings that never applied (beads batch 12) (#195)
- The quickstart installed 1.4 (issue #188), and bump cryptography past a CVE (#194)
- A wizard that congratulated failed deploys, and a modal missing its own recommendation (beads batch 11) (#193)

### Testing

- Prove the auth guard for every route instead of 14 hand-listed handlers (#198)

## [1.11.3] - 2026-08-04

### Fixes

- Preflight now applies the schema's documented vps_ip default (#192)

### Testing

- Two guards that could not fail, and one bead corrected (#191)

## [1.11.2] - 2026-08-04

### Fixes

- An unreachable machine is not a machine earning nothing (beads batch 8) (#190)
- Releases that publish nothing, and docs naming the wrong encryption key (beads batch 7) (#189)

## [1.11.1] - 2026-08-04

### Fixes

- Credentials alone now collect, and the collection test can fail (beads batch 6) (#187)

## [1.11.0] - 2026-08-04

### Features

- Make payouts visible — a queue to answer them, and progress toward the next one (#181)

## [1.10.1] - 2026-08-03

### Documentation

- Record the v1.10.0 terminal state [skip ci]

### Fixes

- Correct money, access-control and recovery defects found auditing v1.10.0

## [1.10.0] - 2026-08-02

### Features

- Own the attribution risk, and contain the lateral one (CashPilot-q0o) (#174) [skip ci]
- Is this machine worth keeping powered on? (CashPilot-l01) (#173) [skip ci]
- Optional container runtime, explicitly unsupported (CashPilot-54q) (#175) [skip ci]
- Payouts, lifetime-vs-balance, and how far off the cashout is (CashPilot-1og) (#171) [skip ci]
- Drop unsafe-inline from the CSP (CashPilot-guw) (#176) [skip ci]
- Generate the README service tables from the catalog (CashPilot-9q1) (#172) [skip ci]
- Encrypted export of irreplaceable service state (CashPilot-qqo) (#170) [skip ci]
- Notice when a provider changes its API, and test credentials on demand (CashPilot-bfl) (#169) [skip ci]
- Is anything actually crossing the wire? (CashPilot-t6y) (#168) [skip ci]

### Refactoring

- Componentize the duplicated app.js markup builders (CashPilot-cyc) (#179)
- Break the main -> routers -> main import cycle (CashPilot-sux) (#177) [skip ci]

## [1.9.1] - 2026-08-02

### Fixes

- Record only per-IP limits a provider actually states (CashPilot-4qv) (#167)

## [1.9.0] - 2026-08-02

### Features

- See the fleet the way providers do — by IP, not by machine (CashPilot-5qc) (#166)

## [1.8.0] - 2026-08-02

### Features

- Per-service disclosure — what it does with your machine (CashPilot-66x) (#165)
- Producer state — is it earning, not just running (CashPilot-b4e)

### Fixes

- Publish both images on every release, and fail if a tag is missing (CashPilot-0zw)

## [1.7.0] - 2026-08-02

### Documentation

- Clear the outstanding CodeRabbit findings on merged PRs

### Features

- Report net profit, not just gross earnings (CashPilot-f5u)

### Fixes

- Charge power per worker, not once for the whole fleet (CashPilot-yh5)

## [1.6.0] - 2026-08-02

### Documentation

- State the security defaults and enforce them in tests (CashPilot-964)
- Match the site theme to the product it documents

### Features

- Let the catalog declare a device, fixing Mysterium's missing TUN (CashPilot-6rv)

### Fixes

- Stop the flatline check crying wolf, and clear it on recovery

## [1.5.0] - 2026-08-02

### CI

- Bump the github-actions group with 4 updates (#144)

### Documentation

- Document the TUN device failure that looks like a healthy node
- Render the feature icons and redraw the header logo
- Record what CashPilot will never do (CashPilot-kct)
- Replace the competitor matrix with a comparison that stays true (CashPilot-qkc)
- Add a direction and roadmap page (#140)

### Features

- Detect services that are running but no longer earning (CashPilot-kbs)
- Persist the deployed spec and redeploy from it (CashPilot-tkd)
- Tell the user when a credential is about to expire (CashPilot-aug)
- Pre-deploy reality check (CashPilot-w58)
- Refuse deletes that would destroy irreplaceable state (CashPilot-efx)

### Fixes

- Detect release changes since the last tag, not the last commit
- Pin the example compose files to major.minor, not :latest (CashPilot-jz3)
- Stop logging raw worker error bodies, and 3 review follow-ups
- Clamp earnings per platform so a payout can't erase real earnings (CashPilot-glc)
- Stop silently destroying stored credentials (CashPilot-1ii)

## [1.4.4] - 2026-08-01

### Fixes

- Offer the durable cookies, not just the 2-hour one (#139)

## [1.4.3] - 2026-08-01

### Documentation

- Add language identifiers to the log-output code fences (#137)
- Record what actually resisted the container hardening (#136)
- Record the live-fleet hazards that look fine from outside (#135)

### Fixes

- Read the balance from the metric card, not a heading level (#138)

## [1.4.2] - 2026-07-31

### Fixes

- Do not use an ephemeral container ID as the worker identity (#134)
- Stop reporting a session-capture referral link as dead (#133)

## [1.4.1] - 2026-07-31

### Features

- Add proxybase.xyz service definition (#126)

## [1.4.0] - 2026-07-31

### Features

- Persist collector alerts and deliver them out-of-band (CashPilot-1ty) (#132)
- Weekly catalog liveness check with referral-link guard (CashPilot-owv) (#131)

## [1.3.11] - 2026-07-31

### Fixes

- Record the FX rate with each earnings reading (CashPilot-rrr) (#130)

## [1.3.10] - 2026-07-31

### Fixes

- Drop all capabilities + no-new-privileges on deployed containers (CashPilot-a5p) (#129)

## [1.3.9] - 2026-07-31

### Fixes

- Let operators opt specific volume roots past the block (CashPilot-52w) (#128)

## [1.3.8] - 2026-07-31

### Dependencies

- Update mkdocs-material requirement from >=9.7.6 to >=9.7.7 (#125)

### Fixes

- Refuse deploying broken/dropped services, not just dead (CashPilot-rp3) (#127)

## [1.3.7] - 2026-07-18

### Refactoring

- Extract shared action-button icon constants (CashPilot-cyc) (#124)

## [1.3.6] - 2026-07-18

### Performance

- Batch health-check writes, PRAGMA synchronous=NORMAL, concurrent exchange fetch (CashPilot-perf) (#123)

## [1.3.5] - 2026-07-18

### Fixes

- HSTS + CSP hardening directives + session cookie Secure behind a trusted proxy (CashPilot-sec) (#122)

## [1.3.4] - 2026-07-18

### Refactoring

- Extract SSRF worker-URL validation into app/worker_proxy.py (CashPilot-sux) (#121)

## [1.3.3] - 2026-07-18

### Fixes

- Unify the two deploy flows so the detail view validates + surfaces errors (CashPilot-cyc) (#120)

## [1.3.2] - 2026-07-18

### Fixes

- Api_worker_command earnings bug + main.py de-duplication (CashPilot-1k5) (#119)

## [1.3.1] - 2026-07-18

### Fixes

- Give each worker a stable client_id instead of its mutable hostname (CashPilot-ng1) (#118)

## [1.3.0] - 2026-07-18

### Features

- Detect deployed-image vs catalog-image drift and warn (CashPilot-5wi) (#117)

## [1.2.0] - 2026-07-18

### CI

- Install docker SDK so CI runs the full suite (fix red main from cm6 floor) (#115)

### Features

- Stricter loader validation to catch malformed entries (CashPilot-keb) (#116)

### Testing

- Harden security-path coverage + fix weak/flaky tests (CashPilot-cm6) (#114)

## [1.1.3] - 2026-07-18

### Performance

- Bcrypt off the event loop, earnings(date) index, bounded metrics cardinality (CashPilot-apm) (#113)

## [1.1.2] - 2026-07-18

### CI

- Pin third-party actions to SHAs, add HEALTHCHECKs, sync worker Docker Hub desc (CashPilot-7br) (#112)

## [1.1.1] - 2026-07-18

### Maintenance

- Remove verified dead code (CashPilot-4s2, partial) (#110)

## [1.1.0] - 2026-07-18

### Features

- Optional /metrics bearer token + atomic first-owner creation (CashPilot-2zx) (#109)

## [1.0.4] - 2026-07-18

### Fixes

- Pin validated worker IP to close SSRF DNS-rebinding TOCTOU (CashPilot-drz) (#111)
- Bind UI + Docker-socket worker to loopback by default (CashPilot-jia) (#107)

## [1.0.3] - 2026-07-17

### Fixes

- Durably revoke sessions on user delete/demote (survives restart) (#106)

## [1.0.2] - 2026-07-17

### Other

- Security + reliability + docs: whole-repo audit follow-ups (#105)

## [1.0.1] - 2026-07-17

### Dependencies

- Update tzdata requirement from >=2026.2 to >=2026.3 (#102)

### Fixes

- Migrate to GHCR peer-cli image + Access Token credentials (#103) (#104)

## [1.0.0] - 2026-07-10

### Features

- Per-worker fleet keys (full cutover, v1.0.0) (#101)

## [0.6.22] - 2026-07-10

### Performance

- Deferred audit follow-ups (health growth, first-run token, orchestrator coverage) (#100)

## [0.6.21] - 2026-07-10

### Fixes

- Code-audit findings — container escape, event-loop stalls, authz, error surfacing (#98)

## [0.6.20] - 2026-07-10

### Features

- Unstable health badge + /metrics exposure warning (#97)

## [0.6.19] - 2026-07-08

### Fixes

- Raise bitping mem_limit 128m->192m to prevent OOM (#96)

## [0.6.18] - 2026-07-05

### CI

- Bump the github-actions group with 2 updates (#94)
- Use GitHub-hosted ubuntu-latest runners (#93)

### Features

- Durable per-service Docker resource limits (#95)

### Security

- Block fork PRs from running on the self-hosted runner (#92)

## [0.6.17] - 2026-06-17

### CI

- Bump starlette from 1.0.1 to 1.3.1 (#91)

## [0.6.16] - 2026-06-17

### CI

- Bump cryptography from 48.0.0 to 48.0.1 (#90)

## [0.6.15] - 2026-06-17

### CI

- Bump python-multipart from 0.0.29 to 0.0.31 (#89)

## [0.6.14] - 2026-06-13

### CI

- Build multi-arch images via QEMU on the X64 runner (#86)

### Features

- Clearer earnings-tracking state on the dashboard (#82 follow-up) (#88)

### Fixes

- Make docker compose pull/up the correct update path (#84) (#87)

## [0.6.13] - 2026-06-11

### Fixes

- Codebase audit — bugs, dead code, hardening, test gaps (#85)

## [0.6.12] - 2026-06-11

### CI

- Bump the github-actions group with 9 updates (#81)
- Allow github-actions major bumps (#80)
- Bump deprecated GitHub Actions to current majors (#79)

### Fixes

- Repocket container env should be RP_EMAIL + RP_API_KEY (#82) (#83)

### Maintenance

- Remove AGENTS.md (migrated to CLAUDE.md)
- Merge AGENTS.md into CLAUDE.md
- Add CLAUDE.md

## [0.6.11] - 2026-05-25

### Documentation

- Add CashPilot-Desktop to ecosystem table

### Features

- Redesign onboarding as standalone synthwave page (#78)

## [0.6.10] - 2026-05-24

### Features

- Add Anyone Protocol collector and fix CI worker manifest (#77)

## [0.6.9] - 2026-05-23

### Fixes

- Auto-purge workers offline > 1 hour from fleet page (#76)

## [0.6.8] - 2026-05-23

### Fixes

- Update Earn.fm tests for Supabase auth constructor (#73)
- Earn.fm collector (Supabase auth), exchange rates, and CSP (#72)

### Maintenance

- Format earnfm.py (trailing newline) (#75)
- Trigger release build after test fix (#74)

## [0.6.7] - 2026-05-23

### Fixes

- Bytelixir collector incorrectly rejects authenticated dashboard at / (#71)

## [0.6.6] - 2026-05-23

### Fixes

- Sanitize credential values on save and improve Bytelixir hints (#70)

## [0.6.4] - 2026-05-23

### Fixes

- Chart and inline colors respect theme (light mode readability) (#69)

## [0.6.3] - 2026-05-23

### Fixes

- Use python -m uvicorn in Docker CMD (shebang path mismatch) (#68)

### Maintenance

- Add version input to build dispatch, pin compose to v0.6.2 (#67)

## [0.6.2] - 2026-05-23

### Fixes

- Release workflow skip compose pin push (branch protection) (#66)
- Rebuild worker on catalog changes, improve credential UX (#64)

## [0.6.1] - 2026-05-23

### Features

- EarnFM token auth, Prometheus metrics, orchestrator resilience (#62)

### Fixes

- Pin Docker images to v0.5.1 instead of latest
- Pin Docker images to v0.5.1 instead of latest

## [0.5.1] - 2026-05-23

### CI

- Convert Docker build to native split-build (amd64+arm64)

### Features

- Drop privileged from all services, rewrite earnfm to token auth (#61)

## [0.4.1] - 2026-05-19

### Dependencies

- Update pytest-cov requirement from >=5.0 to >=7.1.0 (#55)
- Update ruff requirement from >=0.11.0 to >=0.15.13 (#53)
- Update pytest requirement from >=8.0 to >=9.0.3 (#51)

### Features

- Security hardening, collector refactor, and API conformance (#57)

## [0.3.4] - 2026-05-19

### Dependencies

- Update uvicorn requirement from >=0.46.0 to >=0.47.0 (#52)

## [0.3.3] - 2026-05-19

### Dependencies

- Update python-multipart requirement from >=0.0.28 to >=0.0.29 (#50)
- Update pytest-asyncio requirement from >=0.23 to >=1.3.0 (#56)
- Update tzdata requirement from >=2024.1 to >=2026.2 (#54)

### Fixes

- Container crash when started with --user flag (Unraid) (#49)
- Reject deploy of dead services and gate release on CI (#47)
- Ecosystem audit — auth hardening, compose fixes, fleet docs, XSS, validation (#46)

## [0.2.90] - 2026-05-12

### Fixes

- Correct Presearch env var name to REGISTRATION_CODE (#45)

## [0.2.89] - 2026-05-12

### Dependencies

- Update python-multipart requirement from >=0.0.27 to >=0.0.28 (#43)

## [0.2.88] - 2026-05-04

### Dependencies

- Update httpx requirement from >=0.28 to >=0.28.1 (#39)

## [0.2.87] - 2026-05-04

### Dependencies

- Update fastapi requirement from >=0.115 to >=0.136.1 (#40)

## [0.2.86] - 2026-05-04

### Dependencies

- Update apscheduler requirement from >=3.10 to >=3.11.2 (#41)
- Update mkdocs-material requirement from >=9.5 to >=9.7.6 (#42)

## [0.2.85] - 2026-04-27

### Dependencies

- Update jinja2 requirement from >=3.1 to >=3.1.6 (#37)

## [0.2.84] - 2026-04-27

### Dependencies

- Update aiosqlite requirement from >=0.20 to >=0.22.1 (#36)

## [0.2.83] - 2026-04-27

### Dependencies

- Update uvicorn requirement from >=0.34 to >=0.46.0 (#34)

## [0.2.82] - 2026-04-27

### Dependencies

- Update cryptography requirement from >=44.0 to >=47.0.0 (#33)

## [0.2.81] - 2026-04-27

### Dependencies

- Update pyyaml requirement from >=6.0 to >=6.0.3 (#35)

## [0.2.80] - 2026-04-27

### Dependencies

- Update docker requirement from >=7.0 to >=7.1.0 (#32)

## [0.2.79] - 2026-04-27

### Dependencies

- Update uvloop requirement from >=0.21 to >=0.22.1 (#31)

## [0.2.78] - 2026-04-27

### Dependencies

- Update bcrypt requirement from >=4.0 to >=5.0.0 (#30)

## [0.2.77] - 2026-04-27

### CI

- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner
- Switch to self-hosted runner

### Dependencies

- Update python-multipart requirement from >=0.0.18 to >=0.0.27 (#29)

### Documentation

- Add Codecov badge to README (#28)

### Features

- Add social preview image (1280x640 Open Graph)

### Fixes

- Add setup-python to CodeQL for self-hosted runner (#26)

### Testing

- Improve test coverage to 90%+ (#27)

## [0.2.76] - 2026-04-18

### Fixes

- Update Storj deployment and add stop_timeout support (#25)

## [0.2.75] - 2026-04-17

### Features

- Add option to clear service credentials (#23)

### Maintenance

- Add .ghost-portfolio.yml for portfolio page

## [0.2.74] - 2026-04-16

### Fixes

- Update proxyrack.yml to match min. payout. (#21)

## [0.2.73] - 2026-04-15

### Fixes

- Add missing fleet_key.py to worker Docker image (#20)

## [0.2.72] - 2026-04-15

### Fixes

- Use `UTC` import instead of `datetime.UTC` attribute (#18)

## [0.2.71] - 2026-04-15

### Fixes

- Suppress stack trace exposure in worker status page (#17)

## [0.2.70] - 2026-04-15

### Fixes

- Drop passlib + security hardening — fixes #15 (#16)

## [0.2.69] - 2026-04-15

### Features

- Add stale issues workflow

### Fixes

- Truncate password by UTF-8 bytes, not characters (closes #15)

### Maintenance

- Format test_summary_bonus.py

## [0.2.68] - 2026-04-05

### Features

- Signup bonus offset — subtract promotional credits from balances

## [0.2.67] - 2026-04-05

### Fixes

- 4 review findings — encryption, auth, storj tests, traffmon heuristic

## [0.2.66] - 2026-04-05

### Fixes

- MystNodes auto-settle cashout, rewards link, claim modal

## [0.2.65] - 2026-04-05

### Fixes

- Correct cashout URLs and min payout amounts

## [0.2.64] - 2026-04-05

### Fixes

- Traffmonetizer requires browser JWT (reCAPTCHA blocks login)

## [0.2.63] - 2026-04-05

### Fixes

- Traffmonetizer uses email/password, not Docker token

## [0.2.62] - 2026-04-05

### Fixes

- Update PacketStream scraper for new dashboard HTML

## [0.2.61] - 2026-04-05

### Fixes

- Green toast after credential save, silent dashboard refresh

## [0.2.60] - 2026-04-05

### Fixes

- Remove all optional collector fields, add hints for every service

## [0.2.59] - 2026-04-05

### Fixes

- Credential modal alignment, hide optional fields, add hints

## [0.2.58] - 2026-04-05

### Features

- Inline credential update from dashboard and notifications

## [0.2.57] - 2026-04-04

### Documentation

- Add growth strategy playbook

### Features

- Support Android apps in worker heartbeat and UI
- Add CodeRabbit configuration

### Fixes

- Label Android TX/RX in dashboard sub-rows
- Recreate idx_workers_status after migration, minor cleanups
- Use stable client_id for worker identity, add worker tests
- Address review findings on Android worker support
- Center sun in favicon, icon, and logo SVGs

### Maintenance

- Update to tailored CodeRabbit config

## [0.2.56] - 2026-04-02

### Dependencies

- Update bcrypt requirement from <4.1,>=4.0 to >=4.0,<5.1

### Documentation

- Add cross-references to related projects

## [0.2.55] - 2026-04-02

### Maintenance

- Update all icons and banner to new airplane logo

## [0.2.54] - 2026-03-31

### Documentation

- Update roadmap with all built features
- Add v1.5 Multi-Platform Agents to roadmap

### Features

- Add Salad earnings collector
- Add related projects section

### Fixes

- Auto-create external deployment for manual-only collectors
- Salad uses auth cookie + XSRF double-submit, not Bearer
- Salad API moved to app-api.salad.com with Bearer auth

## [0.2.53] - 2026-03-30

### Security

- Comprehensive audit and hardening (v0.2.49)

## [0.2.52] - 2026-03-30

### Fixes

- Use CSS grid for collector credentials to prevent overflow
- Use fence_code_format for mermaid (fence_mermaid removed in pymdownx 10+)

## [0.2.51] - 2026-03-30

### Features

- Add app icon for Unraid CA template

### Fixes

- Add credential fields for bytelixir/grass, setup guide links in wizard

## [0.2.50] - 2026-03-30

### Features

- Support Bearer API key auth on all API endpoints

## [0.2.49] - 2026-03-30

### Features

- Add Setup Guide links to service detail views
- Add repo polish: tests, templates, docs site, Unraid templates, comparison table
- Add Docker Hub README sync workflow

### Fixes

- Remove draft posts from repo

## [0.2.48] - 2026-03-28

### Fixes

- Fix Titan Network dashboard URL to edge.titannet.io

## [0.2.47] - 2026-03-28

### Fixes

- Fix dashboard URLs for Titan Network and Uprock

## [0.2.46] - 2026-03-28

### Fixes

- Remove GRASS from crypto-to-USD conversion

## [0.2.45] - 2026-03-28

### Fixes

- Fix Grass and Bytelixir collectors to return real earnings

## [0.2.44] - 2026-03-28

### Other

- Use remember_web + XSRF cookies for persistent auth

## [0.2.43] - 2026-03-28

### Features

- Add startup collection trigger and Grass 429 retry logic

## [0.2.42] - 2026-03-28

### Fixes

- Fix real earnings for Grass/Bytelixir, fix collector grid layout

## [0.2.41] - 2026-03-28

### Features

- Show credentials with eye toggle, dashboard links for deployed services

## [0.2.40] - 2026-03-28

### Fixes

- Fix collector grid: prevent row height sync when details expand

## [0.2.39] - 2026-03-28

### Features

- Show actual defaults for all env vars, add Default badge

## [0.2.38] - 2026-03-28

### Features

- Add show/hide toggle for secret env vars (Fleet API Key, etc)

## [0.2.37] - 2026-03-28

### Fixes

- Remove fake DATABASE_PATH env var, show defaults for all env vars

## [0.2.36] - 2026-03-28

### Fixes

- Remove General settings, add HOSTNAME_PREFIX + COLLECT_INTERVAL env vars

## [0.2.35] - 2026-03-28

### Fixes

- Fix ruff formatting in env-info endpoint

## [0.2.34] - 2026-03-28

### Other

- Redesign settings: dynamic env vars, all 13 collectors, fix saveSettings bug

## [0.2.33] - 2026-03-28

### Fixes

- Fix worker action/logs API paths: /api/containers → /api/services

## [0.2.32] - 2026-03-28

### Other

- UI overhaul: worker-aware deploy, per-worker management, catalog fixes

## [0.2.31] - 2026-03-28

### Fixes

- Pin bcrypt<4.1 to fix passlib initialization crash

## [0.2.30] - 2026-03-28

### Fixes

- Fix bcrypt 72-byte password limit on Python 3.14

## [0.2.29] - 2026-03-28

### Fixes

- Fix wizard deployed badges, node count, signup buttons, and Mysterium port forwarding

## [0.2.27] - 2026-03-28

### Features

- Add port forwarding requirement to Anyone Protocol guide

### Other

- Enable zkSync Era payouts, fix wallet description

## [0.2.26] - 2026-03-28

### Fixes

- Fix deploy flow: build full spec from YAML, resolve ${VAR} in volumes
- Remove manual Docker deployment sections from guides

## [0.2.25] - 2026-03-28

### Features

- Add dashboard table sorting, update service guides and configs

### Fixes

- Clean up guides and README: remove auto-generation, streamline docs

### Other

- Stop auto-generating README tables, keep README manually maintained

## [0.2.24] - 2026-03-28

### Other

- Rewrite README for UI+Worker architecture, add guide links to tables

## [0.2.23] - 2026-03-28

### Other

- Service audit: update statuses, fix Anyone Protocol, add graveyard
- Clarify README: CashPilot tracks both Docker and non-Docker services

## [0.2.22] - 2026-03-28

### Features

- Add dashboard screenshot, bind MystNodes UI to all interfaces

## [0.2.21] - 2026-03-28

### Fixes

- Update platform support for all 22 services

## [0.2.20] - 2026-03-28

### Other

- Green border on deployed services, remove earnings badge, add Docker platform

## [0.2.19] - 2026-03-28

### Other

- External services: show -- for health, add disconnected label

## [0.2.18] - 2026-03-28

### Fixes

- Update ProxyBase/EarnApp info, make dashboard rows clickable

## [0.2.17] - 2026-03-27

### Fixes

- Fix Bytelixir collector to handle URL-encoded session cookies
- Clean up AGENTS.md: remove deployment examples and private topology
- Update AGENTS.md: service statuses, new referral codes, URnetwork API, setup guides

## [0.2.16] - 2026-03-27

### Features

- Add URnetwork referral code, mark Peer2Profit and PacketShare as dead

## [0.2.15] - 2026-03-27

### Features

- Add 12 new services, update statuses and referral links

## [0.2.14] - 2026-03-27

### Dependencies

- Update bcrypt requirement from <4.1,>=4.0 to >=4.0,<5.1 (#3)

## [0.2.13] - 2026-03-27

### Packaging

- Bump python from 3.12-alpine to 3.14-alpine (#2)

## [0.2.12] - 2026-03-27

### Fixes

- Remove bonus referral fields from all services, update statuses and links

## [0.2.11] - 2026-03-27

### Other

- Show all services, fix platforms, verify URLs

## [0.2.10] - 2026-03-27

### Features

- Add constants.py to worker Dockerfile

## [0.2.9] - 2026-03-27

### Other

- Skip catalog services without Docker image instead of loading them

## [0.2.8] - 2026-03-27

### Fixes

- Fix worker reporting duplicate containers when m4b uses same images

## [0.2.7] - 2026-03-27

### Features

- Enable grouped security updates

### Fixes

- Fix topbar earnings on all pages and theme label duplication

## [0.2.6] - 2026-03-27

### Other

- Navbar Option C: avatar dropdown, move GitHub/sponsor to sidebar

## [0.2.5] - 2026-03-27

### Fixes

- Fix fleet page: remove local instance card, clean container badges

## [0.2.4] - 2026-03-27

### Other

- Redesign navbar: cleaner layout, currency selector, mobile responsive

## [0.2.3] - 2026-03-27

### Other

- Reduce dashboard auto-refresh to once per hour

## [0.2.2] - 2026-03-27

### Fixes

- Fix expanded service rows collapsing on auto-refresh
- Fix CI: release workflow calls build directly via workflow_call

## [0.2.1] - 2026-03-27

### Other

- Move container label constants to shared constants module

## [0.2.0] - 2026-03-27

### Other

- Split UI from Docker: UI never touches Docker, all ops via workers

## [0.1.2] - 2026-03-27

### Features

- Implement CASHPILOT_MODE=ui for Docker-free UI container

## [0.1.1] - 2026-03-27

### Other

- Auto-release patch versions on push to main

### Packaging

- Bump python from 3.12-alpine to 3.14-alpine (#1)

## [0.1.0] - 2026-03-27

### Features

- Add multi-currency system with exchange rate conversion
- Add collector alert notifications in navbar
- Add Grass and Bytelixir earnings collectors
- Add Ebesucher referral link
- Add Bytelixir referral link
- Show manual-only services with platform notice in setup wizard
- Show spinner instead of error when loading services
- Add SECURITY.md, sponsor button, fix cold-start dashboard timeout
- Add 400-day data retention and update deployment docs
- Add federation architecture spec and update collector status in AGENTS.md
- Add CI check to agent checklist in AGENTS.md
- Add privileged mode, command template substitution to orchestrator
- Add per-service earnings breakdown and manual claim flow
- Add collector credential forms to Settings page
- Add Storj storagenode earnings collector
- Add cashout button to deployed service cards
- Add IPRoyal Pawns earnings collector
- Add cashout section to schema and all 39 service YAMLs
- Add earnings dashboard API endpoints and fix route mismatches
- Add earnings collectors for EarnApp, MystNodes, and Traffmonetizer
- Add 12 new service YAMLs from competitor analysis
- Add mobile phone earning to roadmap, remove completed theme item
- Add dark/light theme toggle and GitHub link to navbar
- Add multi-node federation docs and fleet env vars to README
- Add CashPilot app icon (synthwave sun from banner)
- Add security FAQ: Docker isolation, hardening, and honest risk assessment
- Add FUNDING.yml
- Add one-click cashout button to roadmap
- Add federated multi-node fleet management (v1.2)
- Add CI/CD: linting, CodeQL, releases, dependabot, ruff formatting
- Add 10 starfield banner iterations, remove shooting stars
- Add 10 synthwave banner iterations for selection
- Add 8 banner candidates and federated master/child architecture
- Add container discovery labels and fallback lookup
- Add dual operating mode, compose export, and slim Dockerfile
- Add autopilot compass logo, ROADMAP, remove earnings estimates, update competitors
- Add authentication system with user roles and onboarding
- Add workflow_dispatch trigger to CI
- Add project banner SVG and replace README header
- Add referral codes for 13 services and update Repocket

### Fixes

- Fix ruff formatting in main.py
- Fix action buttons: visible, consistent size, instance badge in status
- Fix Grass collector: use /retrieveUser endpoint for totalPoints
- Fix Grass token hint: accessToken in localStorage, not console
- Fix Bytelixir collector: use session cookie (hCaptcha blocks login)
- Update Grass URLs from getgrass.io to grass.io
- Fix Bytelixir and Grass platform info from research
- Fix ruff formatting in orchestrator.py
- Remove dead services, fix platforms, detect external containers
- Remove redundant url_template and code fields from referral config
- Remove how_to_get_code from service definitions
- Fix setup wizard: filter non-deployable services, improve selection UX
- Fix category cards not responding to clicks in setup wizard
- Fix inconsistent cashout button width between enabled/disabled states
- Fix action button tooltips and consistent cashout button width
- Remove private server details from AGENTS.md
- Fix ruff formatting
- Fix duplicate earnings and lint error
- Fix ProxyRack collector: add required headers for API call
- Fix collector config: optional args, correct Supabase key, JWT token support
- Fix and add earnings collectors for all 10 services
- Fix Mysterium collector: add auth support, use correct API endpoint
- Fix host network mode incompatibility with port bindings
- Update roadmap: mark breakdown, claim, and health scoring as done
- Update roadmap: mark dashboard API and cashout YAMLs as done
- Update roadmap: mark EarnApp, MystNodes, Traffmonetizer collectors as done
- Fix Docker socket permissions and apply banner color palette
- Update roadmap: mark implemented federation features, fix service count
- Clean up README: remove referral config section, add legal disclaimer, add Type column
- Remove dead services, fix referral info
- Fix registration 500: pin bcrypt<4.1 for passlib compat
- Fix Alpine Docker build: GID 999 already in use
- Update fleet management spec with WebSocket agent architecture
- Fix license to GPL-3.0, fix Starlette 1.0 TemplateResponse API, add competitors
- Fix Gradient referral URL param and mark SpeedShare as broken

### Other

- Expandable instance rows, per-node earnings, notification bell always visible
- Copy status cache before appending worker containers (was mutating shared cache, growing instance count on every API call)
- Rename Total Earnings to Total Balance, fix first-day delta
- Always show instance count badge (1x, 2x, etc) for Docker services
- Aggregate services by slug, show instance count and external services
- Mark PacketShare and WizardGain as broken, remove from README
- Auto-refresh dashboard 10s after first load for fresh stats
- Cache container stats for instant dashboard loading
- Replace WebSocket federation with UI + Worker architecture
- Revamp README tables: richer columns, referral links in service names
- Redesign dashboard: unified services table with referral links
- Redesign onboarding UX: setup mode selection, preferences persistence
- Synthwave UI overhaul: navy-purple palette, rose/cyan accents, frosted glass
- Replace compass icon with synthwave sun across web UI
- Center banner vertically, embed referrals in service links
- Overhaul README service table with device limits and IP compatibility
- Finalize synthwave starfield banner, remove all candidates
- Optimize Docker image: Alpine base, drop tini, venv pattern
- Rewrite AGENTS.md with comprehensive service status and agent guide
- Initial release: CashPilot passive income platform
- Initial commit

<!-- Generated by git-cliff. Do not edit by hand: `git cliff -o CHANGELOG.md`. -->
