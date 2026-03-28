# Anyone Protocol

> **Category:** DePIN | **Status:** Active
> **Website:** [https://anyone.io](https://anyone.io)

## Description

Anyone Protocol (formerly ATOR) is a decentralized onion-routing privacy network. Node operators run relay nodes and earn ANYONE tokens for bandwidth contributed. Think "incentivized Tor." Official Docker images available for amd64 and arm64 including Raspberry Pi. Configuration is file-based via an anonrc file mounted into the container (Nickname, ContactInfo, ORPort, etc.).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $50 (estimate) |
| Per | relay |
| Minimum payout |  |
| Payout frequency | Epoch-based |
| Payment methods | Crypto |

> Earnings based on bandwidth contributed and uptime. Open source project with active development.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 10 Mbps |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Anyone Protocol](https://anyone.io).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Anyone Protocol** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `ghcr.io/anyone-protocol/ator-protocol`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

No environment variables required.
