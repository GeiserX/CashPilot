# ProxyBase

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxybase.io](https://proxybase.io)

## Description

ProxyBase is a bandwidth-sharing platform that pays users in cryptocurrency for sharing their unused internet connection. Uses a simple user ID-based authentication system. Works on residential connections. Official Docker image available.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $1 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Crypto payouts. Earnings depend on location and bandwidth usage.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO).

### 2. Get your credentials

After signing up and verifying your email, go to [peer.proxybase.org](https://peer.proxybase.org) and find your User ID in the dashboard. It looks like a short alphanumeric string (e.g. `nXzS3c6iTO`).

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyBase** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `proxybase/proxybase`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `USER_ID` | User ID | Yes | No | Your ProxyBase user ID from the dashboard |
| `DEVICE_NAME` | Device Name | Yes | No | Name shown in your ProxyBase dashboard -- container crashes without it (default: `cashpilot-{hostname}`) |
