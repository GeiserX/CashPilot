# HeroMiners Kaspa

> **Category:** Mining | **Status:** Beta
>
> **Website:** [HeroMiners Kaspa](https://kaspa.herominers.com/)

HeroMiners pools work from Kaspa miners and pays them in KAS. CashPilot reads
the unpaid balance for your public payout address. You run the miner yourself.

## Pool terms

| | |
|---|---|
| Pool fee | 0.9% |
| Minimum payout threshold | 1 KAS, adjustable on the pool site |
| Payout schedule | HeroMiners checks for eligible payouts every hour |
| Account | The pool uses your Kaspa address in place of an account |

See the [pool dashboard](https://kaspa.herominers.com/) for current terms and
mining servers.

## Setup

1. Pick a server and port for your hardware from the pool's **Start** page.
   Use your public Kaspa payout address as your miner's username.
2. In CashPilot, open **Settings**, then **Earnings collection**, and select
   **HeroMiners Kaspa**. You can also get there from **Add your payout address**
   in the setup wizard.
3. Paste your public address into **Address**. Include the `kaspa:` prefix
   and leave out any worker name.
4. Click **Save credentials**. Click **Collect now** to read the balance
   immediately, or wait for the next hourly run.

CashPilot stores this address in plain text. Anyone with the address can look
up its mining activity on the pool's site.

## Balances and payouts

The **Balance** is the KAS the pool still holds for you. The **Payouts** page
shows the destination address. When CashPilot sees a balance drop of at least
1 KAS, it can ask you to confirm a payout. Check your wallet for the amount you
received. A pool credit between readings can make the drop smaller than the
payout. See [Mining](../mining.md).

## Troubleshooting

- If HeroMiners has no record of the address, check it against your miner's
  username. If you have just started mining, wait for your first shares.
- If HeroMiners rejects the address, copy the full mainnet address from your
  wallet. Check that it starts with `kaspa:`.
- If CashPilot reports an old share, check that your miner is running and
  sending shares to HeroMiners. CashPilot still shows the pool balance.
