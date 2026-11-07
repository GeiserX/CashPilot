# Upgrading CashPilot

**Read this before upgrading.** Only releases that need you to *do* something are
listed here. If a version is not mentioned, `docker compose pull && docker compose up -d`
is all it needs.

[CHANGELOG.md](CHANGELOG.md) carries the detailed notes recorded so far, but it is
**not** a complete release history, so do not treat it as the authoritative list
of what an upgrade requires. This file is: what breaks, who it affects, and what
to type.

**Always upgrade the UI and every worker to the same version.** The compose files
pin both images to the same tag for exactly this reason.

**Back up `/data` first.** `cashpilot.db` holds your earnings history and
`.fernet_key` decrypts every stored credential; without that key they cannot be
recovered. [Backing up and restoring CashPilot](docs/backup-restore.md) has the
commands, and [Backing up node identities](docs/backup.md) covers the rest.

---

## Socket proxy on sockguard 2.4.6: take the new proxy line

**Affects you if** your worker runs behind `cashpilot-socket-proxy`. sockguard
2.4.5 panics when it decodes a malformed zstd frame (GO-2026-6865 /
CVE-2026-116591); 2.4.6 fixes it. Your compose file pins the proxy image, so
pulling new CashPilot images, or an in-app update, leaves 2.4.5 running.

**What to do**, on every host that runs a worker:

1. In your compose file, set the proxy's image to
   `codeswhat/sockguard:2.4.6@sha256:9a7142d9f8254e7fde7543e046eff920463f5df27b36d959915b44fb4878d06f`,
   or take the compose file of this release.
2. Run `docker compose up -d cashpilot-socket-proxy` (with `-f` and your file
   if it is not `docker-compose.yml`), then check with
   `docker inspect -f '{{.Config.Image}}' cashpilot-socket-proxy`.

---

## Owner isolation: take the compose file again; two features change on the UI's host

