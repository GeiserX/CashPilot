# GOAL

Started: 2026-07-10

## Directive (verbatim)

yes continue — use ralph

## Established intent (from the preceding conversation)

Implement **per-worker fleet keys as a full cutover** for CashPilot (web), shipped as a
**new major version (`v1.0.0`)** and **announced well** (existing fleets must re-enroll).

Cutover design (Sergio's decision):
- **Worker**: obtain a per-worker key on enrollment, persist it (`/data`), use it for
  heartbeats; verify UI→worker calls against its own key.
- **UI**: issue + hash a per-worker key on first heartbeat; bind it to `client_id`;
  **reject the shared key for already-enrolled workers** (real impersonation protection);
  call each worker with *its* key.
- **Migration + version**: `workers.api_key_hash` schema column; teach the auto-release
  workflow to do a **major** bump on a `BREAKING CHANGE`/`feat!` marker (no manual tags);
  upgrade/announcement docs.

Keep the shared `CASHPILOT_API_KEY` as the **enrollment/bootstrap** credential only.

## Working rules (this repo)
- PR workflow, one PR per feature; never merge without Sergio's approval.
- CI runs BOTH `ruff check` and `ruff format --check` — run `ruff format` before every commit.
- Never manually create tags — the release workflow bumps + tags on push to main.
- Full `pytest` must stay green.

## 2026-07-18 — continuation
Test yourself in this mac whatever you need, /research! what to improve, what to unblock... /sergio-loop with ralph then

## 2026-08-02 — continuation
Finish CashPilot 1.x: rebase and merge the open PRs (#145 deployed-spec, #149 flatline, #152 compose pins, #141 docs, #155 mysterium docs), then let release.yml cut a single release (expect v1.5.0 minor) and verify the fleet upgrade end-to-end — credentials still decrypt, collectors report, /api/credentials/health and /api/earnings/flatlines respond, and the mysterium + anyone-protocol containers are still healthy with identities intact. Then continue the remaining 1.x beads, starting with CashPilot-6rv (catalog device support, the P1 that caused the MystNodes TUN failure). Trigger CodeRabbit once per PR, never block on it, but never merge a PR whose review is actively in progress. Two items are Sergio's call and must not be actioned unilaterally: #146's GitGuardian false positive, and any history rewrite.
