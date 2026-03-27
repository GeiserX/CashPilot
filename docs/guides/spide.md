# Spide

> **Category:** Bandwidth Sharing | **Status:** Dead
> **Website:** [https://spide.io](https://spide.io)

## Description

Spide is a bandwidth-sharing service that lets you monetize unused internet bandwidth. Uses an optional machine ID for device tracking. Available through community Docker images from the income-generator project.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $3 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Limited information available. Earnings depend on location.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Spide](https://spide.io).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Spide** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** ``

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `SPIDE_MACHINE_ID` | Machine ID | No | No | Machine ID for existing device already registered (auto-generated if empty) |

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/spide.yml`](../../services/bandwidth/spide.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
