# EarnApp

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earnapp.com](https://earnapp.com)

## Description

EarnApp by Bright Data lets you sell your unused bandwidth for passive income. Bright Data is the world's largest proxy network, powering data collection for Fortune 500 companies. The community Docker image (fazalfarhan01) makes headless deployment easy with a lite mode that requires only a UUID.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $2 - $5 |
| Per | device |
| Minimum payout | $2.50 |
| Payout frequency | On request (auto-redeem available: PayPal $10 min, Wise $10 min, Amazon $50 min) |
| Payment methods | Paypal, Amazon Giftcard, Wise |

> Highly location-dependent. US/EU IPs earn the most. Earnings scale with bandwidth consumed.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux, Android |

## Setup Instructions

### 1. Create an account

Sign up at [EarnApp](https://earnapp.com/i/TSMD9wSm).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **EarnApp** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `fazalfarhan01/earnapp:lite`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNAPP_UUID` | Node UUID | Yes | No | Your EarnApp node ID (run 'earnapp showid' to get it, or generate one with the sdk-node-id format) |
| `EARNAPP_TERM` | Accept Terms | No | No | Set to 'yes' to accept terms of service (default: `yes`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-earnapp \
  -v earnapp-data:/etc/earnapp \
  -e EARNAPP_UUID="<Node UUID>" \
  -e EARNAPP_TERM="<Accept Terms>" \
  fazalfarhan01/earnapp:lite
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/earnapp.yml`](../../services/bandwidth/earnapp.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
