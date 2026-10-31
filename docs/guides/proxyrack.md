# ProxyRack

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://peer.proxyrack.com](https://peer.proxyrack.com)

## Description

ProxyRack's Peer program lets you earn by sharing your bandwidth as part of their proxy network. Each device requires a unique 64-character hex UUID and optionally an API key to auto-register the device. Works on both residential and VPS/datacenter connections. Dashboard is behind Cloudflare, which may require manual browser-based API key retrieval.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $20 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Residential IPs earn more than datacenter. Dashboard behind Cloudflare may complicate automated access.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Devices per account | 500 |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyRack](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

Each device needs its own 64-character hex UUID. Make one with:

```sh
cat /dev/urandom | tr -dc 'a-f0-9' | fold -w 64 | head -n 1
```

The API key is optional: it is shown on the main page of [peer.proxyrack.com](https://peer.proxyrack.com), and with it the container registers itself on your account.

### 3. Deploy with CashPilot

In the CashPilot web UI, open **Catalog** and click **Add** on the **ProxyRack** row, or click **+ Add service** in the top bar and pick it there. Paste a new UUID into **Device UUID**, add your API key if you have one, then click **Deploy ProxyRack**.

### 4. Link the device to your account

Until the device is on your account it earns for nobody. Sign in to [peer.proxyrack.com](https://peer.proxyrack.com), open **Devices**, choose **Add device** and paste the UUID. If you entered an API key, the container registers itself. Check that the device is listed there anyway.

## Docker Configuration

- **Image:** `proxyrack/pop`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UUID` | Device UUID | Yes | No | Unique 64-character hex ID per device. Generate with: cat /dev/urandom | tr -dc 'a-f0-9' | fold -w 64 | head -n 1 |
| `API_KEY` | API Key | No | Yes | Your ProxyRack API key (auto-registers device in dashboard if provided) |
| `DEVICE_NAME` | Device name | No | No | Friendly name for the device in dashboard (default: `Device-${UUID}`) |
