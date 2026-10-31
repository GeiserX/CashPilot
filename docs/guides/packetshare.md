# PacketShare

> [!CAUTION]
> **Dead:** the catalog marks PacketShare as dead. Deployment is blocked. This guide is kept for reference only.

> **Category:** Bandwidth Sharing | **Status:** Dead
>
> **Website:** [https://www.packetshare.io](https://www.packetshare.io)

## Description

PacketShare lets you earn passive income by sharing your unused internet bandwidth. The official Docker image supports headless deployment with email/password authentication via command-line flags. Each container should have a different public IP address. Works on residential and some datacenter connections.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> One device per public IP. Residential IPs only. Earnings depend on location and bandwidth usage.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [PacketShare](https://www.packetshare.io/register.html).

### 2. Deploy with CashPilot

You can't. CashPilot hides dead services from the catalog and the setup wizard, and refuses a deploy request for one.

## Docker Configuration

- **Image:** `packetshare/packetshare`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `PACKETSHARE_EMAIL` | Email | Yes | No | Your PacketShare account email |
| `PACKETSHARE_PASSWORD` | Password | Yes | Yes | Your PacketShare account password |
