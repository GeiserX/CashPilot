# PacketShare

> **Category:** Bandwidth Sharing | **Status:** Dead
> **Website:** [https://www.packetshare.io](https://www.packetshare.io)

## Description

PacketShare lets you earn passive income by sharing your unused internet bandwidth. The official Docker image supports headless deployment with email/password authentication via command-line flags. Each container should have a different public IP address. Works on residential and some datacenter connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> One device per public IP. Residential IPs only. Earnings depend on location and bandwidth usage.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [PacketShare](https://www.packetshare.io/register.html).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **PacketShare** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `packetshare/packetshare`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `PACKETSHARE_EMAIL` | Email | Yes | No | Your PacketShare account email |
| `PACKETSHARE_PASSWORD` | Password | Yes | Yes | Your PacketShare account password |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-packetshare \
  -e PACKETSHARE_EMAIL="<Email>" \
  -e PACKETSHARE_PASSWORD="<Password>" \
  packetshare/packetshare -accept-tos -email=${PACKETSHARE_EMAIL} -password=${PACKETSHARE_PASSWORD}
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/packetshare.yml`](../../services/bandwidth/packetshare.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
