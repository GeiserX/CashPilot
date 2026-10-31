# Earn.fm

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://earn.fm](https://earn.fm)

## Description

Earn.fm pays you for sharing your internet bandwidth. Authenticates via a UUID API key from the dashboard. Lightweight Docker image with straightforward deployment.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout | $15 |
| Payout frequency | On request |
| Payment methods | Crypto, Paypal, Giftcard, Bank |

> Relatively new platform. Earnings vary by location and bandwidth availability.

## Cashing out

Minimum $15. Methods: USDT on BEP20 or Polygon ($1 fee) or TRC20 ($3 fee), PayPal, Amazon or Starbucks gift cards from $15, or a bank wire from $1,000 with transfer fees deducted. Before the first payout you fill in a billing profile (legal name and address), used for the payout receipts.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Devices per IP | 1 |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Earn.fm](https://earn.fm/ref/GEISYB91).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your API key

After signing up, go to [app.earn.fm](https://app.earn.fm) > Account Settings and copy your UUID API key.

### 3. Deploy with CashPilot

In the CashPilot web UI, open **Catalog** and click **Add** on the **Earn.fm** row, or click **+ Add service** in the top bar and pick it there. Paste your API key and click **Deploy Earn.fm**.

The API key only runs the client. To see your balance on the CashPilot dashboard, add your Earn.fm email and password under **Settings → Earnings collection**.

## Docker Configuration

- **Image:** `earnfm/earnfm-client`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNFM_TOKEN` | API Key | Yes | Yes | UUID API key from app.earn.fm > Account Settings |
