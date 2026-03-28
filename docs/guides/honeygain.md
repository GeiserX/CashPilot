# Honeygain

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://www.honeygain.com](https://www.honeygain.com)

## Description

Share your unused internet bandwidth and earn passive income. Honeygain routes web intelligence, content delivery, and market research traffic through your connection. One of the most established bandwidth-sharing platforms with 12M+ users and over 1M payouts completed.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $20 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Varies by location. US/EU IPs earn more. Max 10 devices per account.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android |

## Setup Instructions

### 1. Create an account

Sign up at [Honeygain](https://dashboard.honeygain.com/ref/SERGIB4014).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Honeygain** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `honeygain/honeygain`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `HONEYGAIN_EMAIL` | Email | Yes | No | Your Honeygain account email |
| `HONEYGAIN_PASSWORD` | Password | Yes | Yes | Your Honeygain account password |
| `HONEYGAIN_DEVICE_NAME` | Device name | No | No | Name shown in your Honeygain dashboard (default: `cashpilot-{hostname}`) |
