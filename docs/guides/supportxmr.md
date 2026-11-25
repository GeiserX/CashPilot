# SupportXMR

> **Category:** Mining | **Status:** Beta
>
> **Website:** [supportxmr.com](https://www.supportxmr.com)

## Description

SupportXMR is a Monero mining pool. Your miner uses your payout address as its username. CashPilot reads the unpaid balance SupportXMR holds for that address. You run the miner yourself.

## Payouts

| Metric | Value |
|--------|-------|
| Automatic payout | When your balance reaches your threshold, 0.1 XMR by default |
| Payout on request | From 0.01 XMR, for a 0.001 XMR fee |
| Payment method | Monero |
| Pool fee | 0.6% (PPLNS) |

Earnings depend on your hashrate, the network difficulty and the pool's luck. CashPilot gives no monthly estimate.

## Requirements

| Requirement | Value |
|-------------|-------|
| Hardware | A computer that runs a Monero miner, such as XMRig |
| Residential IP | No |
| Account | None. The pool identifies you by your Monero address |

## Setup

### 1. Point your miner at SupportXMR

SupportXMR recommends XMRig. In your miner's settings:

- Set **Pool** to `pool.supportxmr.com:3333`. Use port 5555 or 7777 for faster machines, or 9000 for TLS.
- Enter your Monero address as the **Username**.
- Enter a worker name or `x` as the **Password**.

Copy the address from your wallet and check it before you start mining.

### 2. Track it in CashPilot

1. Open **Settings**, go to **Earnings collection** and open **SupportXMR**. The setup wizard's **Add your payout address** button opens it for you.
2. Paste the same Monero address into **Address**, without any `.workername` or `+difficulty` part.
3. Click **Save credentials**. CashPilot reads the balance at the next hourly run, or at once when you click **Collect now**.

You can also save the address from the dashboard's credentials window. That window checks the address with SupportXMR as soon as you save it.

CashPilot stores the address in plain text. Anyone with the address can look up your pool stats on supportxmr.com. Use only your public payout address in CashPilot.

## What CashPilot shows

- **Balance** shows the Monero the pool still holds for you. See [Mining](../mining.md).
- The dashboard can detect a balance drop and ask you to confirm a payout. Check your wallet before confirming the amount you received.
- The **Payouts** page shows the destination address. Monero hides wallet balances on-chain, so CashPilot leaves the wallet balance unread.

## Troubleshooting

- **"SupportXMR has no record of this address yet."** Check that the address matches your miner's username. CashPilot reports it as unknown when the pool returns zero for total hashes, last share time, amount due and amount paid. A new miner can show this until its first shares arrive.
- **"This is not a Monero address."** CashPilot checks the format before it asks SupportXMR. Remove any `.workername` or `+difficulty` part and any spaces.
- **"SupportXMR has had no shares from this address for N h."** Check that your miner is running and pointed at SupportXMR. CashPilot still reads the balance.
- **The balance does not move for the first hours.** A new miner's balance starts moving about 2 hours after its first shares, once the pool's blocks confirm.

## Limits

- **A payout can look smaller than it was.** CashPilot reads the balance once an hour. If the pool credits your address between two readings, the drop it sees is the payout minus that credit.
- CashPilot looks for balance drops of at least 0.01 XMR, the pool's minimum payout on request.
