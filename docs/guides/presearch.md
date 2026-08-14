# Presearch

> **Category:** DePIN | **Status:** Dead
> **Website:** [https://presearch.com](https://presearch.com)

> **Presearch shut down permanently in July 2026.** The company announced the closure on July 24, 2026 (effective July 28, 2026): the search platform and the node program are gone, backend infrastructure was decommissioned, and node operators were told to unstake and withdraw their PRE before the deadline. The `presearch/node` Docker image received its last update on July 21, 2026 and running it earns nothing. This page is kept for reference only — do not deploy.

## Description

Presearch was a decentralized search engine where node operators ran Docker containers to process search queries and earned PRE tokens. It required staking a minimum of 4,000 PRE tokens to earn rewards.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $30 (estimate) |
| Per | node |
| Minimum payout |  |
| Payout frequency | Daily |
| Payment methods | Crypto |

> Requires 4,000 PRE stake (~$100-200). Earnings depend on search query volume routed to your node. Fast internet and low latency prioritized.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Presearch](https://presearch.com/signup?rid=4872322).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Presearch** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `presearch/node`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `REGISTRATION_CODE` | Registration Code | Yes | Yes | Your Presearch node registration code from the dashboard |
