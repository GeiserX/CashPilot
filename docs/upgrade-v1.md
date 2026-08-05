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
   Do not leave old-version workers running against a v1.0.0 UI. An old worker
   image only knows the shared key and cannot persist the one it is issued, so it
   never finishes enrolling: for the first 24 hours it keeps heartbeating on the
   shared key — which means anyone holding `CASHPILOT_API_KEY` can impersonate it
   for that long — and after that it is refused and goes offline. The fleet page
   marks such a worker **enrollment incomplete**.

   The same thing happens to a current worker image whose `/data` is read-only or
   is not a persistent volume, because it has nowhere to keep `/data/.worker_key`.
   To recover one: fix the image or the volume, then remove the worker in the
   fleet page so it enrolls again from scratch.
3. Keep `CASHPILOT_API_KEY` **unchanged** — it is still needed for enrollment.
4. Restart the containers. Each worker auto-enrolls on its first heartbeat; confirm
   every worker shows **online** in the fleet dashboard.

Persist the worker's `/data` volume (the compose files already do) so its key
survives restarts.

## Recovery & rollback

- **A worker's `/data` was wiped** (lost its key): it will try the shared key, which
  the UI now rejects for an enrolled worker. Remove the worker in the fleet
  dashboard and it re-enrols on its own: the worker keeps sending the key it
  persisted, and after roughly ten consecutive rejections it discards that key
  and re-enrols with the shared one. Expect a few minutes of 401s in the worker
  log while that plays out. To skip the wait, delete `/data/.worker_key` on that
  host and restart the container.
- **Rolling a worker back to a 0.x image:** remove that worker in the dashboard,
  wait for it to re-enrol (or delete `/data/.worker_key` on the host), then
  redeploy the old image.

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
