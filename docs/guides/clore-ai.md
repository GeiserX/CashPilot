# Clore.ai

> **Category:** GPU Compute | **Status:** Active
>
> **Website:** [clore.ai](https://clore.ai/register?ref_id=hq5z8kvc)
>
> <small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

## Description

Clore.ai is a peer-to-peer GPU marketplace. You list a Linux machine with NVIDIA GPUs, set your own spot and on-demand prices, and renters run their own Docker containers on it. You are paid only for the minutes it is rented, in CLORE, BTC, USDT or USDC. Hosting needs an x86_64 machine on Ubuntu 22.04 or newer (or HiveOS), a working NVIDIA driver and at least 100 Mbps up and down. AMD GPUs are not supported.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $490 (estimate) |
| Per | GPU |
| Minimum payout | 200 CLORE (or 0.0001 BTC, or 10 USDT/USDC) |
| Payout frequency | On request |
| Payment methods | Crypto (CLORE, BTC, USDT, USDC) |

> Paid only for rented minutes, at the price you set. $490 is Clore's own ceiling for one RTX 4090 listed by the minute; smaller cards earn less and an idle card earns nothing. Clore keeps 5% (on-demand) or 1.25% (spot) of each rental, plus 15% when the renter pays in BTC, USDT or USDC instead of CLORE.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 100 Mbps up and down |
| GPU required | Yes (NVIDIA only) |
| Minimum storage | 32GB |
| Supported platforms | Linux (x86_64, Ubuntu 22.04+ or HiveOS) |

## Setup Instructions

### 1. Create an account

Sign up at [Clore.ai](https://clore.ai/register?ref_id=hq5z8kvc).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Run it outside CashPilot

CashPilot cannot deploy Clore.ai. The catalog has no Docker image for it, so its row in **Catalog** shows **Visit** instead of **Add**. In Clore's dashboard, open **My Servers**, click **Add Server** and run the install command it gives you as root on the GPU machine. The installer sets up Docker and Clore's hosting agent, but not the NVIDIA driver: `nvidia-smi` must work first. Renters reach their containers through forwarded ports (22, 8080 and 3000-4000 by default), so open or forward them on your router. CashPilot does not read Clore.ai earnings either, so check them in the provider's dashboard.

## Docker Configuration

None. The catalog has no Docker image for Clore.ai.
