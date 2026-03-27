# Presearch

> **Category:** DePIN | **Status:** Active
> **Website:** [https://presearch.com](https://presearch.com)

## Description

Presearch is a decentralized search engine where node operators run Docker containers to process search queries and earn PRE tokens. Requires staking a minimum of 4,000 PRE tokens to earn rewards. Prioritizes fast internet and low latency nodes.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $5 - $30 |
| Per | node |
| Minimum payout |  |
| Payout frequency | Daily |
| Payment methods | Crypto |

> Requires 4,000 PRE stake (~$100-200). Earnings depend on search query volume routed to your node. Fast internet and low latency prioritized.

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

Sign up at [Presearch](https://presearch.com/signup?rid=4872322).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Presearch** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `presearch/node`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `PRESEARCH_REGISTRATION_CODE` | Registration Code | Yes | Yes | Your Presearch node registration code from the dashboard |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-presearch \
  -v {'container_path': '/app/node', 'description': 'Node data and keys'} \
  -e PRESEARCH_REGISTRATION_CODE="<Registration Code>" \
  presearch/node
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/depin/presearch.yml`](../../services/depin/presearch.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
