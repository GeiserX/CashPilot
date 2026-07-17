# ProxyBase

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxybase.org](https://proxybase.org)

## Description

ProxyBase is a bandwidth-sharing platform that pays users in cryptocurrency for sharing their unused internet connection. You authenticate the peer client with an **Access Token** from your dashboard. Residential IPs earn the most, but datacenter IPs are also supported (at lower traffic). Official multi-arch Docker image (amd64/arm64/armv7).

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
| Residential IP | Not required -- residential earns the most; datacenter IPs are supported at lower traffic |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker (amd64/arm64/armv7), Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO). If the referral field is not pre-filled, enter referral code `nXzS3c6iTO` in the **Referral Code** box before creating your account.

### 2. Get your Access Token

After signing up and verifying your email, open your [dashboard](https://peer.proxybase.org/dashboard) and copy your **Access Token** — it is shown in the Docker command on the setup page and looks like a short alphanumeric string.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyBase** in the service catalog and click **Deploy**. Enter your Access Token and a device name, and CashPilot will handle the rest.

> **Upgrading from an older CashPilot?** ProxyBase moved to a new client image and renamed its credentials (the old `USER_ID`/`DEVICE_NAME` are now the **Access Token** and **Device Name**). Re-deploy ProxyBase from the catalog and re-enter your Access Token so the new client can authenticate — existing containers built on the old image will stop earning.

## Docker Configuration

- **Image:** `ghcr.io/proxybaseorg/peer-cli` (pinned by digest)
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `ID` | Access Token | Yes | Yes | Your ProxyBase Access Token from the dashboard |
| `NAME` | Device Name | Yes | No | Any name to identify this device in your ProxyBase dashboard -- the client won't start without it (default: `cashpilot-{hostname}`) |
