# IPRoyal Pawns

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://pawns.app](https://pawns.app)

## Description

IPRoyal Pawns lets you earn by sharing your unused bandwidth. IPRoyal is a well-established proxy provider, and Pawns is their residential bandwidth-sharing arm. The CLI Docker image accepts credentials via command-line flags. Offers a generous 10% lifetime referral commission and $3 bonus for new signups with code EARN3.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto, Giftcard |

> Earnings depend on location and bandwidth usage. US/EU residential IPs earn more.

## Cashing out

Minimum $5. Select your country first; the methods depend on it. From Spain (October 2026): PayPal 4% with a $0.25 minimum fee, paid through Tremendous, which emails a link where you enter your name and PayPal address; USDT (BEP20, ERC20, TRC20) or USDC (BEP20, ERC20) with a $1 network fee; Bitcoin with a $2 minimum fee; gift cards with no fee. The first payout needs a one-time SMS check of your phone number: Withdraw opens it, and the number goes in with its country code. Every payout then asks for a code sent to your account email and is reviewed for up to 72 hours before it is sent.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android, Ios |

## Setup Instructions

### 1. Create an account

Sign up at [IPRoyal Pawns](https://pawns.app?r=19266874).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **IPRoyal Pawns** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `iproyal/pawns-cli`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7, linux/arm/v6

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `IPROYALPAWNS_EMAIL` | Email | Yes | No | Your IPRoyal Pawns account email (passed as -email flag) |
| `IPROYALPAWNS_PASSWORD` | Password | Yes | Yes | Your IPRoyal Pawns account password (passed as -password flag) |
| `IPROYALPAWNS_DEVICE_NAME` | Device name | No | No | Name shown in your Pawns dashboard (passed as -device-name flag) (default: `cashpilot-{hostname}`) |
| `IPROYALPAWNS_DEVICE_ID` | Device ID | No | No | Unique device identifier (passed as -device-id flag) (default: `cashpilot-{hostname}`) |
