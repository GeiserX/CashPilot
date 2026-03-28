# ProxyBase

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxybase.io](https://proxybase.io)

## Description

ProxyBase is a bandwidth-sharing platform that pays users in cryptocurrency for sharing their unused internet connection. Uses a simple user ID-based authentication system. Works on residential connections. Official Docker image available.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $5 |
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
| Supported platforms | Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyBase** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `proxybase/proxybase`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `USER_ID` | User ID | Yes | No | Your ProxyBase user ID from the dashboard |
| `DEVICE_NAME` | Device Name | No | No | Name shown in your ProxyBase dashboard (default: `cashpilot-{hostname}`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-proxybase \
  -e USER_ID="<User ID>" \
  -e DEVICE_NAME="<Device Name>" \
  proxybase/proxybase
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/proxybase.yml`](../../services/bandwidth/proxybase.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
