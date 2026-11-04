# Traffmonetizer

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://traffmonetizer.io](https://traffmonetizer.io)

## Description

Traffmonetizer lets you monetize your internet traffic by sharing bandwidth with verified businesses. One of the few bandwidth-sharing services that works well on VPS and datacenter IPs in addition to residential connections. Uses a simple token-based authentication passed via command-line arguments. Supports ARM architectures for Raspberry Pi and similar devices.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $10 |
| Payout frequency | On request |
| Payment methods | Crypto, Bank |

> VPS and datacenter IPs earn less than residential. US/EU locations earn more. The more **unique public IPs** your devices have, the more you earn.

> **Same IP = shared traffic.** Multiple devices on the same public IP are allowed (no ban risk), but traffic is split between them, so you don't earn more total. Running on both a phone and server on the same WiFi is pointless. The phone only adds value on cellular data (different IP). Also available on iOS.

## Cashing out

Minimum $10. PayPal is no longer offered. Save one payout method in the profile first: USDT on Solana or TON (lowest fees), Arbitrum (low fees) or Tron TRC20 (high network fees), or a bank transfer from $1,000. The first address you save applies at once; changing it later needs an email confirmation. The dashboard may ask for a messenger contact (WhatsApp, Telegram or Skype) before the first withdrawal. A request pays whole dollars and the cents stay in the balance.

## Domain move to traffmonetizer.io (November 2026)

On 2 November 2026 traffmonetizer.com stopped resolving: the registrar put the domain on hold. Traffmonetizer moved the website, the dashboard and the API to traffmonetizer.io, announced it by email on 3 November, and published a new `traffmonetizer/cli_v2` image the same day. Containers on the older image keep logging `Status: [any ip] - disconnected` and earn nothing.

If you ran Traffmonetizer before the move:

1. **Redeploy the container on every worker.** Open the Traffmonetizer row in CashPilot and deploy again without changing anything. The deploy pulls the new image and keeps your token and device name. `docker logs cashpilot-traffmonetizer` should then show `connected`. Your current token keeps working for the container.
2. **Replace the earnings-collector token if it is rejected.** The token we had copied from app.traffmonetizer.com got `401 Unauthorized` from the new API, and a fresh one from the new dashboard worked at once. If CashPilot reports your Traffmonetizer token as rejected, log in at [app.traffmonetizer.io](https://app.traffmonetizer.io), copy `authToken` as in step 2 of the setup, and paste it under **Settings → Earnings collection**.

The account, balance and devices carried over unchanged. Your old referral links stop working with the old domain; `https://traffmonetizer.io/?aff=<your code>` works the same way.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Devices per IP | Unlimited |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Android |

## Setup Instructions

### 1. Create an account

Sign up at [Traffmonetizer](https://traffmonetizer.io/?aff=2111758).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

Log in at [app.traffmonetizer.io](https://app.traffmonetizer.io), press F12, open **Application → Local Storage → https://app.traffmonetizer.io** and copy the `authToken` value. CashPilot's earnings collector uses the same token, under **Settings → Earnings collection**.

### 3. Deploy with CashPilot

In the CashPilot web UI, open **Catalog** and click **Add** on the **Traffmonetizer** row, or click **+ Add service** in the top bar and pick it there. Paste your token, then click **Deploy Traffmonetizer**.

## Docker Configuration

- **Image:** `traffmonetizer/cli_v2`
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7. Docker Hub labels every tag of this image `linux/amd64`, including the real ARM builds, so Docker cannot pick them itself. CashPilot deploys `arm64v8` on a 64-bit ARM worker and `arm32v7` on a 32-bit one, going by the architecture the worker reports. Running it by hand on a Raspberry Pi, use the `arm64v8` (or `arm32v7`) tag explicitly.

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `TRAFFMONETIZER_TOKEN` | Token | Yes | Yes | The `authToken` value in your browser's Local Storage at app.traffmonetizer.io |
| `TRAFFMONETIZER_DEVICE_NAME` | Device name | No | No | Name displayed in dashboard for device management (default: `cashpilot-{hostname}`) |
