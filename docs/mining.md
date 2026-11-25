# Mining

The **Mining** section of the catalog is for crypto you mine with your own hardware. Today it tracks a pool you already mine on: you point your miner at the pool, give CashPilot the payout address, and CashPilot reads what the pool holds for you. CashPilot runs no miner for these entries.

| Pool | Coin | Guide |
|---|---|---|
| OCEAN | Bitcoin | [OCEAN](guides/ocean.md) |

## Accrued is not received

A pool keeps the coins your hashrate earns until they pass its payout threshold. That **unpaid balance** is money the pool owes you. It is not in your wallet yet, and a pool that closes or changes its rules may never pay it.

CashPilot keeps the two apart:

- The **balance** of a pool is its unpaid balance: the same "waiting" figure every provider's balance is. The catalog marks each pool entry with `collector.accrual: pool`, which says its balance is accrued, not received.
- When the pool pays you, the unpaid balance drops. The dashboard asks you to confirm that drop as a **payout**. Only a confirmed payout counts as received, in the lifetime total and on the Payouts page.
- The cash-out reminder skips pools. They pay by themselves, so there is nothing for you to request.

## No keys, ever

A pool is tracked by its **public payout address**. It is the same address anyone can look up on the pool's stats page, and it unlocks no funds. CashPilot stores it in plain text so Settings can show it back to you.

CashPilot never asks for a private key, a seed phrase or an exchange login, and it never signs or moves funds. See [What we will not build](roadmap.md#g-what-we-will-not-build).

## Fees

A pool keeps a fee from what your hashrate earns. Each guide states the pool's fee from the pool's own pages. The balance CashPilot reads is already net of that fee.

## What is not tracked yet

- **Solo pools** (CKPool solo, Public Pool). They hold no balance: you are paid only when your own miner finds a block. A balance read from them would always be 0, so CashPilot does not invent one.
- **P2Pool.** It pays each share straight into your wallet when a block is found, so nothing accrues at the pool. Tracking it needs a "received" reading of the wallet, which CashPilot does not have yet.
- **Lightning payouts.** A pool that pays you over Lightning sends small amounts CashPilot cannot see. It sees on-chain payouts only.
- **Pools that need an API key** (NiceHash, Braiins Pool). They come later.
