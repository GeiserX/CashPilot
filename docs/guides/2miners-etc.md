# 2Miners ETC

> **Category:** Mining | **Status:** Beta
>
> **Website:** [2Miners Ethereum Classic](https://etc.2miners.com/)

CashPilot reads the unpaid balance of an Ethereum Classic address on the
2Miners pool. You run the miner yourself.

## Pool terms

| Metric | Value |
|---|---|
| Pool fee | 1% |
| Minimum payout threshold | 0.1 ETC, adjustable on the pool site |
| Payout schedule | 2Miners checks for eligible payouts every two hours |
| Account | The pool uses your payout address in place of an account |

The 2Miners pool also offers BTC and TON payouts. This catalog entry tracks
addresses paid in ETC. See the [pool FAQ](https://etc.2miners.com/faq) for
payout terms.

## Setup

1. Pick a server and port from the [2Miners setup guide](https://etc.2miners.com/help).
   Set the algorithm to ETCHash and use your public ETC address as the miner's username.
2. In CashPilot, open **Settings**, then **Earnings collection**, and select
   **2Miners ETC**. You can also get there from **Add your payout address**
   in the setup wizard.
3. Paste your public address into **Address**. Include the `0x` prefix and
   leave out any worker name.
4. Click **Save credentials**. Choose **Collect now** to read the balance
   immediately, or wait for the next hourly run.

CashPilot stores the address in plain text. Anyone with it can look up its
mining activity on the pool's site.

## Balances and payouts

**Balance** shows the ETC the pool still holds for you. The pool lists
immature rewards separately. They enter the unpaid balance when they mature.
The **Payouts** page shows the address and can read its wallet balance from
Ethereum Classic.

A drop of at least 0.1 ETC can prompt you to confirm a payout. Check your
wallet for the amount you received. A pool credit between readings can make
the drop smaller than the payout. See [Mining](../mining.md).

## Troubleshooting

- If 2Miners has no record of the address, check it against your miner's username.
  If you just started mining, wait for your first shares.
- If CashPilot reports an old share, check that your miner is running and
  sending shares to 2Miners. CashPilot still shows the pool balance.
