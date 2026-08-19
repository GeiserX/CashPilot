# URnetwork

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://ur.io](https://ur.io)

## Description

URnetwork is a decentralized VPN and bandwidth-sharing network. You earn by providing bandwidth as a community provider. The provider container authenticates itself with your account email and password (the binary's `auth-provide` subcommand), stores the session JWT in the `urnetwork-data` volume, and starts providing — no manual token extraction involved.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Works on VPS and residential. Crypto payouts. Supports proxy mode for multi-IP setups.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [URnetwork](https://ur.io/?referral_code=1Q3G19).

### 2. Get your credentials

The provider logs in with your normal URnetwork account: the email and password you use at [ur.io](https://ur.io). If you created the account with Google or Apple sign-in, set a password on it first — the headless provider has no browser to run an SSO flow in.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **URnetwork** in the service catalog and click **Deploy**. Enter your email and password; the provider authenticates on first start (`Jwt written to /root/.urnetwork/jwt` in its log), keeps the session in the `urnetwork-data` volume, and starts providing.

Your provider stats and earnings live at [app.ur.network/stats](https://app.ur.network/stats). Link a wallet in the URnetwork app — an unlinked wallet forfeits payouts after 30 days.

> **Deployed URnetwork before and it never earned anything?** CashPilot releases before this fix asked for a `UR_AUTH_TOKEN` variable that the provider binary has never read — the container simply ran unauthenticated (issue #344). Upgrade CashPilot, then **Deploy** URnetwork again from the catalog with your email and password.

## Docker Configuration

- **Image:** `bringyour/community-provider:g4-latest` (the release channel the [provider docs](https://docs.ur.io/provider) name as most stable)
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UR_USER_AUTH` | Email | Yes | No | Your URnetwork account email (ur.io login) |
| `UR_PASSWORD` | Password | Yes | Yes | Your URnetwork account password (no spaces); used by `auth-provide`, session persists in the volume |
