# URnetwork

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://ur.io](https://ur.io)

## Description

URnetwork is a decentralized VPN and bandwidth-sharing network. You earn by providing bandwidth as a community provider. Uses JWT-based authentication. Official Docker image from Bring Your Own (bringyour). Supports both direct mode (with tun device) and proxy mode (SOCKS5).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $5 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Works on VPS and residential. Crypto payouts. Supports proxy mode for multi-IP setups.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [URnetwork](https://ur.io).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **URnetwork** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `bringyour/community-provider`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UR_AUTH_TOKEN` | Auth Token | Yes | Yes | Your URnetwork authentication token from the dashboard |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-urnetwork \
  -v urnetwork-data:/root/.urnetwork \
  -e UR_AUTH_TOKEN="<Auth Token>" \
  bringyour/community-provider provide
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/urnetwork.yml`](../../services/bandwidth/urnetwork.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
