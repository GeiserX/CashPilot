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

No account creation is needed. Anyone Protocol relays are permissionless -- you just run a node and earn ANYONE tokens based on uptime and bandwidth.

### 2. Configure anonrc

Anyone Protocol requires an `anonrc` configuration file. Create it before deploying:

```
User anond
DataDirectory /var/lib/anon
ControlSocket /run/anon/control
ControlSocketsGroupWritable 1
CookieAuthentication 1
CookieAuthFile /run/anon/control.authcookie
CookieAuthFileGroupReadable 1
Log notice file /etc/anon/notices.log
ORPort 9001
ExitRelay 0
Nickname YourRelayName
ContactInfo your@email.com
AgreeToTerms 1
```

**Important:** `AgreeToTerms 1` is required since version 0.4.9.7-live. Without it, the container exits immediately with "User has not agreed to the terms and conditions."

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Anyone Protocol** in the service catalog and click **Deploy**. CashPilot will handle the anonrc creation and volume setup.

## Docker Configuration

- **Image:** `ghcr.io/anyone-protocol/ator-protocol`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CONTACT_EMAIL` | Contact Email | No | No | Operator email (set in anonrc ContactInfo if not already present) |

### Required Configuration

The `anonrc` file must contain `AgreeToTerms 1` to accept the [Anyone Protocol Terms](https://www.anyone.io/terms). The entrypoint script only handles Nickname and ContactInfo -- the terms check is in the `anon` binary itself.
