# MystNodes

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://mystnodes.com](https://mystnodes.com)

## Description

MystNodes (Mysterium Network) is a decentralized VPN and proxy network built on blockchain technology. You earn MYST tokens by running a node that provides VPN, proxy, and data scraping services to users. Requires NET_ADMIN capability and host networking for full functionality. Includes a built-in web UI for node management. Works on both residential and VPS connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Earnings in MYST tokens. Residential IPs earn significantly more. Node WebUI at port 4449 for management. VPS accepted. Important: after first run, set your beneficiary (settlement) wallet via the node WebUI or CLI to match your mystnodes.com account -- this links on-chain earnings to your cloud dashboard.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android, Browser-Extension |

## Setup Instructions

### 1. Create an account

Sign up at [MystNodes](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **MystNodes** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `mysteriumnetwork/myst`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

No environment variables required.
