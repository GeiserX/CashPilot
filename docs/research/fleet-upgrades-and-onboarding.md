# Fleet upgrades and server onboarding — design

Status: **proposal** (CashPilot-t5ja). Nothing here is built yet except the
prerequisite fix in `_find_container` (managed-label guard). This document is
the contract the implementation will be reviewed against.

Two chronic operational papercuts share one design surface:

1. **Worker version skew.** Upgrading a worker means SSH-ing into the server
   and editing a compose file, so fleets drift: workers a full series behind
   their UI are the norm, not the exception. The dashboard warns about skew but
   offers no action.
2. **Adding a server.** Today the fleet page prints three environment variable
   lines; everything else — writing the compose file, running it — happens over
   SSH, by hand, from documentation.

The design principles, in order of precedence:

* **The operator's pipeline is sovereign.** Anyone running GitOps must be able
  to keep CashPilot strictly read-only about its own fleet. The existing update
  banner's contract — *announce, never act* — extends per worker and stays the
  default.
* **No stored credentials that widen a UI compromise.** The UI already commands
  Docker sockets on every enrolled server through the worker API. Adding SSH
  credentials to that same box would turn "UI compromised" into "root on every
  server, including ones with no worker". We refuse that trade.
* **A worker's identity must survive its upgrade.** `/data` holds the
  per-worker key and client id; losing either locks the worker out (this
  happened in production — an image bump minted a new client id and 401'd
  forever).

---

## Part A — Worker upgrades

### A per-worker `upgrade_mode`

A new per-worker setting, stored exactly like the existing `watts` /
`dedicated` settings (config table, `worker_{client_id}_upgrade_mode`, written
through the owner-gated `/api/config` path — no schema migration, survives
re-enrolment):

| Mode | Meaning |
|---|---|
| `announce` (**default**) | The fleet page shows "vX.Y.Z available" next to the worker. Nothing is ever done to any container. This is the GitOps mode, and it is the default precisely so that managed behaviour is always an explicit opt-in per worker. |
| `managed` | The UI may offer (and the owner may click) "Upgrade worker to vX.Y.Z". The worker performs its own upgrade via the sidecar mechanism below. |

Design detail carried over from the skew work: today the fleet page compares a
worker to the *UI's own* version. Announce mode needs the latest *published
release* as a second reference (already cached daily by the update check), so a
worker can show "behind the UI" and "behind latest" independently, and an
Android client keeps being judged against Android releases only.

### Managed mode: how a worker upgrades itself

A container cannot recreate itself: the existing deploy path force-removes the
old container before creating the new one, and when the old container *is* the
worker, the process dies mid-call and nothing creates the replacement. The
`restart: unless-stopped` policy cannot save a container that was removed
rather than stopped.

So managed mode uses a **short-lived upgrader sidecar**:

1. UI → worker: the upgrade order rides the **heartbeat response** — the one
   channel a worker is already authenticated on — as
   `{"upgrade": {"target": "v1.26.0"}}`. No new endpoint, no new credential.
   The UI only sets this field when the worker's mode is `managed` AND the
   owner explicitly clicked the upgrade action for that worker and version;
   it is an order, not standing state.
2. The worker validates the target (well-formed release tag, same MAJOR —
   cross-major upgrades always stay manual), pulls
   `drumsergio/cashpilot-worker:<target>` (the worker already has full image
   pull capability), and starts the sidecar: a container from the *new* image
   whose entrypoint is the upgrade script, labelled
   `cashpilot.role=upgrader`, given the Docker socket and nothing else.
3. The sidecar reads the running worker's container config (env block,
   volumes including `/data`, name, network, port bindings — verbatim), stops
   and removes the old worker, creates the new one from the same config with
   the new image, waits for its `/api/health` to answer, and exits. On a
   failed health check it recreates the worker from the previous image tag
   (kept for exactly this purpose) so a bad release cannot strand a remote
   server, then reports the failure in the next heartbeat.
4. The UI shows the outcome from what it can actually observe: the next
   heartbeat's reported version. No heartbeat within a timeout → the worker is
   flagged unreachable with "upgrade may have failed" and the operator gets
   the sidecar's log path.

Invariants the implementation must keep, each with a test:

* `announce` mode provably never mutates containers — the negative control is
  a worker in announce mode receiving a hand-crafted upgrade order and
  refusing it (the worker checks its own mode; the UI not sending is policy,
  the worker not obeying is enforcement).
