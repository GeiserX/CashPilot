# Bitping

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://app.bitping.com](https://app.bitping.com)

## Description

Bitping is a decentralized network monitoring platform that pays you for running a node. Your node performs website monitoring, latency testing, and network quality checks for Bitping's customers. Works on both residential and VPS connections. The Docker image logs in with the `BITPING_EMAIL` and `BITPING_PASSWORD` environment variables on first start, then persists the session in a volume mount so restarts do not re-authenticate.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Earnings depend on network quality and demand for monitoring from your location. VPS nodes accepted.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Bitping](https://app.bitping.com).

### 2. Get your credentials

The node uses your normal account login: the same email and password you use at [app.bitping.com](https://app.bitping.com). No separate API token is needed.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Bitping** in the service catalog and click **Deploy**. Enter your email and password; the node logs itself in on first start and stores its session in the `bitping-data` volume.

> **Deployed Bitping before and it never earned anything?** CashPilot releases **v0.2.32 through v1.35.1** deployed the container with **no credentials at all** (the catalog had lost the two variables), so the node sat waiting for a login forever. Upgrade CashPilot, then **Deploy** Bitping again from the catalog with your email and password.

## Docker Configuration

- **Image:** `bitping/bitpingd`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `BITPING_EMAIL` | Email | Yes | No | Your Bitping account email |
| `BITPING_PASSWORD` | Password | Yes | Yes | Your Bitping account password |
