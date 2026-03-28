# Anyone Protocol

> **Category:** DePIN | **Status:** Active
> **Website:** [https://anyone.io](https://anyone.io)

## Description

Anyone Protocol (formerly ATOR) is a decentralized onion-routing privacy network. Node operators run relay nodes and earn ANYONE tokens for bandwidth contributed. Think "incentivized Tor." Official Docker images available for amd64 and arm64 including Raspberry Pi. Configuration is file-based via an anonrc file mounted into the container (Nickname, ContactInfo, ORPort, etc.).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $5 - $50 |
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

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-anyone-protocol \
  -p 9001:9001 \
  -v anon-data:/var/lib/anon \
  -v anon-config:/etc/anon \
  ghcr.io/anyone-protocol/ator-protocol
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/depin/anyone-protocol.yml`](../../services/depin/anyone-protocol.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
