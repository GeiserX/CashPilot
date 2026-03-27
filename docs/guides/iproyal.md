# IPRoyal Pawns

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://pawns.app](https://pawns.app)

## Description

IPRoyal Pawns lets you earn by sharing your unused bandwidth. IPRoyal is a well-established proxy provider, and Pawns is their residential bandwidth-sharing arm. The CLI Docker image accepts credentials via command-line flags. Offers a generous 10% lifetime referral commission and $3 bonus for new signups with code EARN3.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $5 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto, Bank |

> Earnings depend on location and bandwidth usage. US/EU residential IPs earn more.

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

Sign up at [IPRoyal Pawns](https://pawns.app?r=19266874).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **IPRoyal Pawns** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `iproyal/pawns-cli`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `IPROYAL_EMAIL` | Email | Yes | No | Your IPRoyal Pawns account email (passed as -email flag) |
| `IPROYAL_PASSWORD` | Password | Yes | Yes | Your IPRoyal Pawns account password (passed as -password flag) |
| `IPROYAL_DEVICE_NAME` | Device name | No | No | Name shown in your Pawns dashboard (passed as -device-name flag) (default: `cashpilot-{hostname}`) |
| `IPROYAL_DEVICE_ID` | Device ID | No | No | Unique device identifier (passed as -device-id flag) (default: `cashpilot-{hostname}`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-iproyal \
  -e IPROYAL_EMAIL="<Email>" \
  -e IPROYAL_PASSWORD="<Password>" \
  -e IPROYAL_DEVICE_NAME="<Device name>" \
  -e IPROYAL_DEVICE_ID="<Device ID>" \
  iproyal/pawns-cli -email ${IPROYAL_EMAIL} -password ${IPROYAL_PASSWORD} -device-name ${IPROYAL_DEVICE_NAME} -device-id ${IPROYAL_DEVICE_ID} -accept-tos
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/iproyal.yml`](../../services/bandwidth/iproyal.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
