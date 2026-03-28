# ProxyLite

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxylite.ru](https://proxylite.ru)

## Description

ProxyLite monetizes your internet traffic by sharing bandwidth with verified organizations. Works on both residential and VPS/datacenter connections. Simple setup requiring only a user ID from the dashboard. Offers a generous 15% lifetime referral commission.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto, Paypal |

> Residential IPs earn more. VPS/datacenter connections accepted at lower rates.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyLite](https://proxylite.ru/?r=KMUPRZIZ).

### 2. Get your credentials

After signing up at [proxylite.ru](https://proxylite.ru), your User ID is visible in the dashboard at `lk.proxylite.ru`. It's a numeric ID (e.g. `521465`).

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyLite** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `proxylite/proxyservice`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `USER_ID` | User ID | Yes | No | Your ProxyLite account ID (found in dashboard at lk.proxylite.ru after registration) |
