# unMineable (CPU mining, paid in your coin)

> **Category:** Mining | **Status:** Beta
>
> **Website:** [unmineable.com](https://unmineable.com/?ref=awk6-j1z0)
>
> <small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

unMineable lets your CPU mine and pays you in a coin you choose, such as SHIB,
DOGE or XMR. CashPilot runs XMRig on a Linux Docker worker with an amd64 or
arm64 processor and points it at unMineable's RandomX pool. unMineable converts
what your CPU mines into your coin and pays your public address. You need no
account. Keep your wallet keys and recovery phrase in your wallet.

## Our referral code is on every worker

Every worker CashPilot deploys logs in as `COIN:ADDRESS.WORKER#awk6-j1z0`. The
part after the `#` is CashPilot's unMineable referral code. You cannot remove
it from the catalog entry.

- With the code, unMineable lowers your platform fee from 1% to 0.75%. You keep
  99.25% of your mining rewards.
- unMineable pays the code's owner, CashPilot's maintainer, 0.25% of your
  mining rewards. That money funds CashPilot.
- The terms are on unMineable's [referral page](https://unmineable.com/referrals).

If you do not want to use the code, run XMRig yourself instead of this entry.

## Before you deploy

- XMRig spends 1% of hashing time supporting its developers. CashPilot builds
  the signed upstream release with that fee intact. [XMRig fee source](https://github.com/xmrig/xmrig/blob/v6.27.0/src/donate.h)
- unMineable holds your balance until it reaches the coin's payment threshold,
  for example 0.03 XMR. Thresholds differ by coin and network. CashPilot reads
  the threshold unMineable reports for your address.
- Coins that need a memo or payment tag, such as XRP sent to an exchange, are
  not supported. Use a wallet address that needs no memo.
- Some coins can be paid on more than one network. unMineable chooses the
  network from your address. Check that your wallet accepts that network.
- Check your hosting contract before mining on a rented server. Hetzner Cloud,
  for example, prohibits mining. [Hetzner Cloud terms](https://www.hetzner.com/legal/cloud-server/)

## Deploy

1. Open **Catalog**, select **Mining**, then add **unMineable**.
2. Choose an amd64 or arm64 worker with at least 3 GiB available for the miner.
3. Enter the **Payout coin** ticker, such as `SHIB`, and your public **Payout
   address** for that coin. Choose a **Worker name** with letters, digits, `-`
   or `_`.
4. Set a **CPU thread target (%)**. XMRig can ignore this hint when the host
   reports incomplete CPU topology. Check the thread count in the logs.
5. Deploy and check the logs for `accepted` shares. unMineable credits the
   balance after it confirms the work, which can take a few hours.

## Track the balance

1. Open **Settings** and find **unMineable** under the collectors.
2. Enter the same payout address and coin ticker you deployed with. Enter the
   address alone, without the coin, worker name or referral code.
3. Select **Test**. Until unMineable credits the first shares of a new
   address, the test says it could not verify the payout address. The
   dashboard then shows the exact reason, such as "no record of this address
   yet" or "does not list the coin".

The balance CashPilot shows is accrued, not received. When unMineable pays you,
the balance drops and the dashboard asks you to confirm the payout. Only a
confirmed payout counts as received. See [Mining](../mining.md).

CashPilot prices BNB, BTC, DOGE, ETC, KAS, LTC, PRL, SHIB, TRX, USDT, USDC and XMR.
Any other coin is tracked in its own units, without a value in your currency.

## Check the power cost

Measure how many extra watts the machine draws while mining. Multiply the
extra watts by the hours it runs each month, divide by 1,000 and multiply by
your price per kWh. For example, 40 W running for 30 days uses 28.8 kWh.
Compare that cost with what unMineable credits you. The coin price,
unMineable's conversion rate and your hashrate all change.

## Troubleshooting

- **"does not accept this address" on the dashboard, or "Invalid address" in
  the miner log.** The address is not valid for that coin on a network
  unMineable pays. Check the coin ticker and the address.
- **The pool never connects.** Some DNS filters block pool domains. Check the
  resolver on the worker and whether your network permits the connection.
  The connection uses TLS on port 443 and accepts the pool's self-signed
  certificate without checking a CA chain.
- **Slow hashrate.** Huge pages can improve RandomX speed. See the
  [XMRig guide](xmrig.md#troubleshooting) for the host step.
- **Antivirus or a NAS security advisor flags XMRig.** These tools can label
  coin miners as potentially unwanted applications (PUA). Verify the image
  and use it only on hardware where you have permission to mine.
- **unMineable accounts and aliases.** CashPilot uses the address login, which
  needs no account. A worker that logs in with an unMineable alias is not
  tracked here.
