# Earn.fm

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earn.fm](https://earn.fm)

## Description

Earn.fm pays you for sharing your internet bandwidth. It authenticates via Supabase using email and password. Lightweight Docker image with straightforward deployment.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout | $3 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Relatively new platform. Earnings vary by location and bandwidth availability.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Earn.fm](https://earn.fm/ref/GEISYB91).

### 2. Get your credentials

After signing up, you'll use your account email and password for Docker deployment.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Earn.fm** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `earnfm/earnfm-client`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNFM_EMAIL` | Email | Yes | No | Your Earn.fm account email |
| `EARNFM_PASSWORD` | Password | Yes | Yes | Your Earn.fm account password (used for Supabase auth) |
