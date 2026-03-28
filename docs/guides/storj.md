# Storj

> **Category:** Storage Sharing | **Status:** Active
> **Website:** [https://www.storj.io](https://www.storj.io)

## Description

Storj is a decentralized cloud storage network where you earn by renting out your unused disk space. Run the storage node via Docker and get paid approximately $1.50/TB stored per month plus $2/TB egress. Payments are in STORJ token or via zkSync L2. Requires at least 550GB of available disk space and a stable internet connection. One of the most mature and truly passive storage income services.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $15 (estimate) |
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
| Supported platforms | Docker, Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Storj](https://www.storj.io/node). No referral program available.

### 2. Create a node identity

Before running a storage node, you must generate a cryptographic identity. This involves computing a proof-of-work to difficulty 36, which takes **several hours** of CPU time.

```bash
# Download the identity binary
curl -L https://github.com/storj/storj/releases/latest/download/identity_linux_amd64.zip -o identity.zip
unzip identity.zip

# Generate identity (CPU-intensive, takes hours)
nohup ./identity create storagenode --identity-dir /path/to/identity/ > /tmp/storj-identity.log 2>&1 &
```

The process outputs progress like `Generated 50000 keys; best difficulty so far: 34`. It's done when it reaches difficulty 36 and exits. Files created: `ca.cert`, `ca.key`, `identity.cert`, `identity.key`.

### 3. Authorize the identity

After identity creation, authorize it with an auth token from the Storj dashboard:

```bash
./identity authorize storagenode <auth-token> --identity-dir /path/to/identity/
```

Verify: `identity.cert` should have 3 certificate entries, `ca.cert` should have 2.

### 4. Port forwarding

Forward these ports through your router to the server running the node:
- **TCP 28967** — Storage node traffic (required)
- **TCP 14002** — Dashboard/monitoring (optional, local access only)

### 5. Deploy with CashPilot

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

### Important Notes

- **Escrow period**: First 9 months of operation have held-back escrow (75% of storage fees held, released gradually). This incentivizes long-term operation.
- **One node per IP**: Storj recommends one node per public IP for optimal satellite allocation.
- **Uptime matters**: Nodes with poor uptime get less data. Aim for 99.5%+ uptime.
- **Disk selection**: Always use spinning disks (HDD). The data stored is cold storage — IOPS don't matter, capacity does.
