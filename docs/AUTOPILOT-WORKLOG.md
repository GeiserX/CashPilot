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
