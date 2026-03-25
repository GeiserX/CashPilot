# Repocket

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://repocket.com](https://repocket.com)

## Description

Repocket lets you earn passive income by sharing your unused internet bandwidth. It works on both residential and VPS/datacenter connections. Setup requires an email and API key from the dashboard. The Docker image uses environment variables directly (no command-line flags needed), making it straightforward to deploy.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $20 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Residential IPs earn more. VPS/datacenter IPs accepted but at lower rates.

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

Sign up at [Repocket](https://repocket.com/).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Repocket** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `repocket/repocket`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `RP_EMAIL` | Email | Yes | No | Your Repocket account email |
| `RP_API_KEY` | API Key | Yes | Yes | Your Repocket API key (found in Dashboard > API Key section) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-repocket \
  -e RP_EMAIL="<Email>" \
  -e RP_API_KEY="<API Key>" \
  repocket/repocket
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus |  |
| New user bonus |  |
| How to get code | No public referral program found as of March 2025 |

---

*This guide was auto-generated from [`services/bandwidth/repocket.yml`](../../services/bandwidth/repocket.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
