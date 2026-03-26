# Ebesucher

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://www.ebesucher.com](https://www.ebesucher.com)

## Description

Ebesucher is a traffic exchange platform where you earn credits by visiting websites through an automated surfbar. Runs in a headless browser container (Firefox or Chromium). Not a traditional bandwidth-sharing service — it generates traffic by browsing websites automatically. Requires a browser container which uses more resources than typical bandwidth apps.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | 0.5 - 2 EUR |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Paypal |

> Earnings in BTP points convertible to EUR. Uses significant CPU/memory for browser. Needs periodic restart.

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

Sign up at [Ebesucher](https://www.ebesucher.com).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Ebesucher** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `jlesage/firefox`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EBESUCHER_USERNAME` | Username | Yes | No | Your Ebesucher username for the surfbar URL |
| `VNC_PASSWORD` | VNC Password | No | Yes | Password for VNC access to the browser (default: `cashpilot`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-ebesucher \
  -p 5800:5800 \
  -v ebesucher-data:/config \
  -e EBESUCHER_USERNAME="<Username>" \
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

*This guide was auto-generated from [`services/bandwidth/ebesucher.yml`](../../services/bandwidth/ebesucher.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
