# Upgrading CashPilot

**Read this before upgrading.** Each major release has its own section, newest
first: what changed in that version, then how to upgrade, step by step. Between
the majors, only releases that need you to *do* something are listed here. If a
version is not mentioned, `docker compose pull && docker compose up -d` is all
it needs.

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

## After 3.0.1: the read-only key and metrics work from `.env`

**Affects you if** you set `CASHPILOT_READONLY_API_KEY`,
`CASHPILOT_METRICS_ENABLED` or `CASHPILOT_METRICS_TOKEN` in `.env`. Up to
3.0.1 the compose files did not pass these to the UI container. So the
read-only key got HTTP 401 on every call, also from cashpilot-mcp in
read-only mode, and `/metrics` answered 404. The fleet compose file did not
pass `CASHPILOT_ADMIN_API_KEY` either.

**What to do.** Add the missing lines to the `environment` list of
`cashpilot-ui` in your compose file:

```yaml
      - CASHPILOT_READONLY_API_KEY=${CASHPILOT_READONLY_API_KEY:-}
      - CASHPILOT_METRICS_ENABLED=${CASHPILOT_METRICS_ENABLED:-false}
      - CASHPILOT_METRICS_TOKEN=${CASHPILOT_METRICS_TOKEN:-}
```

In `docker-compose.fleet.yml`, also add
`- CASHPILOT_ADMIN_API_KEY=${CASHPILOT_ADMIN_API_KEY:-}` if it is not there.

Or take the current file. Keep a copy of yours first, then carry over your own
changes and keep your `.env`:

```sh
curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/main/docker-compose.yml
```

Replace `docker-compose.yml` with the file name you use. Check that its image
tags are the series you run, and set them back if they are not. Then run
`docker compose up -d`, with `-f docker-compose.fleet.yml` if you use that
file.

---

## 3.0: upgrade the UI first, then change the image tags

### What changed in 3.0

CashPilot 3.0 changes how the UI and the workers agree on which container to
replace. A worker now replaces a running container only when the UI names that
exact container. A 2.x UI cannot do that, so a 3.0 worker under a 2.x UI
refuses to replace anything. That is why this release is a major version: the
UI and every worker must move to 3.0 together, the UI first. The same release
adds mining, GPU grants and new earnings figures.

#### Why upgrade

- **A redeploy cannot replace the wrong container.** Before 3.0, a redeploy
  replaced whatever container had the service's name. A container that
  changed outside CashPilot could be replaced, and the files in it lost. In
  3.0 the UI shows you the container IDs it is about to replace, and the
  worker refuses if the container changed in the meantime. Proxied copies get
  the same check on Start and on tunnel recovery.
- **GPU services get a GPU, and nothing else does.** A catalog service that
  declares a GPU gets that one device. Every other container gets
  `NVIDIA_VISIBLE_DEVICES=void`, so a CUDA image cannot take the GPU through a
  host whose default Docker runtime is `nvidia`.
- **Mining is in the catalog** (beta), with pool balances read from your
  public payout address only.

#### Approval before a container is replaced

- A redeploy, a settings change or a rename of a running service shows the
  containers it will replace, by ID, and waits for your approval.
- A proxied copy saves the full Docker ID of its container. A copy whose ID is
  not saved yet, or changed, asks for your approval on its next Start.
  Automatic recovery skips such a copy and shows an alert on the Fleet page.
