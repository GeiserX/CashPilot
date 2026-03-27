# Bitping

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://app.bitping.com](https://app.bitping.com)

## Description

Bitping is a decentralized network monitoring platform that pays you for running a node. Your node performs website monitoring, latency testing, and network quality checks for Bitping's customers. Works on both residential and VPS connections. The Docker image requires interactive initial setup to authenticate, then persists credentials in a volume mount.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $5 |
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
| Supported platforms | Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Bitping](https://app.bitping.com).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Bitping** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `bitping/bitpingd`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `BITPING_EMAIL` | Email | Yes | No | Your Bitping account email |
| `BITPING_PASSWORD` | Password | Yes | Yes | Your Bitping account password |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-bitping \
  -v bitping-data:/root/.bitping \
  -e BITPING_EMAIL="<Email>" \
  -e BITPING_PASSWORD="<Password>" \
  bitping/bitpingd
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/bitping.yml`](../../services/bandwidth/bitping.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
