# Upgrading CashPilot

**Read this before upgrading.** Only releases that need you to *do* something are
listed here. If a version is not mentioned, `docker compose pull && docker compose up -d`
is all it needs.

[CHANGELOG.md](CHANGELOG.md) carries the detailed notes recorded so far — it is
**not** a complete release history, so do not treat it as the authoritative list
of what an upgrade requires. This file is: what breaks, who it affects, and what
to type.

**Always upgrade the UI and every worker to the same version.** The compose files
pin both images to the same tag for exactly this reason.

**Back up `/data` first.** `cashpilot.db` holds your earnings history and
`.fernet_key` decrypts every stored credential — without that key they cannot be
recovered. See [Backing up node identities](docs/backup.md) for the rest.

---

## v1.11.30 — the shared fleet key stops working for a worker that never enrolled

**Affects you if** a worker appears in your fleet but has never confirmed its own
key. On the Workers page these now show an **"enrollment incomplete"** badge. If
every worker shows a normal *Last seen* time and no badge, **no action is
required**.

In practice this means: a worker running a pre-1.0.0 image, or one whose `/data`
is read-only or is not a persistent volume, so it cannot keep the key it was
issued. It also affects **the Android app before v0.2.0**, which did not persist
its per-worker key.

**What changed.** `CASHPILOT_API_KEY` is the shared *enrollment* key. Once a
worker has been issued its own key, the shared one is meant to stop working for
it — that is the entire point of per-worker keys. Until now, a worker that never
confirmed kept the shared key valid for its identity **forever**, and the UI
re-sent that key to whoever held it every 60 seconds. The window is now bounded
at **24 hours from the moment the key was issued**.

**What breaks if you do nothing.** Such a worker starts receiving `401` on its
heartbeat and disappears from the dashboard. Containers it manages keep running
and keep earning — you simply stop seeing and controlling them.

**What to do.** Give the worker somewhere to keep its key, then let it enrol
again:

1. Upgrade that worker to `1.0.0` or newer.
2. Make sure `/data` is a **writable, persistent** volume, not a tmpfs and not
   read-only.
3. **Keep `/data/.worker_id`.** It is the worker's identity, read once at
   startup. If it is missing, the worker registers under a brand-new id and you
   get a duplicate row in the fleet rather than the same machine re-enrolling.
   Before recreating the container, make sure the file exists and is owned by
   the container user:

   ```bash
   ls -l /path/to/worker/data/.worker_id
   chown 1000:1000 /path/to/worker/data/.worker_id
   ```

4. Remove the worker on the fleet page, then **restart the container** — the
   identity is read at startup, so `docker compose up -d` on an already-running
   container does not re-read it:

   ```bash
   docker compose restart cashpilot-worker
   docker logs cashpilot-worker | grep -i enrol
   ```

   It writes `/data/.worker_key` once enrolled. Confirm that file exists.
5. For the **Android app**, update it to **v0.2.0 or newer** — earlier builds
   cannot persist the key at all.

Existing, already-enrolled workers are untouched: they authenticate with their
own key, which does not expire.

---

## v1.11.4 — the example compose files pin a release series

**Affects you if** you copied `docker-compose.yml` from the repo and are relying
on it tracking the newest build. Your existing deployment is **unaffected until
you edit your compose file** — nothing changes underneath you.

**What changed.** The examples pin `1.11` instead of `latest`, so following the
quickstart gives you a known version rather than whatever was pushed most
recently.

**What to do.** Nothing. If you want a different version, pin an explicit one —
`drumsergio/cashpilot:1.12.0` — rather than a floating tag. `:latest` is not
supported: it makes the version you are running unknowable, which is what
produced a months-old bug report against a bug that had already been fixed.

---

## v1.5.0 — CashPilot refuses to start if it cannot persist its encryption key

**Affects you if** your `/data` is not writable. **No action is required** if it
is a normal bind mount or volume.

**What changed.** Credentials are encrypted with a key at `/data/.fernet_key`. If
that could not be written, CashPilot used to carry on with a key that died with
the process — so everything encrypted during that run became unreadable on the
next restart. It now refuses to start instead.

**What breaks if you do nothing.** The container exits at startup with an error
naming the path.

**What to do.** Fix the mount so `/data` is writable. If a throwaway instance is
genuinely what you want, set `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` and accept that
stored credentials will not survive a restart.

**Back up `/data/.fernet_key`.** Without it, stored credentials cannot be
decrypted — not by you, and not by us.

---

## v1.0.4 — the dashboard binds to loopback by default

**Affects you if** you reach the dashboard from another machine on your LAN and
you use the shipped compose file. **No action is required** if you browse from
the host itself, or if you front it with a reverse proxy on the same machine.

**What changed.** The compose files bind the dashboard — and, in the fleet
compose, the Docker-socket worker — to `127.0.0.1` instead of `0.0.0.0`. The
worker has the Docker socket, which is root-equivalent on the host, so publishing
it to the whole network by default was the wrong default.

**What breaks if you do nothing.** The dashboard stops answering on the LAN
address you were using.

**What to do.** Set `CASHPILOT_BIND_ADDR` to `0.0.0.0`, or better, to the one
interface you actually want it on:

```bash
CASHPILOT_BIND_ADDR=192.168.1.10 docker compose up -d
```

**On a single-host install**, leave the worker on loopback. Only the UI needs to
reach it, and it does so over the Docker network.

**On a fleet**, a remote worker must be reachable by the UI, and it uses a
*different* variable — `CASHPILOT_WORKER_BIND_ADDR` in `docker-compose.fleet.yml`.
Left on loopback, a remote worker is unreachable and its containers become
unmanageable. Bind it to the interface the UI reaches it on — a tailnet address
rather than `0.0.0.0`, since that port carries the Docker socket API:

```bash
CASHPILOT_WORKER_BIND_ADDR=100.x.y.z docker compose up -d
```

---

## v1.0.0 — per-worker fleet keys

A full cutover with its own page: **[Upgrade to v1.0.0](docs/upgrade-v1.md)**.

In short: every worker is issued its own key on first heartbeat and uses it
thereafter; `CASHPILOT_API_KEY` becomes an enrollment credential only. Keep it
set — enrollment still needs it. Upgrade the UI first, then every worker.

---

## Everything else

No action required. Pull and recreate:

```bash
docker compose pull && docker compose up -d
```

**On a fleet, run that on every host.** It only updates the Compose project it
runs in, so remote workers stay on their old version until you upgrade them too —
and the UI and workers are meant to be on the same release.
