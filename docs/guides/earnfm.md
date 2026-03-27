# Earn.fm

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earn.fm](https://earn.fm)

## Description

Earn.fm pays you for sharing your internet bandwidth. It uses a simple token-based authentication via the EARNFM_TOKEN environment variable. The platform provides an API key from user settings that serves as the token. Lightweight Docker image with straightforward deployment.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $3 |
| Per | device |
| Minimum payout | $3 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Relatively new platform. Earnings vary by location and bandwidth availability.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Earn.fm](https://earn.fm/ref/GEISYB91).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Earn.fm** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `earnfm/earnfm-client`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNFM_TOKEN` | API Token | Yes | Yes | Your Earn.fm API key (found in app.earn.fm > Settings) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-earnfm \
  -e EARNFM_TOKEN="<API Token>" \
  earnfm/earnfm-client
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/earnfm.yml`](../../services/bandwidth/earnfm.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