* The generic deploy path's refusal to mount `/var/run` stays intact. The
  sidecar is a separate, worker-initiated code path; the UI cannot inject a
  spec into it — it only ever names a version tag, and the tag is validated
  against the release-tag grammar before use.
* The upgrade never crosses a MAJOR version automatically.
* `/data`, the container name, and the env block survive byte-for-byte; the
  post-upgrade heartbeat must authenticate with the SAME per-worker key.
* The `_find_container` managed-label guard (shipped ahead of this design)
  keeps the ordinary command channel unable to touch the worker or UI
  containers; the sidecar is the only code that may operate on the worker's
  own container, and it does so by container id, not by slug lookup.

### What about the UI container itself?

Out of scope, deliberately. The UI hosts the upgrade orders; letting it order
its own replacement invites the same chicken-and-egg with fewer safety nets,
and the UI is one container on one server the operator already touches. The
existing banner (announce-only) remains the UI's own upgrade story.

---

## Part B — Adding a server from the UI

### The auth options, examined honestly

**1. Generated bootstrap command (chosen as the default path).**
The UI generates a complete, copy-paste `docker run` (and a compose block) for
the new server: image pinned to the current release, `CASHPILOT_UI_URL`
prefilled with the reachable URL, enrollment key inline, worker name chosen in
the wizard, bind address guidance. The operator pastes it into any shell they
already have on the target server.

* Stored credentials added to the UI: **none**.
* New attack surface: **none** — this is the existing enrollment flow with the
  human error removed.
* Works everywhere Docker works, regardless of how the operator reaches the
  server (SSH, console, Portainer, whatever).

The wizard then **watches enrollment live**: the moment the new worker's first
heartbeat arrives, the wizard flips to "enrolled — key issued", using the
enrollment state machine that already exists. The user never leaves CashPilot
except to paste one line into a terminal they already own.

**2. Scoped enrollment tokens (second phase, recommended).**
Today the bootstrap command necessarily embeds the long-lived shared fleet
key. A generated **single-use, expiring enrollment token** (accepted only for
first contact, exchanged for the per-worker key exactly like the shared key is
today) removes the last uncomfortable property: a pasted-somewhere bootstrap
command stops being a forever-credential. The shared key then matters only as
a break-glass.

**3. SSH from the UI — considered and rejected.**
Every variant was weighed: operator-pasted private key, UI-generated keypair
with the public key installed by the operator, password exchanged for a key at
first use. All of them fail the same test: the UI would hold credentials that
grant **root on servers, beyond the worker's own API**, so a UI compromise
escalates from "can command enrolled workers' Docker" to "owns every machine
it was ever given". Additional costs: an SSH client stack where none exists
today, host-key verification UX, reachability assumptions (NAT, VPNs), and a
credential-lifecycle story (rotation, revocation, audit) that the bootstrap
path simply does not need. If a future need arises (e.g. headless bare-metal
provisioning), it must be a separate opt-in component with hardware-token
gating — not a default path, and never stored alongside the fleet database.

**4. Remote Docker socket / Docker context — rejected outright.**
Publishing a Docker socket over TCP is the exact thing the security notes warn
against; the worker API exists to avoid it.

### The wizard, concretely

"Add server" on the fleet page becomes a three-step guided flow:

1. **Name and network** — worker name, expected network type
   (residential/hosting, feeding the existing egress logic), reachable UI URL
   (validated against the request's own host as a sane default).
2. **Run this on the server** — the generated `docker run` + compose block,
   copy buttons, with the enrollment credential shown once (masked by
   default, reveal audit-logged like the existing key reveal).
3. **Waiting for first heartbeat…** — live status from the enrollment state
   machine: contact → key issued → key confirmed. Errors surface here with
   their fix (wrong UI URL, firewalled port, clock skew), instead of the
   current silence.

---

## Rollout

| Phase | Ships | Risk |
|---|---|---|
| 1 | Per-worker announce (latest-release reference on the fleet page), `upgrade_mode` setting, Add-server wizard with generated bootstrap + live enrollment | Low — read-only plus UI |
| 2 | Managed self-upgrade via sidecar, rollback, health-gated | Medium — new privileged worker code path, ships behind the per-worker opt-in |
| 3 | Scoped enrollment tokens | Low — additive auth tightening |

Each phase is its own bead and PR; phase 2 does not start until phase 1's
announce contract has a negative-control test in CI.
