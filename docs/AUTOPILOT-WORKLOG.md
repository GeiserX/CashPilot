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

## 2026-08-02T11:47:37Z — sergio-loop segment 1, iteration 1

**Slice:** merge the remaining 1.x PRs, cut one release, verify the fleet.

**Merged (14 total this batch):** 1ii, efx, tkd, glc, aug, kbs, qkc, kct, jz3, w58, the CodeRabbit
security follow-up (#154), the log-leak fix, docs (#141), the Mysterium runbook (#155), and the CI
fix (#156).

**Release: v1.5.0.** Tag, GitHub release, and all four image tags published multi-arch and verified
present with `docker manifest inspect`: cashpilot{,-worker}:1.5.0 and :1.5. The :1.5 tag matters
because the compose files now pin major.minor (CashPilot-jz3).

**CI bug found and fixed while releasing (#156).** release.yml decided whether to build from
`git diff HEAD~1 HEAD` — only the newest commit — while a release contains every commit since the
previous tag. The failure was SILENT: with the app changes in earlier commits (merged `[skip ci]`)
and a compose-only final commit, it concluded "nothing to build", skipped the version step, and
produced no tag and no image while reporting success. Now diffs from the latest tag; verified
`v1.4.4..HEAD` reports 7 app/ files + services/ and resolves to build.

**Fleet verification (read-only, watchtower):**
- 17/17 containers up; cashpilot-ui and cashpilot-worker both healthy.
- Credentials decrypt and collectors run: 12 platforms recorded readings dated today
  (bitping, bytelixir, earnapp, earnfm, grass, honeygain, iproyal, mysterium, proxyrack, repocket,
  storj, traffmonetizer).
- Mysterium identity intact: 0x55fd4a497237be0591b6c2423cde0e325398b6a8. Anyone Protocol relay key
  (ed25519_master_id_secret_key) present. Both were recreated earlier today to restore the TUN
  device and the cashpilot labels my hardening run had stripped.
- **One real fault: packetstream** — "Could not parse balance from dashboard". Its fix shipped in an
  earlier release; the fleet UI is still on 1.4.1, so upgrading resolves it.

**Fleet is on UI 1.4.1 / worker 1.4.2, NOT 1.5.0.** Upgrading is a DEPLOY, a class deliberately
excluded from the standing grant in .omc/sergio-loop/authorization.json (which names only merge and
release). The stack is GitOps-managed at /mnt/user/appdata/stacks/watchtower/cashpilot/, so the
correct path is a push to the Gitea stacks repo, not editing on the server. Not actioned.

**Counters:** iteration 1, no_progress 0, failures 0.

**Next action:** get Sergio's go-ahead for the fleet upgrade to 1.5.0 (which also fixes
packetstream), then continue 1.x with CashPilot-6rv (catalog device support — the P1 behind the
MystNodes TUN failure).

## 2026-08-02T12:23:44Z — sergio-loop segment 1, iteration 2

**Released v1.5.0 then v1.6.0.** Both verified: tag, GitHub release, and all image tags present
multi-arch on Docker Hub (:1.6.0 and :1.6 for both ui and worker).

**Open PRs: 0.** Landed #145, #146, #149, #152, #141, #155, #156, #157, #158, #159, #160.

**CI bug found while releasing (#156).** release.yml decided whether to build from
`git diff HEAD~1 HEAD`, only the newest commit, while a release contains everything since the
previous tag. Silent: with app changes in earlier `[skip ci]` merges it concluded "nothing to
build", skipped the version step, and produced no tag and no image while reporting success. Now
diffs from the latest tag.

**CodeRabbit audit (Sergio's explicit ask) — 14 unresolved threads found on MERGED PRs.** All are
now fixed and resolved, each verified by reading main rather than trusting the report:
- #149 (2, REAL BUGS, never seen before): the flatline query read all history, so a failing
  collector — whose old readings are unchanged — read as a flatline, as did a removed service
  that kept its history; and nothing cleared the flatline cooldown on recovery, so a service
  that recovered and went flat again inside the window was silently swallowed. Fixed in #158.
- #143 (4): raw worker body logged at warning while deliberately withheld from the caller
  (credential leak into logs), schema overclaim, E402, leaked lifespan_context. Fixed in #154.
- #140 (4): record-vs-catalog precedence, over-broad hosted-custody legal claim, export trust
  boundary, recovery boundary. Fixed in #160.
- #126 (2): guide commands used :latest while the catalog pins by digest. Fixed in #160.
- #136 (1): already fixed in #137; verified no bare opening fence remains.
- #146 (1): hostname preservation, already fixed in #145.
Threads stayed open only because fixes landed in later PRs — CodeRabbit auto-resolves same-branch
fixes only. Each closed with a comment naming the fixing PR.

**One review finding REJECTED after checking.** #126 claimed the YAML says USDC on Solana with a
Solana wallet, conflicting with the guide's Tempo. Both files say Tempo, the CLI flag is
--tempo-address, and independent research agrees. Not actioned.

**Logo/theme (Sergio's question).** Diagnosed as a theme mismatch rather than a logo problem: docs
shipped material's deep purple + pink while the app is #0f1117 with a #3b82f6 accent, so the site
and the product looked like different things and the warm mark clashed with the purple bar. Sergio
chose "match the docs to the app"; shipped in #159. No logo redraw needed — the mark was already
drawn for dark.

**Counters:** iteration 2, no_progress 0, failures 0.

**Next action:** fleet upgrade to 1.6.0 awaits Sergio (deploy is not in the standing grant); then
continue 1.x beads starting with f5u (P1, net profit / power cost).

## 2026-08-02T13:21:08Z — sergio-loop segment 1, iteration 3

**Fleet upgraded to 1.6.0 and verified end to end.** Sergio granted deploy explicitly
("Obviously update all my fleet, otherwise how can you really test everything we did so far?"),
recorded in .omc/sergio-loop/authorization.json. Production data mutation and history rewrite
remain excluded.

Method: GitOps, one commit per host to its own Gitea stacks repo (giteaer/watchtower,
giteaer/geiserback, giteaer/geiserct), webhook deploying in ~20s each. Nothing edited on a server
directly, so the next deploy cannot revert it.

Pre-flight before touching anything: confirmed /data writable on all three hosts and the
.fernet_key present, because 1.6.0 REFUSES TO START when it cannot persist the encryption key.
Took a hot DB backup first (cashpilot.db.pre-1.6.0.bak, 54 MB).

Verified after:
- watchtower UI + worker, geiserback worker, geiserct worker: all 1.6.0, all healthy. 5 workers
  online and heartbeating. 17 cashpilot containers running.
- UI startup clean — "Application startup complete", no encryption-key refusal.
- Credentials decrypt: 6 encrypted config rows readable, 13 platforms recorded a reading today.
- Migrations landed on the live DB: deployments.spec_encrypted, config.updated_at,
  earnings.fx_rate_usd all present.
- PACKETSTREAM RECOVERED: $2.13 recorded today, its first reading since 2026-07-27, and its
  stored alert is gone. That is the concrete payoff of the upgrade.
- Node identities intact: mysterium 0x55fd4a497237be0591b6c2423cde0e325398b6a8, anyone-protocol
  ed25519_master_id_secret_key present.
- New endpoints registered: /api/credentials/health, /api/earnings/flatlines,
  /api/services/{slug}/preflight.

Rollback if ever needed: pin the tag back to 1.4.x in the host's stacks repo and push; the images
are still published and /data was untouched by the image change.

**Counters:** iteration 3, no_progress 0, failures 0.

**Next action:** bead f5u (P1) — net profit rather than gross, power cost first-class.

## 2026-08-02T13:29:11Z — sergio-loop segment 1, iteration 4

**f5u implemented (PR #161) and deliberately NOT merged.** CodeRabbit reviewed it properly for
once and found five issues; two make the reported figures wrong, which in a feature about
reporting money honestly is disqualifying:

- power.summarise reports per-service `net == gross` when no tariff is configured. The TOTALS are
  right (cost_known false, total_net None) but the rows render gross as net — the exact failure
  the bead exists to prevent, in my own code, against my own stated rule.
- api_earnings_net subtracts a window-scoped cost from get_earnings_per_service(), which returns
  the latest BALANCE rather than earnings over the window. A 30-day cost against a lifetime
  balance is meaningless.

Three more, all real: stopped containers inflate container_count; every worker is collapsed into
one count and one host TDP, so a 3-host fleet is charged one idle floor and is_metered cannot be
applied per worker; no error boundary around worker-status data.

Held rather than merged, recorded in docs/DEFERRED-QUESTIONS.md. Fixing 1 and 2 needs a
window-scoped earnings query and per-worker attribution — real work, not a patch on the diff.

**Counters:** iteration 4, no_progress 0 (the review outcome is progress: it stopped a wrong
feature reaching users), failures 0.

**Next action:** rework #161 — per-service None when the tariff is unknown, window-scoped
earnings, per-worker power attribution, running-only containers, error boundary. Then b4e.

## 2026-08-02T13:32:18Z — sergio-loop segment 1, iteration 5

**Reworked PR #161 (f5u).** Four of five review findings fixed and verified; the fifth is
explicitly deferred rather than quietly dropped.

Fixed:
- Per-service net equalled gross when no tariff was configured. Totals were right; the ROWS were
  not. Now cost/net are None per service with cost_quality "unknown", and nothing is flagged
  negative on an unknown cost. This was the feature's own rule broken in its own code.
- Net was computed against the latest BALANCE (a running total), so a 30-day electricity cost was
  charged against a lifetime of earnings. New database.get_earned_by_platform(days) sums
  per-platform deltas over the window, clamped per platform exactly as the dashboard does
  (CashPilot-glc), so a payout does not read as negative earnings.
- Stopped containers inflated container_count, shrinking each running service's share of the idle
  floor and understating cost. Filtered on status == running.
- No error boundary: a worker-status failure could take out earnings figures that come from the
  database and are still reportable.

Deferred, stated on the PR: per-worker power attribution. All workers still collapse into one
count and one host TDP, so a multi-host fleet is charged one idle floor and power.is_metered
cannot be applied per worker. Needs the worker grouping carried through to the watt calculation —
its own reviewable diff, not a rushed addendum.

Verification: ruff clean; 1520 passed; coverage 93.67%.

**Counters:** iteration 5, no_progress 0, failures 0.

**Next action:** await CI + CodeRabbit on #161; then per-worker attribution, then b4e.

## 2026-08-02T13:38:45Z — sergio-loop segment 1, iteration 6

**PR #161 (f5u) merged.** All checks green, no review running, all threads resolved afterwards.
Added endpoint tests first — codecov flagged that the module was covered but the endpoint around
it was not, which is where config parsing, the running-only filter and the error boundary live.
1525 passed, coverage 94.30%.

**Backlog reconciled.** Closed the 13 beads shipped and merged this session with their PR numbers:
1ii, efx, tkd, 964, glc, aug, kbs, qkc, kct, jz3, w58, 6rv, f5u. Open is now 18, of which 3 are
the v2.0.0 wallet tiers (luj, dv6, e8u), so 15 remain for 1.x.

**Filed CashPilot-yh5 (P2)** for the deferred half of f5u rather than losing it: the cost is
computed fleet-wide, so a three-host fleet is charged ONE idle floor, and power.is_metered cannot
be applied per worker — meaning a mixed fleet of home servers and VPSes is billed as though every
machine were metered. _get_all_worker_containers already groups by worker; api_earnings_net
discards that grouping before the watt calculation.

**Counters:** iteration 6, no_progress 0, failures 0.

**Next action:** bead b4e (P2) — producer-state detection (Producing / Idle / Failing), which
pairs naturally with the flatline work already shipped.

## 2026-08-02T13:45:05Z — sergio-loop segment 1, iteration 7

**PR #162 (yh5) merged; bead closed.** Power is now charged per worker rather than once for the
whole fleet. This mattered concretely for Sergio's three-host setup: it was being charged ONE
machine's idle floor, understating idle cost roughly threefold, and power.is_metered could not be
applied at all — so a VPS would have been billed like a home server. Each worker now contributes
its own container count, host TDP (from system_info, default as fallback) and metered flag; an
unmetered host is skipped rather than costed and zeroed; a service on several hosts accumulates
from each. Tests assert the arithmetic: two hosts cost twice one host, unmetered contributes zero,
a 200W server is not costed as a 65W mini PC. 1529 passed, coverage 94.30%.

**Counters:** iteration 7, no_progress 0, failures 0.

**Next action:** bead b4e (P2), producer-state detection. NOTE FOR THE NEXT SESSION: this session
has run very long and the last few iterations needed repeated attempts at simple test patches,
which is the signal that context is spent. b4e deserves fresh context rather than another push
here — the value of this loop has come from verifying claims against code and catching wrong
numbers before they shipped, and that standard is what degrades first.

## 2026-08-02T13:50:39Z — sergio-loop segment 1, iteration 8 (segment end)

**v1.7.0 released and the UI deployed.** Brings f5u (net profit) and yh5 (per-worker power) to
the fleet. Verified live: UI healthy on 1.7.0, /api/earnings/net registered, zero encryption-key
refusals at startup, 13 platforms reporting today, 6 encrypted config rows still readable.

**Workers deliberately left on 1.6.0.** No worker code changed since v1.6.0, so the release
correctly skipped build-worker and there is no 1.7.0 worker image. UI 1.7.0 + worker 1.6.0 is
exactly what the build system intends.

**FOUND A REAL P1 WHILE DOING IT — CashPilot-0zw.** The release publishes only images whose source
changed, but the example compose pins BOTH images to the same major.minor tag (jz3) and
tests/test_compose_image_pins.py ENFORCES that they match. So on any release where one image is
rebuilt and the other is not, following our own documented pinning produces a compose file
referencing a tag that does not exist, and docker compose pull fails. The rule and the build
contradict each other and the test enforces the broken side. Verified concretely:
cashpilot:1.7.0 exists, cashpilot-worker:1.7.0 and :1.7 do not.

Preferred fix recorded on the bead: retag unchanged images on release (a manifest operation, not a
rebuild) so every version has both images and same-tag pinning stays valid. Explicitly NOT
"always rebuild both" — building an unchanged multi-arch artefact to satisfy a naming convention
is the wrong trade. Plus a release-time check that every tag the example compose references
actually resolves; CI passed happily while this was broken, and only deploying caught it.

**Counters:** iteration 8 of 8 — segment budget reached. no_progress 0, failures 0.

**Stop state: BUDGET.** Not blocked and not failed: 14 1.x beads remain and all are workable.
Resume with sergio-loop --continue.

**Next action:** CashPilot-0zw (P1, the tag-skew bug — it makes the documented quickstart fail),
then b4e.

## 2026-08-02T14:34:28Z — segment 2, iteration 1

**CashPilot-0zw shipped (PR #163) and closed.** Releases now publish BOTH images: an unchanged one
is re-pointed at the new tags with buildx imagetools (a manifest operation, seconds, not a rebuild)
rather than rebuilding a multi-arch artefact to satisfy a naming convention. verify-tags then fails
the run if any tag the release claims does not resolve — the gap that let v1.7.0 ship with
cashpilot:1.7.0 present and cashpilot-worker:1.7.0 absent while CI stayed green.

CodeRabbit caught that the three new run blocks interpolated inputs.version-derived tags straight
into `for tag in ...`, in steps running after the registry login. Fixed by passing them through
env and reading them as data.

That fix exposed a second bug of my own in verify-tags: a `while` on the right of a pipe runs in a
subshell, so `missing=1` never reached the check — the gate would have passed silently on a
missing tag, the exact failure it exists to catch. And the `[ -s file ] && missing=1` I first
reached for would have failed the step under `bash -e` on the HAPPY path. Rewritten to read from a
file with a redirect; simulated locally against real Docker Hub tags before pushing.

**Counters:** segment 2, iteration 1, no_progress 0, failures 0.
**Next action:** bead b4e (P2), producer-state detection.

## 2026-08-02T14:38:46Z — segment 2, iteration 2

**CashPilot-b4e shipped as PR #164.** Producer state as a verdict SEPARATE from container health,
because health is computed from restarts and crashes and a container producing nothing for a month
still scores 100/100.

Two of the three signals: earnings movement over a trailing window (services with a collector), and
health_signals — log regexes declared in the service YAML with a plain-language 'means' and a
state. The YAML signal is the only one available for the 30+ services with no collector, and it
keeps service-specific knowledge out of app/ per the architecture rule.

The important behaviour is what it refuses to claim: a service with no collector reads UNKNOWN,
never IDLE. Saying "idle" when the earnings simply cannot be seen is the same false confidence the
feature exists to remove. Too little history is UNKNOWN; a stopped container is not judged. Every
verdict carries reasons. A concrete log diagnosis outranks an earnings observation, so "login
failed" beats "earnings moved" — the log says why.

NO catalog entries declare health_signals yet, deliberately: a guessed regex that never matches is
dead weight, one that matches the wrong line tells the user something false, and populating them
needs real log samples per service. A test fails if a declared pattern does not compile or has no
'means'.

Endpoint tests written UP FRONT this time — four earlier PRs failed codecov/patch for exactly the
omission of endpoint coverage. 1556 passed, coverage 94.38%.

Deferred and stated on the PR: the third signal, container network rx/tx counters, which needs
those figures wired through the Docker worker heartbeat (the bead calls this the bulk of the work).

**Counters:** segment 2, iteration 2, no_progress 0, failures 0.
**Next action:** await CI/CodeRabbit on #164 and merge; then 66x (per-service transparency).

## 2026-08-02T12:40:00Z — sergio-loop segment 2, iteration 4

**Slice:** CashPilot-66x — per-service disclosure ("is this malware?").

**Changed:** `app/disclosure.py` (new), `app/main.py` (2 endpoints), `services/_schema.yml`,
`tests/test_disclosure.py` (new, 22 tests), and verified `disclosure:` blocks on 4 services
(mysterium, anyone-protocol, proxybase-xyz, storj).

**Design decision worth recording:** the module is built around the *absent* answer, not the
present one. An undocumented service reports `documented: false` and states plainly that this is
not a claim of safety; `routes_third_party_traffic()` is three-valued so "not documented" cannot
collapse into "no". 46 of 50 services are deliberately left undocumented rather than guessed, and
`/api/disclosure/coverage` enumerates that gap.

**Verification:** `ruff check .` clean · `ruff format --check .` 84 files clean ·
`pytest --cov=app --cov-fail-under=90` → **1578 passed**, coverage **94.44%**. Endpoint tests
written up front (the omission that failed codecov/patch on four earlier PRs).

**Counters:** iteration 4, no_progress 0, failures 0.

**Next action:** CashPilot-5qc.
