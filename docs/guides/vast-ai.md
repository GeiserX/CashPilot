# Vast.ai

> **Category:** GPU Compute | **Status:** Active
> **Website:** [https://vast.ai](https://vast.ai)

## Description

Vast.ai is a GPU cloud marketplace where you rent out your NVIDIA GPU to AI/ML researchers and developers. Docker-native platform where you set your own hourly prices. An RTX 3090 typically earns $0.20-0.40/hr when rented. Requires an NVIDIA GPU with recent drivers and a stable internet connection. Revenue depends heavily on GPU model, pricing strategy, and market demand.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $50 - $300 |
| Per | GPU-hour |
| Minimum payout | $25 |
| Payout frequency | On request |
| Payment methods | Crypto, Bank |

> RTX 3090 ~$0.20-0.40/hr, RTX 4090 ~$0.40-0.80/hr when rented. Utilization varies. Requires NVIDIA GPU, Linux host, Docker, and nvidia-container-toolkit. Set your own pricing.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 100 Mbps |
| GPU required | Yes |
| Minimum storage | 100GB |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Vast.ai](https://cloud.vast.ai/?ref_id=452772).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Vast.ai** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** ``
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `VAST_API_KEY` | API Key | Yes | Yes | Vast.ai host API key from dashboard |

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/compute/vast-ai.yml`](../../services/compute/vast-ai.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