**Affects you if** your worker runs behind `cashpilot-socket-proxy`. Until now
a compromised worker on the UI's host could read the UI's `/data`, including
`.fernet_key`, the key that decrypts every login CashPilot stores, and the
keys in the UI container's environment. The proxy now lets the worker reach
only the containers, volumes and networks it created
([what that closes](docs/security-defaults.md#docker-socket-proxy)).

**What you lose.**

- **The in-app update no longer updates the dashboard** on the host where the
  UI and a worker run together. It updates the worker; the UI is not the
  worker's to recreate. Update the dashboard with
  `docker compose pull && docker compose up -d`. The update card says so.
  Worker-only hosts are not affected.
- **Earners you started yourself disappear from the worker**: one started by
  hand, or from a compose file CashPilot exported. The worker can no longer see
  them, so the dashboard stops listing them as external services. They keep
  running and earning; only CashPilot's view of them goes.

**What to do.**

1. Take the new compose file, the same way as in
   [the socket proxy section](#docker-socket-proxy-take-the-new-compose-file-once).
2. Run `docker compose up -d --force-recreate` (with `-f` and your file if it
   is not `docker-compose.yml`).

That runs `cashpilot-migrate` once, before the proxy starts. Docker cannot add a
label to an existing volume or network, so it moves your data onto labelled
ones:

- every volume of an earner the worker started is copied to a backup named
  `<volume>-pre-isolation`, checked, recreated with the label, filled back from
  the backup and checked again, and the earner is recreated as it was. A
  Mysterium identity keeps its address. Each backup carries the label
  `cashpilot.backup-of=<volume>`, and the log line
  *Backup … holds the data of …* says which earner it belonged to;
- the worker's own volumes are copied into new ones with `_owned` names
  (`cashpilot_worker_data_owned`, and `cashpilot_fleet_owned` where the UI runs
  too);
- `cashpilot-isolated` is rebuilt with the label and its earners put back.

It can take a few minutes on a node with a large volume. If it stops halfway (a
reboot, a kill), run the same command again: it finishes from where it stopped.
`docker logs cashpilot-migrate` shows what it did. A second run finds nothing to
do and exits.

A volume that a container you started also uses, or one with a custom driver,
is left as it was, with a warning in that log. The earner keeps running and
the worker still sees and controls it, but redeploying it (an update included)
is refused while it uses that volume. Move its data to a volume CashPilot
creates, or redeploy it on a new one.

**What is left behind, and how to remove it.** Nothing is deleted for you:

- each `<volume>-pre-isolation` backup (`docker volume ls --filter label=cashpilot.backup-of`);
- the old `cashpilot_worker_data` and `cashpilot_fleet` volumes, prefixed with
  your project name (`docker volume ls | grep -E 'cashpilot_(worker_data|fleet)$'`);
- `cashpilot-docker-api`, the old socket volume, which held only the socket;
- the folder `cashpilot-migrate-state` next to your compose file, the
  migration's record (root only; it holds each earner's settings, credentials
  included).

Once the dashboard shows every earner running and earning, and a Mysterium
node shows its old address, remove them from your compose folder. `<project>`
is your compose project name, usually the folder's name:

```sh
docker volume ls -q --filter label=cashpilot.backup-of | xargs -r docker volume rm
docker volume rm cashpilot-docker-api <project>_cashpilot_worker_data <project>_cashpilot_fleet \
  && sudo rm -rf cashpilot-migrate-state
```

The folder goes only once both old volumes are gone, which is what the `&&`
checks: while an old `cashpilot_worker_data` or `cashpilot_fleet` exists, the folder is what stops the next
`docker compose up` from copying it over the new one again.

---

## v1.72.1: take the compose file again if your worker runs behind the socket proxy

**Affects you if** you took the compose file of v1.71.0, v1.71.1 or v1.72.0,
the ones with `cashpilot-socket-proxy`. Their policy refused the Docker calls the
LAN fence makes to build and use its network. On a fresh install, every earner
on the bridge network was refused with an isolation error, and turning
isolation on from the Fleet page failed. Activity could not read a
host-network earner such as Mysterium either. Their stand-in for an unset bind
folder was also a path Docker could create, which a compromised worker could
use to reach the host's files.

**What to do.**

1. If you set `CASHPILOT_ISOLATION=off` to get past that error, remove it (or
   set it to `auto`) first, so the new worker starts with the fence.
2. Take the v1.72.1 compose file, the same way as in the next section.
3. Run `docker compose up -d --force-recreate`, with `-f` and the file you
   use if it is not `docker-compose.yml` (for example
   `docker compose -f docker-compose.worker.yml up -d --force-recreate` on a
   worker-only server). Without `--force-recreate`, Compose can keep the
   running proxy and its old policy.
4. If your earners already sit on the default bridge, turn isolation on from
   the Fleet page.

The worker's status page compares the policy fingerprint in the worker's own
settings with the one its image expects. It catches an old compose file, but
not a proxy that kept running with the old policy: `--force-recreate` is what
covers that.

## Docker socket proxy: take the new compose file once

**Affects you if** your worker runs from a compose file that mounts
`/var/run/docker.sock` into `cashpilot-worker`. Nothing breaks if you do
nothing: the in-app update and `docker compose pull && up -d` only pull new
images and keep your compose file, so the worker keeps the raw socket, which is
root on the host. The worker's status page says *Docker access: direct socket
(root on this host)*.

**What changed.** The shipped compose files add `cashpilot-socket-proxy`, a
pinned sockguard container that holds the socket, passes the worker only the
Docker calls it makes, and refuses dangerous containers
([what it refuses](docs/security-defaults.md#docker-socket-proxy)). The worker
no longer mounts the socket.

**What to do.**

1. Check `docker compose version` says 2.23.1 or newer; the policy is inline
   in the compose file.
2. Replace your compose file with the new `docker-compose.yml` (or
   `docker-compose.fleet.yml`, or `docker-compose.worker.yml` on a worker-only
   server). Keep your own changes, except these: the proxy refuses to recreate
   a CashPilot service with a GPU (`devices: /dev/dri`, `gpus`, an NVIDIA
   reservation), and the **Update** button says so before it starts. On a
   GPU host, stay on your old compose file for now.
3. In the `.env` next to it, add your compose folder, so the in-app update can
   still run:

       CASHPILOT_COMPOSE_DIR=/the/folder/with/docker-compose.yml

   If a service keeps its data in a host folder (Storj, for example), add that
   folder too, comma-separated for several. It also counts as a
   `CASHPILOT_ALLOWED_VOLUME_ROOTS` entry, so you need not list it twice:

       CASHPILOT_PROXY_BIND_MOUNTS=/mnt/user/storj

   Named volumes (Mysterium's identity, EarnApp's device id) need nothing,
   unless a container already keeps that data in a host folder (one created
   by hand or by an old release): a redeploy keeps that folder, so it has to
   be listed here too. The worker refuses such a redeploy, naming the folder,
   before it stops the container.

   Each folder you list here is one a compromised worker could use to reach
   root on the host ([why](docs/security-defaults.md#docker-socket-proxy)).
   Leave both settings unset if you update by hand and run no host-folder
   service.
4. Run `docker compose up -d` once (on a worker-only server,
   `docker compose -f docker-compose.worker.yml up -d`, unless you saved it as
   `docker-compose.yml`). It starts the proxy and recreates the
   worker behind it. The containers the worker deployed keep running.
5. Open the worker's status page: it should say *Docker access: socket proxy*.
   If it adds that the policy is not the one the image expects, a later
   release changed the policy: take that release's compose file the same way.

**If something is refused.** The dashboard shows the proxy's reason, and
`docker logs cashpilot-socket-proxy` lists every refused call. A bind outside
the allowed folders names `CASHPILOT_PROXY_BIND_MOUNTS`. The proxy and the worker
both allow only `runc` and the gVisor runtimes; a deploy that names another one
(`crun`, `nvidia`, `io.containerd.runc.v2`) is refused before the running
container is touched, so pick one of those in `CASHPILOT_CONTAINER_RUNTIME`
and its overrides. If the **Update** button says it needs `CASHPILOT_COMPOSE_DIR`,
it prints the exact line to add.

**To go back,** put your old compose file back, run `docker compose up -d`
(with the same `-f` as above if you used one),
then remove the proxy with `docker rm -f cashpilot-socket-proxy`.

## LAN isolation by default (since v1.70.0)

**Affects you if** a worker runs earners on Docker's default bridge, which is
every worker deployed before this release unless you set
`CASHPILOT_CONTAINER_NETWORK`.

**What changed.** A new install fences its earners off your LAN, the host, your
tailnet and cloud metadata by itself: a Docker network plus one firewall table
the worker writes ([LAN isolation by default](docs/isolation.md#lan-isolation-by-default)).

**What breaks if you do nothing.** Nothing. An upgraded worker keeps its earners
where they are and writes no firewall rule. The Fleet page shows "Earners on
this worker can reach your LAN and this host" on its row.

**What to do.** Upgrade the UI and every worker, then press **Turn on
isolation** on each worker's row. It redeploys each earner once onto the new
network and keeps their volumes and identities. Then press **Check isolation**
to see it hold. To stay on Docker's default bridge on purpose, set
`CASHPILOT_ISOLATION=off` on the worker; **Check isolation** still reports the
earners as exposed. If you already run your own rules with
`CASHPILOT_CONTAINER_NETWORK`, nothing changes.

---

## v1.46.0: redeploy Mysterium once to close the tailnet to its customers

**Affects you if** you run Mysterium through CashPilot and deployed it before
v1.46.0. Otherwise **no action is required**.

**What changed.** The node blocks a list of private ranges for its VPN
customers. Its default list leaves out `100.64.0.0/10` (Tailscale and
carrier-grade NAT) and `169.254.0.0/16` (cloud metadata). Since v1.46.0 the
catalog starts the node with both added, through `--firewall.protected.networks`.

**What breaks if you do nothing.** Nothing stops working. A node deployed
earlier keeps the default list, so a customer's traffic can still reach those
ranges, and **Check isolation** on the Fleet page flags it.

**What to do.** Upgrade the UI and the worker that runs Mysterium, then redeploy
Mysterium from the dashboard. The identity stays in its data volume. Details:
[Mysterium, which uses host networking](docs/isolation-check.md#mysterium-which-uses-host-networking).

---

## v1.36.6: a Mysterium node deployed by CashPilot has to be redeployed once

**Affects you if** you run Mysterium (MystNodes) through CashPilot. Check on the
host that runs it:

```bash
docker logs cashpilot-mysterium 2>&1 | grep -c 'PERM_SUDOERS'
```

`0` means **no action is required**. Anything else means the node has been
online, listed and earning nothing.

**What changed.** CashPilot starts every service with all Linux capabilities
dropped and adds back only what the service's catalog entry declares. Mysterium
declared `NET_ADMIN` alone. Its node configures the VPN interface and firewall
through `sudo`, and sudo needs `SETUID` and `SETGID`, so since v1.15.0 every
session failed at setup while the node kept registering and looking healthy. The
catalog now declares all three, and a redeploy now takes capabilities from the
catalog instead of repeating the ones the container was first created with.

**What breaks if you do nothing.** Nothing new. The node stays as it is: running
and not earning.

**What to do.**

1. Upgrade the UI **and the worker that runs Mysterium** to v1.36.6. A worker on
   an older version refuses the deploy with `403 Blocked capabilities: SETGID,
   SETUID`, because each worker checks capabilities against its own catalog.
2. Check where the node keeps its identity **before** you redeploy:

   ```bash
   docker inspect cashpilot-mysterium --format '{{range .Mounts}}{{.Type}} {{.Name}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
   ```

   `volume mysterium-data...` is what CashPilot creates: open Mysterium in the
   dashboard and **redeploy** it, and the node keeps its identity and
   reputation. A `bind` mount means the container was created or changed outside
   CashPilot. On v1.36.7 or newer a redeploy keeps the mounts the container has
   now, so redeploy it from the dashboard too. On v1.36.6 exactly, a redeploy
   would move it onto the `mysterium-data` volume, which is a different
   identity: upgrade first, or recreate that container by hand with the same
   mount, following the [Mysterium guide](docs/guides/mysterium.md).
3. Confirm: `docker exec cashpilot-mysterium sudo -n true && echo SUDO_OK`, and
   the `grep -c` above stays at `0` for the new container.

MystNodes takes several hours to re-score a node. The full walkthrough is in the
[Mysterium guide](docs/guides/mysterium.md).

---

## v1.11.30: the shared fleet key stops working for a worker that never enrolled

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
it. That is the entire point of per-worker keys. Until now, a worker that never
confirmed kept the shared key valid for its identity **forever**, and the UI
re-sent that key to whoever held it every 60 seconds. The window is now bounded
at **24 hours from the moment the key was issued**.

**What breaks if you do nothing.** Such a worker starts receiving `401` on its
heartbeat and disappears from the dashboard. Containers it manages keep running
and keep earning; you simply stop seeing and controlling them.

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

4. Remove the worker on the fleet page, then **restart the container**. The
   identity is read at startup, so `docker compose up -d` on an already-running
   container does not re-read it:

   ```bash
   docker compose restart cashpilot-worker
   docker logs cashpilot-worker | grep -i enrol
   ```

   It writes `/data/.worker_key` once enrolled. Confirm that file exists.
5. For the **Android app**, update it to **v0.2.0 or newer**; earlier builds
   cannot persist the key at all.

Existing, already-enrolled workers are untouched: they authenticate with their
own key, which does not expire.

---

## v1.11.4: the example compose files pin a release series

**Affects you if** you copied `docker-compose.yml` from the repo and are relying
on it tracking the newest build. Your existing deployment is **unaffected until
you edit your compose file**: nothing changes underneath you.

**What changed.** The examples pin `1.11` instead of `latest`, so following the
quickstart gives you a known version rather than whatever was pushed most
recently.

**What to do.** Nothing. If you want a different version, pin an explicit one
(`drumsergio/cashpilot:1.12.0`) rather than a floating tag. `:latest` is not
supported: it makes the version you are running unknowable, which is what
produced a months-old bug report against a bug that had already been fixed.

---

## v1.5.0: CashPilot refuses to start if it cannot persist its encryption key

**Affects you if** your `/data` is not writable. **No action is required** if it
is a normal bind mount or volume.

**What changed.** Credentials are encrypted with a key at `/data/.fernet_key`. If
that could not be written, CashPilot used to carry on with a key that died with
the process, so everything encrypted during that run became unreadable on the
next restart. It now refuses to start instead.

**What breaks if you do nothing.** The container exits at startup with an error
naming the path.

**What to do.** Fix the mount so `/data` is writable. If a throwaway instance is
genuinely what you want, set `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` and accept that
stored credentials will not survive a restart.

**Back up `/data/.fernet_key`.** Without it, stored credentials cannot be
decrypted, not by you, and not by us.

---

## v1.0.4: the dashboard binds to loopback by default

**Affects you if** you reach the dashboard from another machine on your LAN and
you use the shipped compose file. **No action is required** if you browse from
the host itself, or if you front it with a reverse proxy on the same machine.

**What changed.** The compose files bind the dashboard (and, in the fleet
compose, the Docker-socket worker) to `127.0.0.1` instead of `0.0.0.0`. The
worker has the Docker socket, which is root-equivalent on the host, so publishing
it to the whole network by default was the wrong default.

**What breaks if you do nothing.** The dashboard stops answering on the LAN
address you were using.

**What to do.** Set `CASHPILOT_BIND_ADDR` to `0.0.0.0`, or better, to the one
interface you actually want it on. Put it in the `.env` file next to the compose
file, not on the command line. The in-app update reads `.env` and never your
shell. When the published address or port is not in that file, the update
refuses to run rather than move your dashboard back to loopback.

```bash
printf '\nCASHPILOT_BIND_ADDR=192.168.1.10\n' >> .env
docker compose up -d
```

The same goes for `CASHPILOT_UI_PORT`, the host port, if 8080 is taken. That
variable needs the current compose file, whose `ports:` line reads
`${CASHPILOT_UI_PORT:-8080}:8080`; the file from v1.61 and older hard-codes
`8080:8080` and ignores it. Download the current compose file, or
keep your own edited port mapping, which the update also accepts.

The leading newline in `printf` keeps the new line from joining the last line
of an `.env` that does not end in one.

**On a single-host install**, leave the worker on loopback. Only the UI needs to
reach it, and it does so over the Docker network.

**On a fleet**, a remote worker must be reachable by the UI, and it uses a
*different* variable: `CASHPILOT_WORKER_BIND_ADDR` in `docker-compose.fleet.yml`.
Left on loopback, a remote worker is unreachable and its containers become
unmanageable. Bind it to the interface the UI reaches it on: a tailnet address
rather than `0.0.0.0`, since that port carries the Docker socket API:

```bash
printf '\nCASHPILOT_WORKER_BIND_ADDR=100.x.y.z\n' >> .env
docker compose up -d
```

---

## v1.0.0: per-worker fleet keys

A full cutover with its own page: **[Upgrade to v1.0.0](docs/upgrade-v1.md)**.

In short: every worker is issued its own key on first heartbeat and uses it
thereafter; `CASHPILOT_API_KEY` becomes an enrollment credential only. Keep it
set, because enrollment still needs it. Upgrade the UI first, then every worker.

---

## Everything else

No action required. Pull and recreate:

```bash
docker compose pull && docker compose up -d
```

**On a fleet, run that on every host.** It only updates the Compose project it
runs in, so remote workers stay on their old version until you upgrade them too,
and the UI and workers are meant to be on the same release.
