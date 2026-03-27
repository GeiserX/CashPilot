# Storj

> **Category:** Storage Sharing | **Status:** Active
> **Website:** [https://www.storj.io](https://www.storj.io)

## Description

Storj is a decentralized cloud storage network where you earn by renting out your unused disk space. Run the storage node via Docker and get paid approximately $1.50/TB stored per month plus $2/TB egress. Payments are in STORJ token or via zkSync L2. Requires at least 550GB of available disk space and a stable internet connection. One of the most mature and truly passive storage income services.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $2 - $15 |
| Per | TB |
| Minimum payout | $4 |
| Payout frequency | Monthly |
| Payment methods | Crypto |

> ~$1.50/TB stored + $2/TB egress + $2.74/TB audit/repair. Earnings scale with disk allocated and node age. First 9 months have held-back escrow. Port 28967 must be forwarded.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 5 Mbps upload |
| GPU required | No |
| Minimum storage | 550GB |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Storj](https://www.storj.io/node).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Storj** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `storj/storagenode`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `WALLET` | Wallet address | Yes | No | ERC-20 wallet address for STORJ token payouts (or zkSync) |
| `EMAIL` | Email | Yes | No | Email address for operator notifications |
| `ADDRESS` | External address | Yes | No | External IP or DDNS hostname with port (e.g. mynode.ddns.net:28967) |
| `STORAGE` | Storage allocation | Yes | No | Maximum disk space to allocate (e.g. 2TB) (default: `1TB`) |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-storj \
  -p 28967:28967/tcp \
  -p 14002:14002 \
  -v /path/to/identity:/app/identity \
  -v /path/to/storage:/app/config \
  -e WALLET="<Wallet address>" \
  -e EMAIL="<Email>" \
  -e ADDRESS="<External address>" \
  -e STORAGE="<Storage allocation>" \
  storj/storagenode
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/storage/storj.yml`](../../services/storage/storj.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
