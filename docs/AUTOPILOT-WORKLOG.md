# Autopilot Worklog — CashPilot per-worker-keys cutover

Append-only. Newest at the bottom. Every "done" needs evidence (test/CI/commit).

---

### 2026-07-10 — kickoff
- Branch `feat/per-worker-keys` created off `main` (after merging #90/#97/#98/#100).
- Goal recorded in `docs/GOAL.md`: per-worker keys **full cutover** → `v1.0.0`, announced.
- Established the plan (worker + UI + DB migration + release-workflow major bump + docs).
- Next: DB layer first — `workers.api_key_hash` column + migration + helpers + tests.

### 2026-07-10 — US-001 DONE (DB layer)
- `workers.api_key_hash` column + idempotent migration; `hash_worker_key` (sha256),
  `set/get_worker_key_hash`. Commit c22a5a3.
- Evidence: 4 new TestWorkerKeys tests pass; full pytest **1085 passed**; ruff check+format clean.
- Next: US-002 — UI heartbeat enrollment + reject shared key for enrolled workers.

### 2026-07-10 — US-002/003 DONE (UI cutover, both directions)
- US-002: heartbeat enrollment + reject shared key for enrolled workers (commit 088be34).
- Storage upgraded hash->encrypted (api_key_enc) so the UI can also authenticate
  outbound (commit 7328acf).
- US-003: `_get_verified_worker_url` sends each worker's own key outbound (commit 7328acf+).
- Evidence: full pytest **1088 passed**; ruff check+format clean.
- Next: US-004 — worker side (obtain/persist/use its key; inbound verify accepts own key).

### 2026-07-10 — US-003..007 DONE + architect review + PR opened
- US-003 outbound (a3827ea), US-004 worker side (df3866f), US-005 release major-bump (0065304),
  US-006 docs (f250799).
- Architect (thorough) PASSED all 5 security criteria; fixed its MEDIUM availability
  defect (lost-enrollment lockout) via key_confirmed re-delivery + low-sev items (becb5a1).
- Deslop pass: no slop found (all helpers used, no dead code, purposeful comments).
- US-007: **PR #101 opened** (feat(fleet)!: → v1.0.0), NOT merged (awaits Sergio).
- Evidence: full pytest **1099 passed**; ruff check+format clean; branch pushed.
- All 7 PRD stories passes:true. Waiting on #101 CI + CodeRabbit before cancel.

### 2026-07-18 — Bead grind (ralph): security/CI tier shipped, 5wi+ng1 in flight
- **Merged + released** (v1.0.4→v1.1.x): jia (compose loopback bind), drz (SSRF IP-pin),
  2zx (metrics bearer token + register race), 4s2 (dead code), 7br (CI SHA-pins + HEALTHCHECK),
  apm (bcrypt off-loop + earnings index + metrics cardinality), cm6 (coverage floor 90% +
  fixed CI silently skipping 196 Docker-SDK tests), keb (stricter catalog loader validation).
- **5wi (PR #117, green, pending CodeRabbit):** detect deployed-image vs catalog-image drift;
  `_split_image`/`_image_outdated` helpers + `image_outdated` on /api/services/deployed +
  "update available" badge. TestImageDrift (2). Full suite green.
- **ng1 (PR #118, green, pending CodeRabbit):** stable worker `client_id` in /data/.worker_id
  instead of mutable hostname (fixes hostname-collision 401 + rename lockout). Migration
  preserves an already-enrolled worker's WORKER_NAME identity (else new-UUID → permanent 401).
  TestClientId (6). Full suite **1168 passed**; ruff clean.
- CodeRabbit rate-limited all day (PR volume); #117/#118 held green-and-open until its rolling
  window reopens, then review → merge. NOT bypassing the review gate.
- **In progress:** 1k5 (main.py god-module refactor + api_worker_command earnings bookkeeping
  bug) — architect mapping the behavior-preserving plan. Remaining: 1k5, cyc, guw (web) +
  desktop kca/rrb/ada.

### 2026-07-18 — Bead grind COMPLETE (all safely-verifiable work shipped)
- **Fully closed + released (14 beads):** web jia/drz/2zx/4s2/7br/apm/cm6/keb/5wi/ng1/1k5
  (v1.0.4→v1.3.1) + desktop kca/rrb/ada. All merged, CodeRabbit-reviewed, CI-green, released.
- **1k5** (main.py god-module): fixed the real api_worker_command earnings-bookkeeping bug
  ($0-forever deploys) + consolidated the 4 worker-proxy blocks / lifecycle trio / entry-meta.
- **rrb** (desktop): auto-tag.yml (conventional-commit → tag → reusable desktop-release) +
  build-time version stamping; validated end-to-end (fired on ada's merge).
- **Partial (open, PRs shipped):**
  - cyc → PR #120: deploy-flow dedup + the deployServiceToWorkers bug (silent failures + no
    validation) fixed. REMAINING: HTML-builder componentization + inline-onclick removal.
  - sux → PR #121: SSRF guard extracted to app/worker_proxy.py (main.py -160L, no new cycle).
    REMAINING: benign main→routers→main cycle (intentionally left; ~40-seam churn, zero value).
- **Blocked (need a browser):** cyc componentization + guw (CSP/unsafe-inline). Both change
  rendered markup / every handler on a LIVE revenue product; the Chrome extension is not
  connected in this env, so they can't be verified — deferred to a browser-enabled session.
- Verification: every PR full-suite green (web 1172 pytest; desktop go test -race) + ruff/gofmt
  + CodeRabbit reviewed. Frontend (cyc) verified statically (node --check + analysis) as browser
  was unavailable.
