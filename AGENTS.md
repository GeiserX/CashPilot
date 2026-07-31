# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [SYNC_CONCEPTS.md](https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

## Operating a live fleet — hazards that look fine from outside

Failure modes that are easy to trigger, expensive or impossible to undo, and
invisible from the dashboard: in each case the earning containers keep running, so
nothing prompts you to look. Read this before changing anything on a running fleet.

### Never bulk-redeploy services to "apply" new container settings

A release that adds container hardening (`cap_drop`, `no-new-privileges`,
`pids_limit`, ...) only affects containers created **after** it, because Docker
fixes `HostConfig` at creation time. The obvious next step — redeploy everything so
it takes effect — can permanently destroy node identities.

A redeploy rebuilds the spec from the **catalog YAML**. If a service was originally
deployed with different storage than its catalog entry declares, redeploying
silently swaps it. The common case: a service running on a **bind mount** whose
catalog entry declares a **named volume**. The new container gets a fresh, empty
volume and the old data is simply no longer attached.

Harmless for stateless bandwidth services. Not harmless for anything holding an
identity:

| Service kind | What is lost | Recoverable? |
|---|---|---|
| Mysterium / MystNodes | node keystore -> new identity | No: re-registration, reputation reset |
| Storj | node identity -> forfeits held amount | No |
| Anyone Protocol | relay keys -> new relay, reputation reset | No |
| URnetwork and similar | persisted auth / JWT | Only by logging in again |

Catalog entries that interpolate environment variables (e.g.
`${IDENTITY_DIR}:/app/identity`) are equally dangerous: if the variable is unset at
deploy time the mount does not resolve to the original location.

**Always compare before redeploying:**

```bash
# What is mounted right now
docker inspect cashpilot-<slug> \
  --format '{{range .Mounts}}{{.Type}} {{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}} -> {{.Destination}}
{{end}}'

# What the catalog would create instead
docker exec cashpilot-ui python -c "
from app import catalog; catalog.load_services()
print((catalog.get_service('<slug>').get('docker') or {}).get('volumes'))"
```

A `bind` on the left against a bare `name:/path` on the right means **do not
redeploy that slug**. Same for any `${VAR}` you cannot prove is set.

**Safe remedy:** recreate the container *in place* rather than redeploying from the
catalog. Read the running container's image, env, mounts, ports, labels and restart
policy from `docker inspect`, then recreate it identically, adding only the new
security flags. The original mounts stay attached and no UI login is needed. Canary
one stateless service and confirm it returns healthy before continuing.

The durable fix is to make deployed storage and catalog agree — either redeploy that
service deliberately once, where an identity reset is acceptable, or keep the bind
mount and never redeploy that slug from the catalog.

### A recreated worker can lose its identity (fixed in 1.4.2)

**Symptom:** after an image bump, every heartbeat returns `401 Unauthorized` and the
worker disappears from the fleet view — while its service containers keep earning.

**Cause:** the UI keys a worker's row and its per-worker key on a `client_id`
persisted at `/data/.worker_id`. Before 1.4.2 a worker without that file fell back to
`CASHPILOT_WORKER_NAME`, which defaults to `socket.gethostname()` — inside Docker,
the container short ID, regenerated on every recreate. The worker then presents a
valid key under an id the UI never enrolled, and the UI refuses it. It cannot
self-recover: it authenticates with its existing key, so it can never re-enroll.

**Recovery** (needed on <=1.4.1, or whenever `/data/.worker_id` is missing):

```bash
# The id the UI knows this worker by
docker exec cashpilot-ui python -c "
import sqlite3; c=sqlite3.connect('/data/cashpilot.db')
print([(r[0], r[1]) for r in c.execute('select client_id, name from workers')])"

# Restore it, matching the key file's ownership so the app user can read it
d=<worker /data dir>
printf '<client_id>' > "$d/.worker_id"
chown --reference="$d/.worker_key" "$d/.worker_id"
chmod  --reference="$d/.worker_key" "$d/.worker_id"
docker compose restart cashpilot-worker
```

`docker compose up -d` will **not** reload it while the container is merely
"Running" — the id is read at startup, so restart the container.

Seeding `/data/.worker_id` *before* recreating an older worker avoids the outage
entirely. When diagnosing, note that `workers.name` is the container hostname and
legitimately changes on every recreate — that is cosmetic. Judge identity by
`client_id`, health by `key_confirmed = 1` plus a `200` heartbeat. The column is
`last_heartbeat`, not `last_seen`.

### A green release does not mean both images were published

`release.yml` bumps one tag, but builds the UI and the worker **independently** based
on which paths a merge touched. A worker-only release publishes
`cashpilot-worker:<version>` and no `cashpilot:<version>`. `build-ui: skipped` is a
normal, silent outcome, so the newest git tag may have no image for one component and
the two images legitimately sit on different versions.

Verify against the registry — not the Docker Hub web API, which lags by hours:

```bash
docker manifest inspect -- drumsergio/cashpilot:<version>
docker manifest inspect -- drumsergio/cashpilot-worker:<version>
```

To confirm a fix actually shipped, grep inside the image rather than trusting a green
run: `docker run --rm --entrypoint sh <image> -c "grep -c cap_drop /app/app/orchestrator.py"`.

### Catalog liveness: "could not verify" is not "broken"

`scripts/check_catalog_liveness.py` separates **problems** (`dead` — the catalog is
wrong) from **inconclusive** (`unreachable` — we could not tell). Only problems open
the weekly rollup issue.

A referral link that redirects to the provider's bare homepage is reported
inconclusive **on purpose**: it is indistinguishable from a working link that reads
`?ref=CODE`, stores it in the session, sets a cookie and redirects to a clean URL.
Confirming either way needs an account with that provider.

Never retire a service on that signal alone. Check whether the referral URL is
handled specially first:

```bash
curl -s -o /dev/null -w '%{http_code}\n' 'https://provider.example/'       # bare page
curl -s -D - -o /dev/null 'https://provider.example/?ref=CODE' | head -5    # with code
```

A `302` + `Set-Cookie` on the referral URL where the bare page returns `200` means
the code **is** captured — the link works.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
