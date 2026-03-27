# ProxyRack

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://peer.proxyrack.com](https://peer.proxyrack.com)

## Description

ProxyRack's Peer program lets you earn by sharing your bandwidth as part of their proxy network. Each device requires a unique 64-character hex UUID and optionally an API key to auto-register the device. Works on both residential and VPS/datacenter connections. Dashboard is behind Cloudflare, which may require manual browser-based API key retrieval.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Crypto |

> Residential IPs earn more than datacenter. Dashboard behind Cloudflare may complicate automated access.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyRack](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyRack** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `proxyrack/pop`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UUID` | Device UUID | Yes | No | Unique 64-character hex ID per device. Generate with: cat /dev/urandom | tr -dc 'a-f0-9' | fold -w 64 | head -n 1 |
| `API_KEY` | API Key | No | Yes | Your ProxyRack API key (auto-registers device in dashboard if provided) |
| `DEVICE_NAME` | Device name | No | No | Friendly name for the device in dashboard (default: `Device-${UUID}`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-proxyrack \
  -e UUID="<Device UUID>" \
  -e API_KEY="<API Key>" \
  -e DEVICE_NAME="<Device name>" \
  proxyrack/pop
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/proxyrack.yml`](../../services/bandwidth/proxyrack.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
