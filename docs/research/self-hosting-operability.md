# What a self-hosting operator hits

A review of the gaps between "CashPilot runs" and "an operator can look after it
for a year". Written after upgrading a live five-server fleet from 1.10.1, and
every claim below was checked against the repository as it stands rather than
against that deployment — which matters, because **two of the seven concerns
turned out to be true of the deployment and not of the shipped project.**

Each item states what the operator hits, the evidence, the smallest change that
would help, and what it costs.

---

## 1. Nothing tells an operator they are behind

**What they hit.** A fleet sat **33 releases** behind and nothing anywhere said
so. Not the dashboard, not a log line, not the fleet page.

**Evidence.** The UI already computes drift *between itself and its workers* —
`app/main.py` sets `w["version_skew"] = version.skewed(...)` per worker. It has
no idea what the latest published release is: nothing under `app/` mentions
`api.github.com`, `releases/latest`, or any equivalent.

So the machinery for "these two versions differ" exists and is used; the missing
half is a reference point outside the deployment.

**Smallest change.** A once-a-day fetch of the newest tag, cached, surfaced as a
dismissible banner. Three constraints, all of which are the difference between a
useful feature and an unwelcome one:

- **Degrade silently offline.** An air-gapped or firewalled install must not show
  an error, a spinner, or a warning about the check itself. Unknown is unknown.
- **Never auto-update.** This deploys containers and holds credentials. It tells
  you; you decide.
- **Dismissible per version**, or it becomes wallpaper and stops being read.

**Cost.** Small: one scheduled job, one cached value, one banner. The judgement
is in the failure modes, not the fetch.

**Highest value of anything here** — it is the only item that turns an invisible
problem into a visible one.

---

## 2. No upgrade precheck, and no way to know whether a migration ran

**What they hit.** Upgrading meant checking by hand that both images existed at
the target tag, taking a database backup, and reasoning unaided about whether
the schema would migrate.

**Evidence.** Migrations are applied on startup and are careful — `app/database.py`
guards column changes behind `PRAGMA table_info` — but **nothing reports what
happened.** There is no schema-version log line and no startup summary. An
operator watching `docker logs` cannot tell a clean start from one that just
rewrote the earnings table.

**Smallest change.** One log line at startup: the schema version, and whether a
migration ran on this boot. That is a few lines of code and it converts "I hope
that worked" into something greppable and pasteable into a bug report.

**Cost.** Very small. Worth doing on its own merits.

---

## 3. Image tag skew is a known footgun

**What they hit.** Pinning the UI and worker independently, and ending up with a
mismatched pair.

**Evidence.** `build.yml` carries a `verify-tags` job precisely because a release
once published one image and not the other, and `release.yml` now builds both on
every release with a long comment explaining why re-tagging was wrong.

The compose files pin both to the same series, so following the quickstart is
safe. The risk is entirely for operators who pin by hand.

**Smallest change.** Documentation: say that the two images are released as a
pair and must be pinned to the same tag. No code.

**Cost.** Trivial.

---

## 4. The images have healthchecks; the compose files do not use them

**What they hit.** No documented way to be told a container is unhealthy without
building the alerting yourself.

**Evidence, and this one is sharper than the original concern.** Both images
declare `HEALTHCHECK` (`Dockerfile:56`, `Dockerfile.worker:71`) — so Docker knows
the health state. But **neither shipped compose file mentions `healthcheck` at
all** (zero matches in both), and `restart: unless-stopped` restarts on *exit*,
not on *unhealthy*. A container that is up and failing its own healthcheck stays
up, silently, forever.

So the image-level work is done and nothing consumes it.

**Smallest change.** Two things, in order of value:

1. Document a minimal Prometheus + Alertmanager recipe against the `/metrics`
   endpoint that already exists.
2. Show, in the compose comments, how to act on the healthcheck the image already
   declares.

**Cost.** Small, and mostly documentation.

---

## 5. Memory limits — the concern was about the deployment, not the repo

**Corrected.** The seed recorded `mem_limit: 256m` on the UI. **The shipped
compose files set no memory limit at all** — both carry only a commented-out
`deploy: resources:` block. That limit was local to the live fleet.

The useful residue is still real: nobody has measured what the UI actually needs
under a collection cycle with a 56 MB database, APScheduler in-process, and
collectors running. An operator who sets a limit is guessing, and an OOM here
presents as *"collection randomly stops"* — the hardest class of failure for a
user to notice, let alone report.

**Smallest change.** Measure RSS across a full collection cycle, then document a
floor with the measurement beside it. Do not ship a limit; ship a number and its
provenance.

**Cost.** An afternoon of measurement. No code.

---

## 6. No documented restore path

**What they hit.** Backing up *node identities* is documented (`docs/backup.md`).
Restoring the UI's own `/data` is not.

**Evidence.** `.fernet_key` is mentioned across `docs/security-defaults.md`,
`docs/configuration.md` and `docs/fleet.md`, always in passing. There is no page
that says: here is what to copy, here is how to put it back, here is what breaks
if you do not.

**Losing `.fernet_key` makes every stored credential permanently undecryptable.**
The code says so in three places. That is the single most destructive thing an
operator can do to this application, and it is documented only as an aside.

**Smallest change.** One page: what `/data` contains, the two files that matter
(`cashpilot.db`, `.fernet_key`), a copy-paste backup command, the restore, and an
explicit statement of what is unrecoverable without the key.

**Cost.** Small, and the highest documentation value here.

---

## 7. Worker data directory — also about the deployment, not the repo

**Corrected.** The seed recorded the UI and worker sharing one `/data`, so the
component holding the Docker socket could read `.fernet_key` and the credential
store.

**The shipped compose files already separate them.** `docker-compose.yml` and
`docker-compose.fleet.yml` both mount `cashpilot_data:/data` on the UI and
`cashpilot_worker_data:/data` on the worker, declared as distinct volumes. They
share only `cashpilot_fleet:/fleet`, which holds the shared enrollment key both
components need by design.

So this was a property of the live fleet. What is missing is the *reason*: nothing
says why they are separate, which is exactly the kind of thing someone
consolidates while "simplifying" a compose file.

**Smallest change.** A comment in both compose files and a line in the fleet docs:
the worker has the Docker socket, which is root on the host; it must not also be
able to read the credential store. Plus a test that fails if the two volumes are
ever collapsed into one.

**Cost.** Trivial, and it protects a real boundary.

---

## What to do, in order

| | Item | Kind | Value |
|---|---|---|---|
| 1 | Startup log line: schema version + whether a migration ran | code, tiny | high |
| 2 | Restore page for `/data` and `.fernet_key` | docs | high |
| 3 | Separate-volumes rationale + a test pinning it | docs + test | high |
| 4 | "You are N releases behind" banner | code | highest, largest |
| 5 | Alerting recipe against `/metrics`, and acting on the healthcheck | docs | medium |
| 6 | Measure the UI's real memory floor and publish the number | measurement | medium |
| 7 | Say the two images are released as a pair | docs | low, trivial |

Items 5 and 7 of the original seven were about the live fleet rather than the
project, and are recorded above as corrections rather than as work.
