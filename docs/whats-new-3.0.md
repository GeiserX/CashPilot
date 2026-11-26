# What's new in 3.0

CashPilot 3.0 changes how the UI and the workers agree on which container to
replace. A worker now replaces a running container only when the UI names that
exact container. A 2.x UI cannot do that, so a 3.0 worker under a 2.x UI
refuses to replace anything. That is why this release is a major version: the
UI and every worker must move to 3.0 together, the UI first. The same release
adds mining, GPU grants and new earnings figures. This page lists what changed,
with a link to the page for each part, and then
[how to upgrade](#upgrading-from-2x).

## Why upgrade

- **A redeploy cannot replace the wrong container.** Before 3.0, a redeploy
  replaced whatever container had the service's name. A container that
  changed outside CashPilot could be replaced, and the files in it lost. In
  3.0 the UI shows you the container IDs it is about to replace, and the
  worker refuses if the container changed in the meantime. Proxied copies get the same check on Start and on tunnel
  recovery.
- **GPU services get a GPU, and nothing else does.** A catalog service that
  declares a GPU gets that one device. Every other container gets
  `NVIDIA_VISIBLE_DEVICES=void`, so a CUDA image cannot take the GPU through a
  host whose default Docker runtime is `nvidia`.
- **Mining is in the catalog** (beta), with pool balances read from your
  public payout address only.

## Approval before a container is replaced

- A redeploy, a settings change or a rename of a running service shows the
  containers it will replace, by ID, and waits for your approval.
- A proxied copy saves the full Docker ID of its container. A copy whose ID is
  not saved yet, or changed, asks for your approval on its next Start.
  Automatic recovery skips such a copy and shows an alert on the Fleet page.
- From the Fleet page you can deploy to a joined CashPilot Desktop, and stop
  and start its services, once it runs Desktop 2.0.
  [Fleet dashboard](fleet.md#fleet-dashboard)

## Mining (beta)

- **A new Mining section in the catalog.** Run [XMRig](guides/xmrig.md) or
  [unMineable](guides/unmineable.md) on your CPU, or
  [SRBMiner-Multi](guides/srbminer-multi.md) or
  [KRig for Kryptex Pool](guides/kryptex-pearl.md) on an NVIDIA GPU. The CPU
  thread setting caps the threads the miner starts, also on virtual machines.
- **Pool balances without a key.** CashPilot reads the unpaid balance of
  [OCEAN](guides/ocean.md), [SupportXMR](guides/supportxmr.md),
  [HeroMiners Kaspa](guides/herominers-kas.md),
  [2Miners ETC](guides/2miners-etc.md) and unMineable from your public payout
  address. It shows what your hashrate should earn next to what the pool
  credited. [Mining](mining.md)
- **Miners on your network.** Set `CASHPILOT_MINERS` on a worker, and Fleet
  shows the hashrate, temperature and power of Bitaxe (AxeOS) and cgminer
  devices. [LAN miner readings](mining-devices.md)

## GPU grants (beta)

A catalog entry can declare the GPU it needs. The worker then passes in one
NVIDIA device request, or the AMD or Intel render node, and nothing more. It
gives each miner its own GPU, and it notices when a grant is gone. A custom service and a proxied copy never get a GPU.
[GPU services](gpu.md)

## Earnings and running costs

- **Bitcoin and Kaspa payout addresses** are read without a key.
  `CASHPILOT_ONCHAIN_URL_<CHAIN>` points the lookup at your own server.
  [On-chain payout balances](onchain.md)
- **Coin balances keep 12 decimals**, so a small payout no longer shows as
  0.00.
- **Break-even tariff, fixed-price hosting and heat credit** on the Fleet
  page's running costs. A miner tracked through its pool is no longer counted
  as running on free electricity. [Running costs](fleet.md#running-costs)
- **Income export.** `GET /api/earnings/income.csv` writes your income for a
  tax tool. [Income export for taxes](income-export.md)
- A catalog entry with no account to create shows **Visit** instead of
  **Sign Up**.

## Companion apps

- **[CashPilot Desktop](https://github.com/GeiserX/CashPilot-Desktop) 2.0.0 or
  later** takes server commands from a 3.0 server. It offers its command
  address only to a server that says it can command a Desktop safely, and 3.0
  is the first such release. Under a 2.x server, Desktop 2.0 only reports what
  runs on it, and so does Desktop 1.7.0 under a 3.0 server. After an upgrade
  from Desktop 1.x, server commands start off until you turn them on in the
  Desktop's dashboard. Desktop does not update itself: download it from its
  releases page.
- **[cashpilot-mcp](https://github.com/GeiserX/cashpilot-mcp) 0.4.0 or later**
  is needed to redeploy a running service, because it sends the confirmation
  that 3.0 asks for.
- **[CashPilot for Android](https://github.com/GeiserX/CashPilot-android)** and
  the Home Assistant integration need no update.

## Upgrading from 2.x

The compose files pin a release series (`drumsergio/cashpilot:2.10`), so
`docker compose pull` and the in-app **Update** button stay inside 2.x. Moving
to 3.0 means taking the new compose file or changing the tags.

### 1. Back up first

Back up the dashboard's `/data` and your node identities, as for 2.0.
[Backing up and restoring](backup-restore.md#backup) and
[Backing up node identities](backup.md) have the steps.

### 2. Upgrade the UI first

On the UI host, take the 3.0 compose file, or change every
`drumsergio/cashpilot:2.10` and `drumsergio/cashpilot-worker:2.10` tag to
`3.0`. Then run:

```sh
docker compose up -d --force-recreate
```

Then do the same on every worker host. A 3.0 UI still deploys to a 2.10
worker. A 3.0 worker under a 2.x UI refuses to replace a running container and
tells you to update the UI.

On Unraid, both apps follow `:latest`, so the next update of either app takes
it to 3.0. Update the UI app first, then the worker app.

### 3. What may ask for a step

[UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md#30-upgrade-the-ui-first-then-change-the-image-tags)
has the details and the commands for each of these:

- A worker behind the socket proxy needs the new proxy policy before it
  deploys a service that uses a GPU.
- A service that sets an `NVIDIA_` variable is refused until you remove it.
- A proxied copy made before 3.0 asks you once to approve its containers.
- Scripts that call `POST /api/deploy/{slug}` must confirm a replacement in a
  second call.

### Rolling back

3.0 adds one table to the database and changes no other, so 2.10.2 opens the
same database. To go back, put back the 2.10 compose file on the UI host and
on every worker host, and run `docker compose up -d --force-recreate` on each.
Move the UI and every worker back together.