- From the Fleet page you can deploy to a joined CashPilot Desktop, and stop
  and start its services, once it runs Desktop 2.0.
  [Fleet dashboard](docs/fleet.md#fleet-dashboard)

#### Mining (beta)

- **A new Mining section in the catalog.** Run [XMRig](docs/guides/xmrig.md) or
  [unMineable](docs/guides/unmineable.md) on your CPU, or
  [SRBMiner-Multi](docs/guides/srbminer-multi.md) or
  [KRig for Kryptex Pool](docs/guides/kryptex-pearl.md) on an NVIDIA GPU. The
  CPU thread setting caps the threads the miner starts, also on virtual
  machines.
- **Pool balances without a key.** CashPilot reads the unpaid balance of
  [OCEAN](docs/guides/ocean.md), [SupportXMR](docs/guides/supportxmr.md),
  [HeroMiners Kaspa](docs/guides/herominers-kas.md),
  [2Miners ETC](docs/guides/2miners-etc.md) and unMineable from your public
  payout address. For OCEAN it also shows what your hashrate should earn next
  to what the pool credited. [Mining](docs/mining.md)
- **Miners on your network.** Set `CASHPILOT_MINERS` on a worker, and Fleet
  shows the hashrate, temperature and power of Bitaxe (AxeOS) and cgminer
  devices. [LAN miner readings](docs/mining-devices.md)

#### GPU grants (beta)

A catalog entry can declare the GPU it needs. The worker then passes in one
NVIDIA device request, or the AMD or Intel render node, and nothing more. It
gives each miner its own GPU, and it notices when a grant is gone. A custom
service and a proxied copy never get a GPU. [GPU services](docs/gpu.md)

#### Earnings and running costs

- **Bitcoin and Kaspa payout addresses** are read without a key.
  `CASHPILOT_ONCHAIN_URL_<CHAIN>` points the lookup at your own server.
  [On-chain payout balances](docs/onchain.md)
- **Coin balances keep 12 decimals**, so a small payout no longer shows as
  0.00.
- **Break-even tariff, fixed-price hosting and heat credit** on the Fleet
  page's running costs. A miner tracked through its pool is no longer counted
  as running on free electricity. [Running costs](docs/fleet.md#running-costs)
- **Income export.** `GET /api/earnings/income.csv` writes your income for a
  tax tool. [Income export for taxes](docs/income-export.md)
- A catalog entry with no account to create shows **Visit** instead of
  **Sign Up**.

The companion apps that work with 3.0 are listed under
[Companion apps](#companion-apps) below.

### Upgrade from 2.x

**Affects everyone on 2.x.** The compose files pin a release series
(`drumsergio/cashpilot:2.10`), so `docker compose pull` and the in-app
**Update** button keep a 2.x install on 2.x. The update card still tells you
that 3.0.0 exists. Moving to 3.0 means taking the new compose file or
changing the tags.

**What breaks if you do nothing.** Nothing, while the UI and every worker stay
on 2.x. The risk is a worker that reaches 3.0 before the UI. A 3.0 worker
replaces a running container only when the UI confirms which container it
replaces, and a 2.x UI cannot do that. So it refuses every redeploy, settings
change, rename and proxied rebuild of a container that already runs. It also
refuses the Start of a proxied copy made before 3.0 when that Start must move
the copy into a new tunnel. Such a copy has no saved container ID yet. It
stays down, also when the traffic cap reset would start it again. The 2.x UI
shows the worker's answer: "This worker runs CashPilot v3.0.x and replaces an
existing container only when the UI confirms which container it replaces, and
this UI is too old to do that. Update the UI, then redeploy. Nothing was
changed." The worker names its exact version where this quote has 3.0.x.
For a Start, the answer ends in "then Start the copy again". The
Fleet page marks that worker in amber, because it is on another release
series.

The other order works. A 3.0 UI still deploys to a 2.10 worker: it reads the
running containers itself and asks you to approve a replacement.

**What to do.**

1. Back up the dashboard's `/data` and your node identities (see the top of
   this file). [Backing up and restoring](docs/backup-restore.md#backup) and
   [Backing up node identities](docs/backup.md) have the steps.
2. On the UI host, keep a copy of your current compose file. You need it to
   roll back. Run the line for the file you use:

   ```sh
   # The dashboard and its worker on one host:
   cp docker-compose.yml docker-compose.2.10.yml
   # A dashboard with remote workers:
   cp docker-compose.fleet.yml docker-compose.fleet.2.10.yml
   ```

   Then replace the file with the 3.0 one of the same name:

   ```sh
   curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/v3.0.1/docker-compose.yml
   ```

   Replace `v3.0.1` with the newest 3.0 release
   (https://github.com/GeiserX/CashPilot/releases), and the file name with
   the one you use. Carry over your own changes, such as container names,
   mounts or ports, and keep your `.env`. Or keep your file and change every
   `drumsergio/cashpilot:2.10` and `drumsergio/cashpilot-worker:2.10` tag to
   `3.0`. If you set the read-only key or metrics in `.env`, also add the
   lines from
   [After 3.0.1](#after-301-the-read-only-key-and-metrics-work-from-env).
   Then recreate the containers:

   ```sh
   # With docker-compose.yml:
   docker compose up -d --force-recreate
   # With docker-compose.fleet.yml:
   docker compose -f docker-compose.fleet.yml up -d --force-recreate
   ```

   Both files also run a worker on the UI host, so that worker is now on 3.0.
3. Do the same on every worker host, with `docker-compose.worker.yml`. Keep a
   copy first:

   ```sh
   cp docker-compose.worker.yml docker-compose.worker.2.10.yml
   ```

   Then take the 3.0 file or change the tag, carry over your changes and
   keep your `.env`. Then run:

   ```sh
   docker compose -f docker-compose.worker.yml up -d --force-recreate
   ```

   If you saved the worker file as `docker-compose.yml`, use that name in
   these commands and leave out `-f`.

On Unraid, both apps follow `:latest`, and each release moves `:latest` for
both images. So the next update of either app takes it to 3.0. Update the UI
app first, then the worker app. If Watchtower or a similar tool updates your
containers, keep the same order.

Then read the parts below that apply to you. Each one has the details and the
commands:

- A worker behind the socket proxy needs the new proxy policy before it
  deploys a service that uses a GPU.
- A service that sets an `NVIDIA_` variable is refused until you remove it.
- A proxied copy made before 3.0 asks you once to approve its containers.
- Scripts must confirm in a second call before a route replaces a running
  container. These routes ask: deploy, rename, device ID change, import-draft
  deploy, adding a proxied copy that already runs, and the worker command
  deploy. A proxied copy's Start may also ask for its containers and a
  `group_approval` in return.

### Take the new proxy policy before you deploy a service that uses a GPU

**Affects you if** your worker runs behind `cashpilot-socket-proxy` and you
want to deploy a catalog service that uses a GPU ([GPU grant](docs/gpu.md)).
Nothing else changes: every other service deploys as before.

The proxy's policy now lets the worker pass in an NVIDIA GPU request and the
render nodes `/dev/dri/renderD128` to `renderD135` and `/dev/kfd`. Until your
compose file carries that policy, the worker refuses a GPU service's deploy
and names the fix. Its status page and the dashboard's update card say the
policy is out of date.

**What to do.** Run the command the worker's status page shows. It rewrites
only the policy block of your compose file and its `CASHPILOT_PROXY_POLICY`
fingerprint lines. Check the diff, use the new file, then run
`docker compose up -d --force-recreate cashpilot-socket-proxy cashpilot-worker`.
Or take this release's compose file.

### The GPU lines in the worker's compose file are gone

**Affects you if** you uncommented the GPU lines of the worker in
`docker-compose.yml` or `docker-compose.fleet.yml` (`devices: /dev/dri`,
`gpus: all` or the `nvidia` reservation). The 3.0 files no longer have them. The worker now reads the GPUs
from sysfs, and it gives a GPU only to a catalog service that declares one.

**What to do.** Nothing is required. You can remove those lines.

### A custom service that sets `NVIDIA_` variables

**Affects you if** a service you deploy sets an environment variable that
starts with `NVIDIA_`, or a custom service uses an NVIDIA GPU.

- The worker refuses a deploy with any `NVIDIA_` variable (HTTP 403).
- The worker sets `NVIDIA_VISIBLE_DEVICES=void` on every container it creates
  without an NVIDIA grant. On a host whose default Docker runtime is `nvidia`,
  such a container loses the GPU on its next deploy
  ([who gets a GPU](docs/gpu.md#who-gets-a-gpu)).

**What to do.** Remove the `NVIDIA_` variables from the service before you
redeploy it. Run a GPU workload that the catalog does not grant outside
CashPilot, or ask for a catalog entry.

### API scripts and cashpilot-mcp: a replacement asks for confirmation

**Affects you if** a script or an AI agent calls the CashPilot API, or you use
[cashpilot-mcp](https://github.com/GeiserX/cashpilot-mcp).

- No owner route replaces a running container in one call any more. These
  routes now need a confirmation:
  - `POST /api/deploy/{slug}`, for a redeploy or a change in the number of
    copies (a change in copies redeploys copy 1 first)
  - `POST /api/deploy/{slug}/device-names/copies`, the rename of proxied
    copies
  - `POST /api/identities/{id}/change`, a device ID change
  - `POST /api/import/drafts/{slug}/deploy`, the deploy of an import draft
  - `POST /api/proxies/{proxy_id}/copies`, when the copy already runs
  - `POST /api/workers/{worker_id}/command` with `"command": "deploy"`, when
    the service already runs on that worker
- Every 409 below puts its fields under `detail`, not at the top level of
  the body. Read `body["detail"]["error"]`, not `body["error"]`.
- A call that does not confirm gets HTTP 409. The error is
  `deploy_target_changed` for a 3.0 worker, and `confirm_deploy_targets` for a
  joined Desktop or a 2.x worker. Handle both. `deploy_target_changed` also
  carries `detail.current_container`.
- To confirm, send the call with `"replace_existing": true`. The answer is
  HTTP 409 with a body like this:

  ```json
  {
    "detail": {
      "error": "confirm_deploy_targets",
      "message": "Replace these containers ...",
      "expected_containers": {"1": "<container id>"}
    }
  }
  ```

  Show `message` to the owner. The keys of `expected_containers` are copy
  numbers as strings, or `p<proxy id>` for a proxied copy. Each value is that
  copy's container ID, or `none` when the worker found no container. A 3.0
  worker gives full IDs, and a 2.x worker short ones. Send the same call again
  with `"replace_existing": true` and `"expected_containers"` set to
  `detail.expected_containers`, unchanged. A 3.0 worker replaces only those
  containers. A 2.x worker does not check the IDs itself. The UI reads its
  containers again just before it sends the deploy, and refuses when an ID
  changed. A container that changes after that read can still be replaced.
  Update 2.x workers to 3.0 to close that gap. The import-draft route takes no
  `replace_existing`. It replaces a running container only when the call
  sends `expected_containers`.
- Adding a proxied copy that already runs takes no `replace_existing`
  either. The answer is HTTP 409 `confirm_deploy_targets` with
  `expected_containers` keyed `p<proxy_id>`. Send the same call again with
  that object.
- The worker command deploy reads `expected_container` from its `spec`: the
  container ID it may replace, or `"none"`, which is the default. When the
  service already runs, the answer is HTTP 409 `deploy_target_changed` with
  `current_container`. Send the deploy again with that ID as
  `spec.expected_container`.
- The Start of a proxied copy
  (`POST /api/proxies/{proxy_id}/copies/{worker_id}/{slug}/start`) can answer
  HTTP 409 with `"error": "confirm_proxy_start_targets"`,
  `expected_containers` and `group_approval`. Send the Start again with both
  fields as you got them.
- `GET /api/workers` returns `watts` as a number or `null`. Before 3.0 it was a
  string, empty when not set. Each worker also has a new `unmetered` field.
- `GET /api/earnings/breakdown` keeps 12 decimals instead of 4.

**What to do.** Use cashpilot-mcp 0.4.0 or later: older versions cannot
redeploy a running service. Add the confirmation step to your scripts.

### A proxied copy may ask you to approve its containers once

**Affects you if** you run copies through a proxy (Proxies on the Fleet page).

The worker now saves the full container ID of each proxied copy when it
deploys or moves it. It replaces a copy only if that copy still has the saved
ID. Copies made before this release have no saved ID yet.

- The first Start that must move such a copy into a new tunnel asks you to
  approve the containers. Approve them once. After that the ID is saved.
- A copy the traffic cap stopped is not started again by itself if it needs
  this approval. A Fleet alert says so. Press Start for the copy on the Fleet
  page.
- Automatic recovery of a tunnel skips such copies and shows a "skipped
  recovery" alert. Stop the copy, then Start it on the Fleet page.
- A worker on 2.5 or older made tunnels that Docker restarts by itself.
  Upgrade that worker to 2.10.2 first, so it replaces them for you.
- A worker older than 2.2.0 ran each copy with a tunnel of its own. A 3.0
  worker no longer moves these pairs into the proxy's shared tunnel when it
  starts. They keep running as they are. A pair moves on the next Start of
  its copy, after you approve its containers. Or upgrade that worker to 2.10.2
  first, which moves them when it starts.

A worker before this release that stopped in the middle of a move can leave a
container named `cashpilot-<service>-p<N>-moving` or `-next`. The worker no
longer settles these by itself, and Start for that copy is refused. Settle it
by hand on that box:

1. If `cashpilot-<service>-p<N>` exists, the move finished. Run
   `docker rm cashpilot-<service>-p<N>-moving` (or `-next`).
2. If it does not exist and the `-moving` container exists, run
   `docker rm cashpilot-<service>-p<N>-next` (if it exists), then
   `docker rename cashpilot-<service>-p<N>-moving cashpilot-<service>-p<N>`.
3. If only the `-next` container exists, do not remove it. Run
   `docker rename cashpilot-<service>-p<N>-next cashpilot-<service>-p<N>`.

Leave out `-v`, so the copy's volumes stay. Then press Start for the copy on
the Fleet page.

### Companion apps

**Affects you if** you use CashPilot Desktop, cashpilot-mcp, the Android app or
the Home Assistant integration with this server.

- **[CashPilot Desktop](https://github.com/GeiserX/CashPilot-Desktop) 2.0.0 or
  later** takes server commands (deploy, stop, start) from a 3.0 server. It offers its command address only to a server that
  says it can command a Desktop safely, and 3.0 is the first such release.
  Under a 2.x server, Desktop 2.0 only reports what runs on it. Desktop 1.7.0
  under a 3.0 server also only reports.
- After an upgrade from Desktop 1.x, server commands start off. Turn them on
  in the Desktop's dashboard if you want this server to command it.
- Desktop does not update itself. Download it from its
  [releases page](https://github.com/GeiserX/CashPilot-Desktop/releases).
- **[cashpilot-mcp](https://github.com/GeiserX/cashpilot-mcp) 0.4.0 or later**
  is needed to redeploy a running service, because it sends the confirmation
  that 3.0 asks for.
- CashPilot Desktop 2.0 has its own upgrade steps. Its pairing moves to a new
  file once, so a later downgrade to 1.x needs a new join. When the server
  refuses its key (HTTP 401), you must join again by hand. It also refuses
  `NVIDIA_` variables, so a 1.x custom service that sets one cannot be
  redeployed until you remove them.
- The [Android app](https://github.com/GeiserX/CashPilot-android) and the Home
  Assistant integration talk to 3.0 as they did to 2.x. They need no update.
  Home Assistant shows every balance in USD with 2 decimals, so a coin balance
  from a mining pool shows wrong there (0.0006 XMR shows as 0.00). Read coin
  balances in CashPilot.

**What to do.** Upgrade this server to 3.0 before you upgrade a Desktop to
2.0. Update cashpilot-mcp to 0.4.0.

### Rolling back

3.0 adds one table to the database and changes no other, so 2.10.2 opens the
same database. Move the UI and every worker back together. 2.10.2 has no
Mining catalog, so remove the mining services you deployed on 3.0 before you
go back. A container that got a GPU on 3.0 keeps it on 2.10.2 until something
redeploys it.

On each host, put back the 2.10 compose file you kept in step 2 or 3, then
recreate the containers. Run the lines for the file that host uses:

```sh
# The dashboard and its worker on one host:
cp docker-compose.2.10.yml docker-compose.yml
docker compose up -d --force-recreate
# A dashboard with remote workers:
cp docker-compose.fleet.2.10.yml docker-compose.fleet.yml
docker compose -f docker-compose.fleet.yml up -d --force-recreate
# A worker host:
cp docker-compose.worker.2.10.yml docker-compose.worker.yml
docker compose -f docker-compose.worker.yml up -d --force-recreate
```

If you did not keep it, take the 2.10 file again, then carry over your own
changes and recreate the containers as above:

```sh
curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/v2.10.2/docker-compose.yml
```

Replace `docker-compose.yml` with the file name that host uses.

If you only changed the tags, change them back to `2.10`. If you also took the
3.0 proxy policy, the 2.10 worker may report that its proxy policy is out of
date. Then put back the 2.10 file, or run the policy command shown under
**Settings**, **About and updates**.

On Unraid, edit each app and set **Repository** to
`drumsergio/cashpilot:2.10` and `drumsergio/cashpilot-worker:2.10`, then
**Apply**. Change both apps. While these tags stay, an update keeps them on
2.10. Set them back to `:latest` when you are ready to return to 3.0.

---

## After 2.3.0: the fleet key no longer reads the dashboard, and `/data` closes to other users

**Affects you if** a dashboard tile, widget or script calls the CashPilot API
with the shared fleet key (`CASHPILOT_API_KEY`), or if something other than
CashPilot reads its `/data` folder.

- The fleet key only enrolls workers. Every dashboard API route now answers it
  with 403 "The fleet key only enrolls workers". Workers, CashPilot Desktop and
  the Android app are not affected: they only send heartbeats and earnings
  imports, which still take it.
- The UI and the worker now create their files for their own user alone
  (`umask 077`), and an image started as root sets `/data` to `700`. A sidecar,
  backup job or file share that reads `/data` as another user loses access.

**What to do.**

1. For a tile, widget or script: set `CASHPILOT_READONLY_API_KEY` on the UI,
   `docker compose up -d`, and give that key to the tile instead
   ([Heimdall tile](contrib/heimdall/README.md#which-key-to-use)).
2. For anything else that reads `/data`: run it as the image's user (uid 1000)
   or as root.

---

## After 2.0.6: redeploy Mysterium once to move it off the host network

**Affects you if** you run Mysterium through CashPilot. Through 2.0.6 the node
ran on the host's network with `NET_ADMIN`, so a compromised node or a
malicious image update could rewrite the host's firewall, the LAN fence
included, and reach your LAN, your tailnet and every other container. Later
releases run it in its own network namespace on `cashpilot-isolated`, behind
the fence, and the worker starts it only once the fence is in place
([Mysterium on the fenced bridge](docs/isolation.md#mysterium-on-the-fenced-bridge)).

A running node keeps running until you redeploy it, in any isolation mode:
the upgraded worker does not stop, start or change it. Redeploy it once to
move it behind the fence. Until then the Fleet page shows it under its worker
with a **Redeploy MystNodes to move behind the fence** button (or, with
isolation off, says to switch it on first), the dashboard lists it under
drift, and **Check isolation** fails on it.

**What to do, in this order.**

1. Upgrade the UI **and the worker that runs Mysterium**. The dashboard refuses
   to redeploy Mysterium onto an older worker.
2. Switch isolation on in Fleet: if the Fleet page offers **Turn on
   isolation**, press it. A worker with `CASHPILOT_ISOLATION=off` needs it set
   to `auto` and a restart. In `off` or `legacy` mode, and on Podman, the
   worker refuses to redeploy Mysterium, since on Docker's default bridge the
   other earners could reach its WebUI; the running node is left as it is. On
   your own network (`CASHPILOT_CONTAINER_NETWORK`) it runs under your rules.
3. Move the UDP range below 32768 first: set `UDP_PORTS` to a
   free range below 32768 other than the default, such as `23100:23129`,
   and change the router forward to match. A value equal to the default
   (`23000:23029`) reads as a field left as it was, so the range on record
   would stay; to take the default itself, remove the service from that
   machine (its data volume stays) and deploy again.
   Or keep the range and reserve it on the host instead, with no router
   change. First read `sysctl net.ipv4.ip_local_reserved_ports`: if it lists
   ranges, add yours (with a dash) to them, comma-separated, and use the whole
   list in both places, or the write drops them. Then run
   `sudo sysctl -w net.ipv4.ip_local_reserved_ports=56000-56100` and put the
   line `net.ipv4.ip_local_reserved_ports = 56000-56100` in
   `/etc/sysctl.d/90-mysterium-ports.conf` so it survives a reboot. It stops automatic picks only; a
   program that binds one of the ports by number still fails the start. The worker cannot see the host's
   reservation, so Fleet keeps warning about the range; once it is reserved,
   redeploy anyway.
   The worker publishes the range 1:1 through Docker, and a node's range on
   record (`56000:56100` through 2.0.6, `56000:56029` in 2.0.7 and 2.1.0) sits in
   Linux's ephemeral range, 32768-60999, where any program on the host can
   hold a port for a moment. One taken port fails the whole start. The
   worker then puts the old node back and names the port, so nothing is
   lost, but the node does not move. A node that keeps its old range still
   works while no host program holds one of its ports. 30 ports also save
   about 175 MB of memory in Docker's port proxy against 101. UPnP no longer
   works for the node, so forward the range by hand if you relied on it.
4. Redeploy Mysterium once from the dashboard. It keeps its data volume or
   data folder, so it keeps its identity and its earnings: the worker reads
   the identity from the running node before it removes it, compares it with
   the new one's, and stops the new node if they differ. That needs both
   reads, so back up the keystore first anyway
   ([Backing up node identities](docs/backup.md)) and check the identity after
   (`docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/identities`).

**If you reach the WebUI through a reverse proxy.** `UI_ADDRESS` is now the
host addresses port 4449 is published on. A Docker network gateway in it is
published as before. A LAN address is published too, but a host `INPUT` rule
no longer restricts it, since published ports go through Docker's forwarding:
use a `DOCKER-USER` rule or keep the proxy on the same machine.

**If the worker runs gVisor by default** (`CASHPILOT_CONTAINER_RUNTIME=runsc`):
nothing to do. Mysterium's catalog entry requires `runc` and wins over it.

**To go back** to 2.0.6, a redeploy is not enough: 2.0.6 keeps the network on
record, so the node would stay on the bridge with its WebUI listening only
inside its own namespace. Remove Mysterium from 2.0.6's dashboard, keeping its
data volume (the default), then deploy it again: a fresh deploy uses 2.0.6's
catalog, host network and UDP range included, on the same data volume or
folder. Back it up first, as for the redeploy.

---

## 2.0: change the image tags

### What changed in 2.0

CashPilot 2.0 adds no big feature of its own. It closes a run of releases,
1.62 to 1.73, that changed what the worker can do on your host, how far an
earner can reach into your network, and how many IPs one box can earn on.
Several of those releases need a step from you when you upgrade, so they get a
major version together.

#### Why upgrade

What an older install leaves open, by version:

- **1.70 and older:** the worker holds the raw Docker socket. Whoever takes
  over the worker is root on your host.
- **1.72 and older,** with the dashboard and a worker on one host: a
  compromised worker can read `.fernet_key` and decrypt every provider login
  you stored.
- **Anything deployed before 1.70:** earners carrying strangers' traffic can
  reach your LAN, your router and your other machines, until you turn the
  fence on.

2.0 closes all three. It also carries the fixes since 1.73: the in-app update
works behind the socket proxy, identity backups you confirmed stay confirmed
through the migration, earners from the old pre-worker deploy path stay
visible after it, Podman workers can deploy, and traffic caps on proxies
recover after a box was offline. Releases are cut from one branch, so every
fix from now on ships in 2.x and the `1.73` tag gets no more patches.

#### Security

##### The worker no longer holds the Docker socket

Whoever holds the Docker socket is root on the host. In the shipped compose
files the socket now sits with a socket proxy,
[sockguard](https://github.com/CodesWhat/sockguard) 2.4.6, pinned by digest.
The worker talks to Docker only through it. The proxy reads every request,
including its JSON body, and refuses:

- every Docker API call the worker does not make (swarm, secrets, plugins,
  builds, exec of arbitrary commands, image push, and more);
- privileged containers, host PID, IPC and user namespaces, unconfined seccomp
  or AppArmor;
- binds of `/`, of the socket, or of any host folder you did not list;
- any added capability other than `NET_ADMIN`, `NET_RAW`, `SETUID` and
  `SETGID`, any device other than `/dev/net/tun`, and any runtime other than
  `runc` and gVisor.

A CI job opens a pull request when sockguard ships a new release, so the pin
does not go stale.
[Docker socket proxy](docs/security-defaults.md#docker-socket-proxy) has the
full list.

##### Owner isolation keeps a compromised worker out of the dashboard

The proxy labels every container, volume and network the worker creates with
`cashpilot.deployed-by=worker`, and refuses the worker everything without that
label. On a host that runs the dashboard and a worker together, a compromised
worker can no longer read the dashboard's `/data`. That folder holds
`.fernet_key`, the key that decrypts every login CashPilot stores. Nor can it
read the keys in the dashboard container's environment. It cannot touch
containers you started by hand either.

It is not yet a full root boundary. If you set `CASHPILOT_COMPOSE_DIR` or
`CASHPILOT_PROXY_BIND_MOUNTS`, a symlink planted in one of those folders can
still reach the host's root, until sockguard can check binds for symlinks.
Leave both unset and that path is closed.
[Owner isolation](docs/security-defaults.md#docker-socket-proxy) lists what a
compromised worker can still do.

##### Earners are fenced off your LAN

On a new install the worker puts bridge-networked earners on their own Docker
network and writes one firewall table that drops traffic from them to:

- private ranges (`10/8`, `172.16/12`, `192.168/16`);
- `100.64/10`, which covers carrier-grade NAT and your tailnet;
- `169.254/16`, cloud metadata;
- the host itself, any subnet directly attached to it, and your home's own
  public IP, which most routers would loop back into the LAN.

An upgraded install turns it on with **Turn on isolation** on the Fleet page,
and **Check isolation** starts two short-lived containers to test that it holds.

Limits: through 2.0.6 Mysterium ran on host networking and was not covered by
the fence; later releases move it onto the fenced bridge in its own network
namespace on its next redeploy, and run it only with isolation on or on your
own network
([Mysterium on the fenced bridge](docs/isolation.md#mysterium-on-the-fenced-bridge)).
A second WAN or extra public IPs are not dropped. Docker Desktop, rootless
Docker, and Unraid are not tested yet. On Podman the fence is not available
yet: a worker there deploys on Podman's default network and the Fleet page says
so. [Network isolation](docs/isolation.md#lan-isolation-by-default) has the
details, and [Test your isolation](docs/isolation-check.md) has the checks by
platform.

##### gVisor where it works

If your Docker daemon has gVisor's `runsc` runtime, `CASHPILOT_CONTAINER_RUNTIME`
puts the bridge-networked earners in it, with exceptions per service. We
measured about a fifth less peak throughput and six to nine times the CPU per
byte moved. It does not run on stock Unraid.
[gVisor, optional](docs/home-network-security.md#7-gvisor-optional) has the
numbers and the install steps.

##### Node identities are backed up before you can lose them

Some earners keep state that has no copy anywhere else: a Mysterium keystore,
a Storj identity. CashPilot refuses to delete those volumes unless you ask for
it explicitly. The Payouts page lists them under **Back these up**, one line
per box, with an encrypted **Download backup** button. A box that has been
backed up asks again when its volume changes or after six months.
[Backing up node identities](docs/backup.md) explains how.

#### Proxied copies: earn on more than one IP

Providers count devices per public IP, so a second copy of an earner on the
same box usually earns nothing. A proxied copy is an extra copy of a deployed
service that leaves through a proxy instead, so one box earns on its own IP plus
one IP per proxy.

- Three kinds of proxy: SOCKS5, HTTP CONNECT, or a Tailscale exit node on
  another connection you own.
- **Test** starts a throwaway tunnel, shows the exit IP and country, and passes
  only when that IP is public and, when the worker knows its own public IP, is
  not the box's own.
- It fails closed. The earner has no network of its own. It shares the
  namespace of a tunnel container whose firewall drops every packet that does
  not go through the proxy. The earner starts only after the tunnel has seen an
  exit IP within 45 seconds. If the proxy dies, the copy stops earning
  and nothing leaks out of your own IP. `scripts/proxy_leak_test.sh` checks
  this against a real Docker daemon.
- An optional traffic cap per proxy, in GB, stops its copies at a threshold
  (90% of the cap by default) and starts them again on the reset day.

Limits: services that need host networking, published ports, volumes, devices
or extra network capabilities cannot run through a proxy. That rules out
Mysterium, Bitping and Storj. Neither can a service whose terms forbid proxies.
UDP goes out only through a Tailscale exit node, never through SOCKS5 or HTTP
CONNECT. [Proxied copies](docs/proxies.md) covers setup and DNS.

#### Also new since 1.62

- **Provider ratings.** Every provider gets a letter grade from the same ten
  questions, each answer backed by a source you can open. At 2.0.0 none of the
  graded providers earned an A or a B. [Provider ratings](docs/ratings.md)
- **Activity.** Off by default. Once you turn it on, it shows what each earner
  does on the network: connections, ports, networks, countries, and alerts for
  mail ports and attempts on your LAN. It reads socket tables only, never
  traffic. [Activity](docs/activity.md)
- **Custom services.** Run any image the catalog lacks, by name and tag, with
  the catalog's restrictions. [Custom services](docs/custom-services.md)
- **Import from another tool.** Bring your logins over from money4band,
  CashFactory or InternetIncome, and review them before saving.
  [Moving from money4band](docs/migrate/money4band.md)
- **Payouts.** The Payouts page lists each service, the boxes it runs on and
  the address it pays to. A balance drop is offered as a payout for you to
  confirm. The [service guides](docs/guides/index.md) give each minimum payout,
  and several say what a first cash-out asks for, such as a one-time
  registration link or a phone check by SMS.
- **App stores.** Install from Unraid Community Applications or TrueNAS SCALE.
  CasaOS and Runtipi packages are in this repository and run the socket proxy.
  [App stores](docs/app-stores.md)
- **Catalog.** At 2.0.0 the catalog held 40 active services and 1 in beta: 17
  ran in Docker, 24 were tracked, and 15 had a balance collector.
  [How CashPilot compares](docs/comparison.md) sets today's catalog against
  five other stacks, every cell sourced.

#### Companion apps in 2.0

- **[CashPilot Desktop 1.0](https://github.com/GeiserX/CashPilot-Desktop)**
  runs the same catalog as an app for macOS (Apple Silicon), Windows and
  Linux. It works as a full dashboard or as a worker that joins this one, and
  pins every service image by digest.
- **[CashPilot for Android 1.0](https://github.com/GeiserX/CashPilot-android)**
  reports a phone's earning apps to the
  [Fleet page](docs/fleet.md#fleet-dashboard) next to your servers. It ships
  from GitHub releases and is waiting for review on
  [F-Droid](https://gitlab.com/fdroid/fdroiddata/-/merge_requests/56196).

### Upgrade from 1.x

**Affects everyone on 1.x.** The compose files pin a release series
(`drumsergio/cashpilot:1.73`), so `docker compose pull` and the in-app
**Update** button never move a 1.x install to 2.0. Moving to 2.0 means taking
the new compose file or changing the tags.

Beyond the fixes since 1.73, 2.0 changes nothing of its own, and it uses the
same database. It is the major version for the releases below, several of
which need a step from you: the socket proxy, owner isolation and its one-shot
migration, and LAN isolation for upgraded installs.

**What to do.** Follow the three steps below on each host. Coming from before
1.73, also follow the sections below for your version.

#### 1. Back up first

- **The dashboard's `/data`.** `cashpilot.db` holds your earnings history and
  `.fernet_key` decrypts every stored login. Without that key the logins
  cannot be recovered. [Backing up and restoring](docs/backup-restore.md#backup)
  has a script that copies both without stopping the container, and the
  commands to check the copy.
- **Node identities.** On the Payouts page, use **Download backup** for every
  box listed under **Back these up**. A Mysterium keystore or a Storj identity
  has no other copy. [Backing up node identities](docs/backup.md)

The migration below keeps its own copy of every volume it touches, but a
backup you hold is the one that survives a lost disk.

#### 2. Take the 2.0 compose file

On each host, first keep a copy of your current compose file, for example
`cp docker-compose.yml docker-compose.1.x.yml`. Rolling back needs it. Then
replace your compose file with the 2.0 one:
`docker-compose.yml` where the dashboard runs, `docker-compose.fleet.yml` for a
dashboard with remote workers, or `docker-compose.worker.yml` on a worker-only
host. Carry over your own changes and keep your `.env`. If you keep your old
file, it must already have the `cashpilot-socket-proxy` and
`cashpilot-migrate` services; then change every `drumsergio/cashpilot:1.x` and
`drumsergio/cashpilot-worker:1.x` tag to `2.0`.

If your worker still mounts `/var/run/docker.sock`, the new file is what moves
the socket to the proxy. Set `CASHPILOT_COMPOSE_DIR=/folder/with/the/compose/file`
in `.env` if you want the in-app update, which opens the symlink path
described above. On a GPU host, read
[the socket proxy section](#docker-socket-proxy-take-the-new-compose-file-once)
first: the proxy refuses to recreate a CashPilot service with a GPU.

#### 3. Start it

```sh
docker compose up -d --force-recreate
```

Add `-f` and your file name if it is not `docker-compose.yml`. Do the
dashboard host first, then every worker host. The dashboard and every worker
should run the same version.

#### What the one-shot migrator does

On an install from before 1.73, `cashpilot-migrate` runs once, before the
socket proxy starts. Docker cannot add a label to an existing volume or
network, so it moves your data onto labelled ones:

- each volume of an earner the worker started is copied to a backup named
  `<volume>-pre-isolation`, checked by digest, recreated with the label,
  filled back from the backup and checked again. The earner is then recreated
  as it was. A Mysterium identity keeps its address;
- the worker's own volumes are copied into new ones named
  `cashpilot_worker_data_owned` and, where the dashboard runs too,
  `cashpilot_fleet_owned`;
- the `cashpilot-isolated` network is rebuilt with the label, with its earners
  put back on it.

It deletes nothing. It can take a few minutes on a node with a large volume.
If it stops halfway, after a reboot or a kill, run the same command again and
it finishes from where it stopped. If it already ran on 1.73, it finds nothing
to do and exits.

#### What you see when it is done

- `docker logs cashpilot-migrate` ends with *Migration complete: everything the
  worker uses carries cashpilot.deployed-by=worker.* A run that had to leave
  something alone ends with *Migration done, with N thing(s) left as they
  were*, and the lines above it say what and why.
- The worker's status page says *Docker access: socket proxy*.
- The dashboard shows every earner running, the Fleet page shows each worker on
  2.0, and a Mysterium node shows the same address as before.

Two things work differently afterwards:

- On the host where the dashboard and a worker run together, the in-app update
  updates the worker only. Update the dashboard with
  `docker compose pull && docker compose up -d`.
- Earners you started by hand, or from a compose file CashPilot exported, no
  longer show in the dashboard. They keep running and earning.

If you came from 1.69 or older, your earners are still on Docker's default
bridge. Press **Turn on isolation** on each worker's row on the Fleet page,
then **Check isolation**.

Once everything has run well for a while, remove what the migration left
behind.
[The owner isolation section](#owner-isolation-take-the-compose-file-again-two-features-change-on-the-uis-host)
lists each leftover and the commands.

#### Rolling back from 2.0

2.0 uses the same database schema as every release since 1.67. To go back to
1.73, set the tags back to `1.73` and run `docker compose up -d`.

To go back further, put back the copy of your old compose file you kept in
step 2, for example `cp docker-compose.1.x.yml docker-compose.yml`, and run
`docker compose up -d`. Use your own file names, and add
`-f docker-compose.fleet.yml` or `-f docker-compose.worker.yml` where you use
those files. The migration copies and never deletes, so your old
worker volumes and each `<volume>-pre-isolation` backup are still there,
unless you removed them. That is why you keep them for a while. A compose file
from before the socket proxy leaves the proxy running: remove it with
`docker rm -f cashpilot-socket-proxy`. Going back past 1.67, restore the
`/data` backup you took as well.

> **The old volumes hold the data from the day you migrated.** On 2.0 the
> worker writes to `cashpilot_worker_data_owned`, and on its host the dashboard to
> `cashpilot_fleet_owned`. The old compose file mounts `cashpilot_worker_data`
> and `cashpilot_fleet` again, so everything written on 2.0 is missing there.
> The newest data stays in the `_owned` volumes until you remove them.

---

## Socket proxy on sockguard 2.4.7: take the new proxy line

**Affects you if** your worker runs behind `cashpilot-socket-proxy`. sockguard
2.4.7 is built with Go 1.27.4, which fixes a crash in Go's HTTP server
(GO-2026-6859 / CVE-2026-97054). The proxy serves HTTP over the socket, so
2.4.6 and older carry that crash. Your compose file pins the proxy image, so
pulling new CashPilot images, or an in-app update, leaves the old proxy
running.

**What to do**, on every host that runs a worker:

1. In your compose file, set the proxy's image to
   `codeswhat/sockguard:2.4.7@sha256:8d985328da6b62a0909656e8c584791d356b5e869f0988deeaef4c08e4cc23da`,
   or take the compose file of this release.
2. Run `docker compose up -d cashpilot-socket-proxy` (with `-f` and your file
   if it is not `docker-compose.yml`), then check with
   `docker inspect -f '{{.Config.Image}}' cashpilot-socket-proxy`.

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
  Mysterium identity keeps its address, and a backup you confirmed on the
  Payouts page stays confirmed (if you migrated with 1.73.0 or 1.73.1, the
  page shows those boxes as changed: confirm them again). Each backup carries the label
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
3. Only if you want the in-app update: add your compose folder to the `.env`
   next to it. This lets containers bind that folder through the proxy, which
   weakens it ([what that costs](docs/security-defaults.md#docker-socket-proxy)).
   Without it, update with `docker compose pull && docker compose up -d`:

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
   release changed the policy. The message gives the command that updates
   only the policy in your compose file, and the `docker compose up -d
   --force-recreate cashpilot-socket-proxy cashpilot-worker` that loads it.

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
[Mysterium](docs/isolation-check.md#mysterium).

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

### What changed in v1.0.0

v1.0.0 hardens fleet authentication. Instead of one shared key doing
everything, **each worker now gets its own key**. This is a breaking change
for existing fleets: worker and UI images must both be on v1.0.0+, and workers
re-enroll automatically on their first heartbeat after the upgrade.

| | Before (0.x) | v1.0.0 |
|---|---|---|
| Heartbeat, worker to UI | shared `CASHPILOT_API_KEY` | worker's **own** key (after enrollment) |
| Commands, UI to worker | shared key | that worker's **own** key |
| Role of `CASHPILOT_API_KEY` | authenticates everything | **enrollment/bootstrap only** |

**Why:** with per-worker keys, a key that leaks from one worker only affects
that one worker, and no worker can present another worker's identity to the
UI. The shared key stops being a fleet-wide credential once a worker is
enrolled.

> **The shared key is still sensitive.** `CASHPILOT_API_KEY` is now an
> *enrollment* credential, not a fleet-wide command key. It remains
> high-value: anyone holding it can enroll a new worker that then receives
> deploy specs (which carry service credentials). Keep protecting it.

#### How enrollment works (automatic)

1. A worker's **first** heartbeat authenticates with the shared
   `CASHPILOT_API_KEY`.
2. The UI issues that worker a unique key. The UI stores it **encrypted** and
   returns it to the worker **once**.
3. The worker persists the key under its own private `/data/.worker_key` and
   uses it from then on. The UI addresses that worker with the same key.
4. Once enrolled, the shared key **no longer works** for that worker.

You don't handle keys by hand: this all happens on the next heartbeat.

### Upgrade from 0.x

**Affects you if** you run CashPilot 0.x: the UI and its workers must both
move to v1.0.0.

**What breaks if you do nothing.** A worker left on a 0.x image under a v1.0.0
UI never finishes enrolling, and after 24 hours it goes offline. Step 2 below
says why.

**What to do.**

1. **Upgrade the UI** image to `drumsergio/cashpilot:1.0.0` or newer.
2. **Upgrade every worker** image to `drumsergio/cashpilot-worker` at the same
   version as the UI. A worker newer than its UI can refuse work: a 3.0
   worker refuses redeploys from a 2.x UI. Do not leave old-version workers
   running against a v1.0.0 UI. An
   old worker image only knows the shared key and cannot persist the one it is
   issued, so it never finishes enrolling. For the first 24 hours it keeps
   heartbeating on the shared key, which means anyone holding
   `CASHPILOT_API_KEY` can impersonate it for that long. After that it is
   refused and goes offline. The fleet page marks such a worker
   **enrollment incomplete**.

   The same thing happens to a current worker image whose `/data` is read-only
   or is not a persistent volume, because it has nowhere to keep
   `/data/.worker_key`. To recover one: fix the image or the volume, then
   remove the worker in the fleet page so it enrolls again from scratch.
3. Keep `CASHPILOT_API_KEY` **unchanged**: enrollment still needs it.
4. Restart the containers. Each worker auto-enrolls on its first heartbeat.
   Confirm that every worker shows **online** in the fleet dashboard.

Persist the worker's `/data` volume (the compose files already do) so its key
survives restarts.

#### Recovery and rollback

- **A worker's `/data` was wiped** (lost its key): it will try the shared key,
  which the UI now rejects for an enrolled worker. Remove the worker in the
  fleet dashboard, and it re-enrols on its own. The worker keeps sending the
  key it persisted. After roughly ten consecutive rejections, it discards that
  key and re-enrols with the shared one. Expect a few minutes of 401s in the
  worker log while that plays out. To skip the wait, delete `/data/.worker_key`
  on that host and restart the container.
- **Rolling back to 0.x:** roll back the UI and every worker together, never
  a worker alone. A 0.x worker under a v1.0.0 UI never finishes enrolling, and
  it goes offline after 24 hours (step 2 above). Set the UI image back to the
  0.x tag you ran before, then set every worker to the same 0.x tag.

---

## Everything else

No action required. Pull and recreate:

```bash
docker compose pull && docker compose up -d
```

**On a fleet, run that on every host.** It only updates the Compose project it
runs in, so remote workers stay on their old version until you upgrade them too,
and the UI and workers are meant to be on the same release.
