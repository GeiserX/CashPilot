# SRBMiner-Multi (GPU mining)

> **Category:** Mining | **Status:** Beta
>
> **Website:** [github.com/doktor83/SRBMiner-Multi](https://github.com/doktor83/SRBMiner-Multi)

SRBMiner-Multi mines Pearl, Zano or Ravencoin with one NVIDIA GPU. CashPilot
runs it on a Linux amd64 Docker worker. Choose a pool and enter your public
payout address. Keep your wallet keys and recovery phrase in your wallet.

!!! warning "Beta"

    This entry has not run on a real GPU yet. The image download, the
    checksum checks and a TLS connection to the pool were tested without a
    GPU. Nobody has logged in to the pool with this entry yet. The
    [GPU grant](../gpu.md) is in beta too.

## Before you deploy

- SRBMiner-Multi keeps 2% of hashing time on Pearl (`pearlhash`) and 0.85% on
  Zano (`progpow_zano`) and Ravencoin (`kawpow`).
  [SRBMiner-Multi fee list](https://github.com/doktor83/SRBMiner-Multi/blob/3.9.0/README.md)
- The miner is closed source, and its license does not let us ship it in the
  image. The [CashPilot image](https://github.com/GeiserX/CashPilot/tree/main/images/srbminer-multi)
  downloads the official release from GitHub at first start. It checks the
  archive and the executable against SHA-256 values we pinned. The worker
  needs outbound HTTPS to GitHub and its release asset host.
- HeroMiners is the default Pearl pool. It charges a 1% pool fee, checks
  payouts every hour and pays from 1 PRL.
  [HeroMiners Pearl pool configuration](https://pearl.herominers.com/api/stats)
- The pool holds the balance until it pays your wallet. CashPilot does not
  read Pearl pool balances yet. Check the balance on the pool's site.
- Check your hosting contract before mining on a rented server. Hetzner Cloud,
  for example, prohibits mining. [Hetzner Cloud terms](https://www.hetzner.com/legal/cloud-server/)

## What the worker needs

- A Linux amd64 host with an NVIDIA GPU. The image has no arm64 build, and
  AMD and Intel GPUs are not supported in this entry.
- The NVIDIA Container Toolkit, set up as [GPU services](../gpu.md#what-your-host-needs)
  describes. Without it, Docker refuses to start the container.
- One copy per machine. The miner gets one GPU, and a second copy would share it.

## Deploy

1. Open **Catalog**, select **Mining**, then add **SRBMiner-Multi**.
2. Choose a worker with an NVIDIA GPU.
3. Paste your public **Payout address** and choose a **Worker name**. A Pearl
   address starts with `prl1`. The pool shows the worker name next to your
   address.
4. Leave **Algorithm** on `pearlhash` and **Pool** on `pearl.herominers.com:1200`
   to mine Pearl. HeroMiners also lists regional servers, such as
   `de.pearl.herominers.com:1200` or `us.pearl.herominers.com:1200`. For Zano
   or Ravencoin, choose `progpow_zano` or `kawpow`, and enter that coin's
   address and a pool for it.
5. Leave **Encrypt the pool connection (TLS)** on `true` unless your pool's
   port takes only plain connections. HeroMiners' port 1200 takes both.
6. Deploy and watch the logs. The first start downloads the miner. Then the
   miner writes its log, with the GPU, the pool connection and accepted shares.

## Check the power cost

Measure how many extra watts the machine draws while mining. Multiply the
extra watts by the hours it runs each month, divide by 1,000 and multiply by
your price per kWh. For example, a GPU that draws 140 W for 30 days
uses about 101 kWh. At $0.20/kWh that costs about $20 a month. Compare that
cost with what the pool credits you. The Pearl price, the network difficulty
and your hashrate all change.

On the Fleet page, enter the machine's total draw while it mines. CashPilot
uses it for the machine's cost. The SRBMiner-Multi row shows its own
electricity cost as unknown, because CashPilot cannot split one machine's draw
between its GPU and its other services.

## Troubleshooting

- **`could not select device driver "nvidia"`.** Docker has no NVIDIA runtime.
  Install the NVIDIA Container Toolkit and restart Docker.
- **`download failed`.** The worker cannot reach GitHub. Allow outbound HTTPS
  to `github.com` and its release asset host, then restart the miner.
- **`SHA-256 mismatch`.** The downloaded file is not the release CashPilot
  pinned. The miner does not start. Update the worker's catalog, and report
  it if the error stays.
- **The container stops at once with an empty log outside CashPilot.** The
  miner quits without a message when it runs as the container's first
  process. CashPilot's worker and its Compose export start it behind Docker's
  init. In a Compose file of your own, add `init: true` to the service. With
  `docker run`, add `--init`.
- **The pool never connects.** Check the host and port. Some DNS filters
  block pool domains. Check the resolver on the worker and whether your
  network permits the connection.
- **Antivirus or a NAS security advisor flags the miner.** These tools can
  label coin miners as potentially unwanted applications (PUA). Use the miner
  only on hardware where you have permission to mine.
