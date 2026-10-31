# PacketStream

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://packetstream.io](https://packetstream.io)

## Description

PacketStream is a peer-to-peer bandwidth marketplace where you can sell your unused bandwidth. It powers a residential proxy network used for market research, SEO monitoring, and ad verification. Simple Docker setup with just a CID (Client ID) required. Note that CAPTCHA-protected login can make automated earnings collection challenging.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal |

> Pays $0.10/GB for bandwidth shared. Earnings depend heavily on demand for your IP's location.

## Cashing out

PayPal only, minimum $5, 3% fee shown before you confirm. The first withdrawal saves your PayPal email; changing it later needs an email confirmation and a 7-day wait, so check the address before you confirm. Requests are reviewed and sent within 7 days; you can cancel one while it waits, and a new one can only be made once it is paid.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Linux, Android |

## Setup Instructions

### 1. Create an account

Sign up at [PacketStream](https://packetstream.io/?psr=7xgZ).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

Log in at [packetstream.io/dashboard](https://packetstream.io/dashboard), click **Setup** in the sidebar, and copy your CID from the Docker command shown there.

### 3. Deploy with CashPilot

In the CashPilot web UI, open **Catalog** and click **Add** on the **PacketStream** row, or click **+ Add service** in the top bar and pick it there. Paste your CID into **Client ID**, then click **Deploy PacketStream**.

## Docker Configuration

- **Image:** `packetstream/psclient`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7, linux/arm/v6

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CID` | Client ID | Yes | No | Your PacketStream Client ID (found in Dashboard > Setup) |
