# Upgrading to v1.0.0 — Per-worker fleet keys

v1.0.0 hardens fleet authentication. Instead of one shared key doing everything,
**each worker now gets its own key**. This is a breaking change for existing
fleets: worker and UI images must both be on v1.0.0+, and workers re-enroll
automatically on their first heartbeat after the upgrade.

## What changed

| | Before (0.x) | v1.0.0 |
|---|---|---|
| Worker → UI heartbeat | shared `CASHPILOT_API_KEY` | worker's **own** key (after enrollment) |
| UI → worker commands | shared key | that worker's **own** key |
| Role of `CASHPILOT_API_KEY` | authenticates everything | **enrollment/bootstrap only** |

**Why:** with per-worker keys, a key that leaks from one worker only affects that
one worker, and no worker can present another worker's identity to the UI. The
shared key stops being a fleet-wide credential once a worker is enrolled.

## How enrollment works (automatic)

1. A worker's **first** heartbeat authenticates with the shared `CASHPILOT_API_KEY`.
2. The UI issues that worker a unique key — stored **encrypted** on the UI and
   returned to the worker **once**.
3. The worker persists the key under its own private `/data/.worker_key` and uses
   it from then on. The UI addresses that worker with the same key.
4. Once enrolled, the shared key **no longer works** for that worker.

You don't handle keys by hand — this all happens on the next heartbeat.

## Upgrade steps

1. **Upgrade the UI** image to `drumsergio/cashpilot:1.0.0` (or newer).
2. **Upgrade every worker** image to `drumsergio/cashpilot-worker:1.0.0` (or newer).
   Do not leave old-version workers running against a v1.0.0 UI — once the UI has
   enrolled a worker, an old worker image (which only knows the shared key) can no
   longer heartbeat.
3. Keep `CASHPILOT_API_KEY` **unchanged** — it is still needed for enrollment.
4. Restart the containers. Each worker auto-enrolls on its first heartbeat; confirm
   every worker shows **online** in the fleet dashboard.

Persist the worker's `/data` volume (the compose files already do) so its key
survives restarts.

## Recovery & rollback

- **A worker's `/data` was wiped** (lost its key): it will try the shared key, which
  the UI now rejects for an enrolled worker. Re-enroll it by removing the worker in
  the fleet dashboard — it re-registers and enrolls fresh on its next heartbeat.
- **Rolling a worker back to a 0.x image:** first remove that worker in the dashboard
  (clears its enrollment) so the shared key is accepted again, then redeploy the old
  image.

---

## Release notes — v1.0.0

**Per-worker fleet keys.** Every worker now authenticates with its own automatically
issued key instead of a single shared secret. The shared `CASHPILOT_API_KEY` becomes
an enrollment-only bootstrap credential: a worker uses it once, receives its own key,
and uses that thereafter — in both directions. A leaked worker key is now scoped to a
single worker, and workers can no longer impersonate one another.

**Breaking:** existing fleets must upgrade both UI and worker images to v1.0.0 and let
workers re-enroll (automatic on first heartbeat). See the upgrade guide above.

!!! note "The shared key is still sensitive"
    `CASHPILOT_API_KEY` is now an *enrollment* credential, not a fleet-wide command
    key — but it remains high-value: anyone holding it can enroll a new worker that
    then receives deploy specs (which carry service credentials). Keep protecting it.
