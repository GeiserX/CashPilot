# WizardGain

> [!CAUTION]
> **Dead:** the site went into indefinite maintenance in March 2026 and the domain has had no name servers since at least August 2026. Deployment is blocked. This guide is kept for reference only.

> **Category:** Bandwidth Sharing | **Status:** Dead
>
> **Website:** [https://wizardgain.com](https://wizardgain.com)

## Description

WizardGain turns your unused internet bandwidth into a recurring revenue stream. Uses email-based authentication. Pays in cryptocurrency. Official Docker image available as wizardgain/worker.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Crypto payouts. Earnings depend on location and bandwidth demand.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [WizardGain](https://wizardgain.com).

### 2. Deploy with CashPilot

You can't. CashPilot hides dead services from the catalog and the setup wizard, and refuses a deploy request for one.

## Docker Configuration

- **Image:** `wizardgain/worker`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EMAIL` | Email | Yes | No | Your WizardGain account email |
