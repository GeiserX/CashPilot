# Nosana

> **Category:** GPU Compute | **Status:** Active
> **Website:** [https://nosana.io](https://nosana.io)

## Description

Nosana is a decentralized GPU compute marketplace built on Solana. It connects GPU owners with AI workload demand, paying in NOS tokens. An RTX 3060 earns approximately $0.048/hr. The platform focuses on AI inference workloads and uses the Solana blockchain for job scheduling and payment settlement. Nodes run containerized workloads via the Nosana CLI.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $20 - $100 |
| Per | GPU-hour |
| Minimum payout |  |
| Payout frequency | Per job completion |
| Payment methods | Crypto |

> RTX 3060 ~$0.048/hr, higher-end GPUs earn more. Earnings depend on job availability and GPU model. Requires NVIDIA GPU, Linux, Docker, and Nosana CLI. Payments in NOS token on Solana.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 50 Mbps |
| GPU required | Yes |
| Minimum storage | 50GB |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Nosana](https://nosana.io).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Nosana** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

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

*This guide was auto-generated from [`services/compute/nosana.yml`](../../services/compute/nosana.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
