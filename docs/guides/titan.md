# Titan Network

> **Category:** DePIN | **Status:** Active
> **Website:** [https://titannet.io](https://titannet.io)

## Description

Titan Network is a DePIN platform that shares your IP address, storage, and bandwidth in exchange for TNT token rewards. Available on Windows, Mac, and Android. Nodes contribute to a decentralized CDN and storage layer. Typical earnings range from $5-30/month depending on resources shared and geographic location.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $30 (estimate) |
| Per | device |
| Minimum payout |  |
| Payout frequency | Epoch-based |
| Payment methods | Crypto |

> Shares IP, storage, and bandwidth. Earnings depend on resources contributed and region. Higher storage allocation yields higher rewards.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | 50GB |
| Supported platforms | Windows, Macos, Android |

## Setup Instructions

### 1. Create an account

Sign up at [Titan Network](https://edge.titannet.info/signup?inviteCode=2GKKJ495).

### 2. Get a Device ID

Log into the Titan Edge dashboard to obtain a Device ID for your node. **Note**: As of March 2026, the WebUI cannot generate device IDs and the Android app buttons are non-functional. You may need to wait for Titan to fix these issues.

### 3. Deploy

No official Docker image exists. Titan provides native binaries for Windows, macOS, and Android. Unofficial Docker images exist but are not endorsed.

## Docker Configuration

- **Image:** (no official Docker image)

### Environment Variables

No environment variables required.

## Known Issues (March 2026)

- **Android app broken**: App installs but buttons/controls are non-functional. Cannot start earning.
- **WebUI device ID generation broken**: The web dashboard cannot generate new device IDs needed for node setup.
- **No official Docker image**: Only native desktop/mobile apps are officially supported.
- **Status**: Wait for Titan team to fix the app and dashboard before attempting setup.
