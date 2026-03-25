# Peer2Profit

> **Category:** Bandwidth Sharing | **Status:** Beta
> **Website:** [https://peer2profit.com](https://peer2profit.com)

## Description

Peer2Profit lets you earn passive income by sharing your internet connection. Works on both residential and VPS/datacenter connections. The community Docker image (mrcolorrain) includes a VNC-based GUI. Status reporting may be unreliable, and the platform has had intermittent availability issues. The official image (peer2profit/peer2profit_linux) is no longer maintained; the community alternative is recommended.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Crypto, Paypal |

> Earnings highly variable. Status reporting may be unreliable. VPS connections accepted. VNC port 5901 for GUI management.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux, Android, Docker |

## Setup Instructions

### 1. Create an account

Sign up at [Peer2Profit](https://peer2profit.com/r/{code}).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Peer2Profit** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `mrcolorrain/peer2profit`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `P2P_EMAIL` | Email | Yes | No | Your Peer2Profit account email |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-peer2profit \
  -p 5901:5901 \
  -e P2P_EMAIL="<Email>" \
  mrcolorrain/peer2profit
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | Percentage of referral earnings |
| New user bonus |  |
| How to get code | Dashboard > Referral > Copy your referral link |

---

*This guide was auto-generated from [`services/bandwidth/peer2profit.yml`](../../services/bandwidth/peer2profit.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
