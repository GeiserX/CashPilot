# Peer2Profit

> **Category:** Bandwidth Sharing | **Status:** Dead
> **Website:** [https://peer2profit.com](https://peer2profit.com)

## Description

Peer2Profit monetizes unused internet bandwidth by routing legitimate traffic through your connection. Works on both residential and datacenter IPs, which is a differentiator from most bandwidth services. Registration via Telegram bot or website. Payouts via PayPal or crypto (MATIC).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $2 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Works on residential AND datacenter/VPS IPs. Mixed reviews - has had downtime scares. Payouts via PayPal or MATIC.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android |

## Setup Instructions

### 1. Create an account

Sign up at [Peer2Profit](https://peer2profit.com).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Peer2Profit** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `peer2profit/peer2profit-linux`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `P2P_EMAIL` | Email | Yes | No | Your Peer2Profit account email |
