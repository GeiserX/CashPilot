# MystNodes

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://mystnodes.com](https://mystnodes.com)

## Description

MystNodes (Mysterium Network) is a decentralized VPN and proxy network built on blockchain technology. You earn MYST tokens by running a node that provides VPN, proxy, and data scraping services to users. Requires NET_ADMIN capability and host networking for full functionality. Includes a built-in web UI for node management. Works on both residential and VPS connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $2 - $10 |
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

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-mysterium \
  --network host \
  --cap-add NET_ADMIN \
  -p 4449:4449 \
  -v mysterium-data:/var/lib/mysterium-node \
  mysteriumnetwork/myst --ui.address=0.0.0.0 --tequilapi.address=0.0.0.0 service --agreed-terms-and-conditions
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/mysterium.yml`](../../services/bandwidth/mysterium.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
