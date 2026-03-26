# Adnade

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://adnade.com](https://adnade.com)

## Description

Adnade is an ad-based passive income service. You earn by running an automated browser that views advertisements. Requires a headless browser container (Firefox) with a specific surfbar URL. Uses more resources than traditional bandwidth apps due to the browser requirement.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0.5 - $2 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Ad-view based. Uses significant CPU/memory for browser. May need periodic restart.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Linux, Docker |

## Setup Instructions

### 1. Create an account

Sign up at [Adnade](https://adnade.com).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Adnade** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `jlesage/firefox`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `ADNADE_USERNAME` | Username | Yes | No | Your Adnade username for the view URL |
| `VNC_PASSWORD` | VNC Password | No | Yes | Password for VNC access to the browser (default: `cashpilot`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-adnade \
  -p 5900:5900 \
  -v adnade-data:/config \
  -e ADNADE_USERNAME="<Username>" \
  -e VNC_PASSWORD="<VNC Password>" \
  jlesage/firefox
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus |  |
| New user bonus |  |
| How to get code | Check the dashboard for referral options |

---

*This guide was auto-generated from [`services/bandwidth/adnade.yml`](../../services/bandwidth/adnade.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
