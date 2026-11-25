# XMRig (Monero CPU mining)

> **Category:** Mining | **Status:** Beta
>
> **Website:** [xmrig.com](https://xmrig.com)

XMRig mines Monero with your CPU. CashPilot runs the miner on a Linux Docker
worker with an amd64 or arm64 processor. Choose a pool and enter your public
Monero address. Keep your wallet keys and recovery phrase in your wallet.

## Before you deploy

- XMRig spends 1% of hashing time supporting its developers. CashPilot builds
  the signed upstream release with that fee intact. [XMRig fee source](https://github.com/xmrig/xmrig/blob/v6.27.0/src/donate.h)
- MoneroOcean is the default pool. It charges a 0% mining fee. It pays from
  0.3 XMR by default, and you can lower that threshold to 0.003 XMR. Payouts
  below 4 XMR can cost up to 0.0004 XMR. [MoneroOcean pool configuration](https://api.moneroocean.stream/config)
- The pool holds the balance until it pays your wallet. Check your chosen
  pool's fee and payout threshold before you start. CashPilot can track
  [SupportXMR](supportxmr.md) balances separately. Those balances are accrued.
- Check your hosting contract before mining on a rented server. Hetzner Cloud,
  for example, prohibits mining. [Hetzner Cloud terms](https://www.hetzner.com/legal/cloud-server/)

## Deploy

1. Open **Catalog**, select **Mining**, then add **XMRig**.
2. Choose an amd64 or arm64 worker with at least 3 GiB available for the miner.
3. Paste your public **Monero address** and choose a **Worker name**. Your pool
   can use the name to identify the machine.
4. Leave **Pool** set to MoneroOcean or enter another pool's host and port. For
   SupportXMR you can use `stratum+ssl://pool.supportxmr.com:9000`. Check its
   current fees and threshold in the [SupportXMR guide](supportxmr.md).
5. Set a **CPU thread target (%)**. XMRig can ignore this hint when the host
   reports incomplete CPU topology. Check the thread count in the logs.
6. Deploy and check the logs for a pool connection and accepted shares. Pool
   credit and payout can take longer.

## Check the power cost

Measure how many extra watts the machine draws while mining. Multiply the
extra watts by the hours it runs each month, divide by 1,000 and multiply by
your price per kWh. For example, 40 W running for 30 days uses 28.8 kWh.
Compare that cost with gross pool rewards. A machine that earns about $3 a
month breaks even on electricity at about $0.10/kWh in this example. Hardware
and hosting costs lower that break-even price. The XMR price, pool rewards and
hashrate all change.

## Troubleshooting

- **Slow hashrate.** Huge pages can improve RandomX speed. On a Linux host
  you control, `sudo sysctl -w vm.nr_hugepages=1280` reserves about 2.5 GiB
  of RAM until reboot. Reserve it only if other workloads can spare the
  memory. Watch the miner log for the huge-page allocation.
  [XMRig huge-page guide](https://xmrig.com/docs/miner/hugepages)
- **MSR optimization.** It requires privileged access to CPU registers.
  CashPilot disables it and runs XMRig as an unprivileged user. Expect lower
  hashrates than a tuned bare-metal benchmark.
  [XMRig MSR guide](https://xmrig.com/docs/miner/randomx-optimization-guide/msr)
- **The pool never connects.** Check the hostname and port. Some DNS filters
  block pool domains. Check the resolver on the worker and whether your
  network permits the connection. TLS helps protect the connection. Use a
  pool certificate fingerprint if you configure XMRig directly and need it
  to verify the pool's identity.
- **Antivirus or a NAS security advisor flags XMRig.** These tools can label
  coin miners as potentially unwanted applications (PUA). Verify the image
  and use it only on hardware where you have permission to mine.
- **Want to use P2Pool.** CashPilot's XMRig guide covers hosted pools. P2Pool
  requires a separate Monero node and P2Pool setup.
