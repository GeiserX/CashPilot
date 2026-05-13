# Repocket

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://repocket.com](https://repocket.com)

## Description

Repocket lets you earn passive income by sharing your unused internet bandwidth. Residential IPs earn the most; VPS/datacenter IPs are accepted at lower rates. Max 5 devices and 5 active sessions per account. Authenticates via Firebase using email and password. The Docker image uses environment variables directly.

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

### 2. Get your credentials

After signing up, you'll use your account email and password for Docker deployment.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Repocket** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `repocket/repocket`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `REPOCKET_EMAIL` | Email | Yes | No | Your Repocket account email |
| `REPOCKET_PASSWORD` | Password | Yes | Yes | Your Repocket account password (used for Firebase auth) |
