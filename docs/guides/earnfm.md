# Earn.fm

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earn.fm](https://earn.fm)

## Description

Earn.fm pays you for sharing your internet bandwidth. Authenticates via a UUID API key from the dashboard. Lightweight Docker image with straightforward deployment.

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

### 2. Get your API key

After signing up, go to [app.earn.fm](https://app.earn.fm) > Account Settings and copy your UUID API key.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Earn.fm** in the service catalog and click **Deploy**. Enter your API token and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `earnfm/earnfm-client`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNFM_TOKEN` | API Key | Yes | Yes | UUID API key from app.earn.fm > Account Settings |
