# Peer2Profit

> [!CAUTION]
> **Deprecated:** Peer2Profit is completely dead: the domain is unreachable and all services are offline. Deployment is blocked. This guide is kept for reference only.

> **Category:** Bandwidth Sharing | **Status:** Dead
>
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

### 2. Deploy with CashPilot

You can't. CashPilot hides dead services from the catalog and the setup wizard, and refuses a deploy request for one.

## Docker Configuration

- **Image:** `peer2profit/peer2profit-linux`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `P2P_EMAIL` | Email | Yes | No | Your Peer2Profit account email |
