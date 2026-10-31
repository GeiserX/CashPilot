# Bytelixir

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://bytelixir.com](https://bytelixir.com)

## Description

Bytelixir lets you earn passive income by sharing unused internet bandwidth. Supports Windows and Android only: the official FAQ states no Linux or Docker client is planned, iOS is unsupported, and macOS is not offered. Earnings depend heavily on location. Web dashboard at dash.bytelixir.com for tracking. No Docker image available.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Earnings vary heavily by location. No Docker image, and the official FAQ says none is planned. Windows desktop app or Android app required.

## Cashing out

Crypto only. The minimum depends on the coin: USDT $5, USDC $5, TON $8, LTC $10, ETH $40, BTC $250. You type the address in each request. Requests are handled in working hours, within 24 hours.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Android |

## Setup Instructions

### 1. Create an account

Sign up at [Bytelixir](https://bytelixir.com/r/OYEIRE0VSZBZ).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Install the app

Download the Windows or Android app from the **Download** section of your dashboard at
[dash.bytelixir.com](https://dash.bytelixir.com); those are the only supported platforms,
and the official FAQ states no Linux or Docker client is planned.

### 3. Track earnings in CashPilot

There is no container to deploy; CashPilot tracks Bytelixir's earnings through your
dashboard session. Log in at dash.bytelixir.com with **Remember Me** ticked, press F12 →
Application → Cookies, and paste three values under **Settings → Earnings collection**:
`bytelixir_session`, `remember_web_…` and `XSRF-TOKEN`. The session cookie alone expires
about two hours after you copy it; the `remember_web` cookie lasts about a year and is what
keeps collection working. Refresh them when the collector reports they expired.
