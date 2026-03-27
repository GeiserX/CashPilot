# PacketStream

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://packetstream.io](https://packetstream.io)

## Description

PacketStream is a peer-to-peer bandwidth marketplace where you can sell your unused bandwidth. It powers a residential proxy network used for market research, SEO monitoring, and ad verification. Simple Docker setup with just a CID (Client ID) required. Note that CAPTCHA-protected login can make automated earnings collection challenging.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal |

> Pays $0.10/GB for bandwidth shared. Earnings depend heavily on demand for your IP's location.

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

Sign up at [PacketStream](https://packetstream.io/?psr=7xgZ).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **PacketStream** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `packetstream/psclient`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CID` | Client ID | Yes | No | Your PacketStream Client ID (found in Dashboard > Setup) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-packetstream \
  -e CID="<Client ID>" \
  packetstream/psclient
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/packetstream.yml`](../../services/bandwidth/packetstream.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
