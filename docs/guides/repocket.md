# Repocket

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://repocket.com](https://repocket.com)

## Description

Repocket lets you earn passive income by sharing your unused internet bandwidth. Residential IPs earn the most; VPS/datacenter IPs are accepted at lower rates. Max 5 devices and 5 active sessions per account. The Docker container authenticates with your account email and an API key from the Repocket dashboard (not your password).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $20 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Residential IPs earn more. VPS/datacenter IPs accepted but at lower rates.

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

Sign up at [Repocket](https://repocket.com/).

### 2. Get your API key

Log in at [app.repocket.com](https://app.repocket.com/bandwidth-earnings) and copy the **API key** shown on the bandwidth-earnings page. This API key — not your account password — is what the Docker container uses to authenticate.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Repocket** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `repocket/repocket`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `RP_EMAIL` | Email | Yes | No | Your Repocket account email |
| `RP_API_KEY` | API Key | Yes | Yes | Your Repocket API key from the dashboard's bandwidth-earnings page (not your account password) |
