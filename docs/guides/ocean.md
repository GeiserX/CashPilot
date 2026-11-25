# OCEAN

> **Category:** Mining | **Status:** Beta
>
> **Website:** [ocean.xyz](https://ocean.xyz)

## Description

OCEAN is a Bitcoin mining pool with no account: your miner logs in with your Bitcoin address as its username, and the pool pays that address. CashPilot does not run a miner here. It reads the unpaid balance OCEAN holds for your address, so you see what your ASIC (a Bitaxe, an Antminer) has earned next to your other income. The unpaid balance is earned but not received: OCEAN pays it on-chain once it passes the payout threshold.

## Payouts

| Metric | Value |
|--------|-------|
| Minimum payout | 0.01048576 BTC, on-chain |
| Payout frequency | When a block pays your balance past the threshold |
| Payment methods | Bitcoin, on-chain (Lightning is opt-in) |
| Pool fee | 2%, or 1% when you build your own block templates with DATUM |

What you earn depends only on your hashrate, the network difficulty and the pool's luck. CashPilot gives no monthly estimate.

## Requirements

| Requirement | Value |
|-------------|-------|
| Hardware | A Bitcoin ASIC miner (a Bitaxe, an Antminer) |
| Residential IP | No |
| Account | None. The Bitcoin address is the identity |

## Setup

### 1. Point your miner at OCEAN

In your miner's settings, follow [OCEAN's own guide](https://ocean.xyz/getstarted):

- **Pool URL:** `stratum+tcp://mine.ocean.xyz:3334` (some miners want the host `mine.ocean.xyz` and the port `3334` apart).
- **Username:** your Bitcoin address. You may add a worker name after a dot, such as `bc1q….bitaxe`.
- **Password:** `x`.

Copy and paste the address. OCEAN does not check it, so a typo mines for an address nobody owns.

### 2. Track it in CashPilot

1. Open **Settings** and find **OCEAN** under the collectors.
2. Paste the same Bitcoin address into **Address**, without the `.workername` part.
3. Save. CashPilot starts reading the balance within the hour, and **Test** checks it at once.

CashPilot stores the address in plain text. It is public: anyone can look up its stats on ocean.xyz, and it unlocks no funds. CashPilot never asks for a key or a seed.

## What CashPilot shows

- **Balance** is OCEAN's **unpaid** balance: Bitcoin the pool has credited to your address but not paid yet. It is earned, not received. See [Mining](../mining.md).
- **Payouts.** When OCEAN pays you on-chain, the unpaid balance drops, and the dashboard asks you to confirm the payout. Only a confirmed payout counts as money received.
- **Payouts page.** The address shows as the place OCEAN pays to.

## Troubleshooting

- **"OCEAN has no record of this address yet."** The address in Settings is not one OCEAN has seen. Check it against your miner's username, character for character. A miner that has not sent its first shares shows this too, so wait a few minutes after you start it.
- **"This is not a Bitcoin address."** CashPilot checks the format before it asks OCEAN. Remove the `.workername` part and any spaces.
- **"OCEAN has had no shares from this address for N h."** Your miner is off, or it mines somewhere else. The balance is still read.
- **"OCEAN pays this address in every block it finds."** A large miner can pass the threshold in every block, so the unpaid balance stays at 0. CashPilot cannot count those payouts yet.

## Limits

- **Lightning payouts are not detected.** If you turned on Lightning payouts, OCEAN pays small amounts over Lightning, and CashPilot does not see them. It sees on-chain payouts only.
- **A payout can look smaller than it was.** CashPilot reads the balance once an hour. If a block credits your address between two readings, the drop it sees is the payout minus that credit.
