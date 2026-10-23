# Repocket

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://repocket.com](https://repocket.com)

## Description

Repocket lets you earn passive income by sharing your unused internet bandwidth. Residential IPs earn the most; VPS/datacenter IPs are accepted at lower rates. Max 5 devices and 5 active sessions per account. The Docker container authenticates with your account email and an API key from the Repocket dashboard (not your password).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $20 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Residential IPs earn more. VPS/datacenter IPs accepted but at lower rates.

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

Sign up at [Repocket](https://link.repocket.com/b1zM).

<small>Referral link: the CashPilot maintainer may earn a commission, at no cost to you. To sign up without it, go to [repocket.com](https://repocket.com).</small>

### 2. Get your API key

Log in at [app.repocket.com](https://app.repocket.com/bandwidth-earnings) and copy the **API key** shown on the bandwidth-earnings page. This API key — not your account password — is what the Docker container uses to authenticate.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Repocket** in the service catalog and click **Deploy**. Enter your account email and the API key. The key is a UUID (eight hex characters, then three groups of four, then twelve, separated by hyphens), and CashPilot refuses anything else before it contacts the worker, so a password pasted in by mistake never reaches the container. The earnings collector under **Settings**, **Collectors** is a separate login with your account email and password; it does not configure the container.

### Recover a container that keeps restarting

A Repocket container started with a password, or any other wrong value, in `RP_API_KEY` logs a 403 `Access denined.` error (that spelling is Repocket's), exits, and Docker restarts it. Changing the CashPilot image or restarting the container does not touch its environment, so the only way out is a new container:

1. Open Repocket on the dashboard and click **Remove**. Nothing is lost: Repocket keeps your balance and devices on its side.
2. Deploy Repocket again and enter the API key from the [bandwidth-earnings page](https://app.repocket.com/bandwidth-earnings). CashPilot now rejects the old recorded value, so a redeploy cannot bring it back.
3. Check the container's logs and restart count after a minute to confirm it connects.

## Docker Configuration

- **Image:** `repocket/repocket`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `RP_EMAIL` | Email | Yes | No | Your Repocket account email |
| `RP_API_KEY` | API Key | Yes | Yes | Your Repocket API key from the dashboard's bandwidth-earnings page (not your account password) |
