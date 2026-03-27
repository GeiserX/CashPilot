# Traffmonetizer

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://traffmonetizer.com](https://traffmonetizer.com)

## Description

Traffmonetizer lets you monetize your internet traffic by sharing bandwidth with verified businesses. One of the few bandwidth-sharing services that works well on VPS and datacenter IPs in addition to residential connections. Uses a simple token-based authentication passed via command-line arguments. Supports ARM architectures for Raspberry Pi and similar devices.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto, Paypal |

> VPS and datacenter IPs earn less than residential. US/EU locations earn more. Multiple IPs supported via Docker networks.

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

Sign up at [Traffmonetizer](https://traffmonetizer.com/?aff=2111758).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Traffmonetizer** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `traffmonetizer/cli_v2`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `TRAFFMONETIZER_TOKEN` | Token | Yes | Yes | Your Traffmonetizer account token (found in Dashboard > Docker run command) |
| `TRAFFMONETIZER_DEVICE_NAME` | Device name | No | No | Name displayed in dashboard for device management (default: `cashpilot-{hostname}`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-traffmonetizer \
  -e TRAFFMONETIZER_TOKEN="<Token>" \
  -e TRAFFMONETIZER_DEVICE_NAME="<Device name>" \
  traffmonetizer/cli_v2 start accept --token ${TRAFFMONETIZER_TOKEN} --device-name ${TRAFFMONETIZER_DEVICE_NAME}
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/traffmonetizer.yml`](../../services/bandwidth/traffmonetizer.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
