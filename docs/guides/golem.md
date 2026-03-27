# Golem Network

> **Category:** GPU Compute | **Status:** Active
> **Website:** [https://golem.network](https://golem.network)

## Description

Golem Network is a decentralized compute marketplace where you share CPU and GPU resources in exchange for GLM tokens. Providers run the Yagna agent which manages workload execution in sandboxed environments. One of the oldest decentralized compute projects (founded 2016). Supports CPU tasks, GPU rendering, and general-purpose compute. Payments via Polygon L2.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $5 - $50 |
| Per | device |
| Minimum payout |  |
| Payout frequency | Per task completion |
| Payment methods | Crypto |

> Earnings depend on hardware, pricing, and task demand. CPU-only nodes earn less. GPU nodes earn more but require NVIDIA. Run the Yagna provider agent (not Docker image). Payments on Polygon in GLM tokens.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 10 Mbps |
| GPU required | No |
| Minimum storage | 20GB |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Golem Network](https://golem.network).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Golem Network** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** ``
- **Platforms:** linux/amd64

### Environment Variables

No environment variables required.

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/compute/golem.yml`](../../services/compute/golem.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
