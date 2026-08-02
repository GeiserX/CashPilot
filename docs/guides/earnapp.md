# EarnApp

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earnapp.com](https://earnapp.com)

!!! danger "EarnApp prohibits the way CashPilot runs it — read this first"

    EarnApp's help centre states: **"Installing EarnApp on Virtual Machines
    (VMs), Docker containers, or hosting services is strictly prohibited."** It
    names **personal or home servers** and **"any device used for business or
    monetization purposes"** as prohibited environments, and says the penalty is
    that your **account is terminated without prior notice** and any **pending
    payments are cancelled**.

    CashPilot deploys every service as a Docker container, usually on a home
    server. **Deploying EarnApp through CashPilot means knowingly accepting that
    risk.** This guide is kept so the decision is an informed one, not so the
    risk is hidden behind a signup link.

    EarnApp does support ordinary desktops, laptops, phones and Raspberry Pi via
    its own installer. If you want to earn with it, that is the route that does
    not put your account and balance at risk — and CashPilot cannot manage it.

## Description

EarnApp by Bright Data lets you sell your unused bandwidth for passive income. Bright Data is the world's largest proxy network, powering data collection for Fortune 500 companies.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $2.50 |
| Payout frequency | On request (auto-redeem available: PayPal $10 min, Wise $10 min, Amazon $50 min) |
| Payment methods | Paypal, Amazon Giftcard, Wise |

> Highly location-dependent. US/EU IPs earn the most. Earnings scale with bandwidth consumed.

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

Sign up at [EarnApp](https://earnapp.com/i/TSMD9wSm).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **EarnApp** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `fazalfarhan01/earnapp:lite`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNAPP_UUID` | Node UUID | Yes | No | Your EarnApp node ID (run 'earnapp showid' to get it, or generate one with the sdk-node-id format) |
| `EARNAPP_TERM` | Accept Terms | No | No | Set to 'yes' to accept terms of service (default: `yes`) |
