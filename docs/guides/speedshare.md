# SpeedShare

> **Category:** Bandwidth Sharing | **Status:** Broken
> **Website:** [https://speedshare.app](https://speedshare.app)

## Description

SpeedShare lets you earn by sharing your unused internet bandwidth. Residential IPs only - datacenter and VPS connections are not accepted. There is no official Docker image; the community image (mrcolorrain) provides container support with a referral code and UUID-based authentication.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto, Paypal |

> Residential IPs only. No official Docker image - uses community build. API at api.speedshare.app is broken (returns Telegraf metrics instead of JSON). Service appears non-functional as of March 2025.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux, Docker |

## Setup Instructions

### 1. Create an account

Sign up at [SpeedShare](https://speedshare.app).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **SpeedShare** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `mrcolorrain/speedshare`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CODE` | Authorization Code | Yes | Yes | Your SpeedShare authorization code from the dashboard |
| `SPEEDSHARE_UUID` | Device UUID | No | No | Unique device identifier. Auto-generated if not provided. |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-speedshare \
  -e CODE="<Authorization Code>" \
  -e SPEEDSHARE_UUID="<Device UUID>" \
  mrcolorrain/speedshare
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | Percentage of referral earnings |
| New user bonus |  |
| How to get code | Dashboard > Referral > Copy your referral link |

---

*This guide was auto-generated from [`services/bandwidth/speedshare.yml`](../../services/bandwidth/speedshare.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
