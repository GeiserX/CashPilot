# AntGain

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://antgain.app](https://antgain.app)

## Description

AntGain is a bandwidth-sharing service that supports unlimited devices per account. Uses API key-based authentication obtained from the dashboard profile tab. Community Docker image available. Pays in cryptocurrency.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $5 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Unlimited devices per account. Crypto payouts.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Linux, Docker |

## Setup Instructions

### 1. Create an account

Sign up at [AntGain](https://antgain.app).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **AntGain** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `pinors/antgain-cli`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `ANTGAIN_API_KEY` | API Key | Yes | Yes | Your AntGain API key (Dashboard > Profile tab) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-antgain \
  -v antgain-data:/data \
  -e ANTGAIN_API_KEY="<API Key>" \
  pinors/antgain-cli
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus |  |
| New user bonus |  |
| How to get code | Check the dashboard for referral options |

---

*This guide was auto-generated from [`services/bandwidth/antgain.yml`](../../services/bandwidth/antgain.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
