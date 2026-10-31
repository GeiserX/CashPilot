# Vast.ai

> **Category:** GPU Compute | **Status:** Active
>
> **Website:** [https://vast.ai](https://vast.ai)

## Description

Vast.ai is a GPU cloud marketplace where you rent out your NVIDIA GPU to AI/ML researchers and developers. Docker-native platform where you set your own hourly prices. An RTX 3090 typically earns $0.20-0.40/hr when rented. Requires an NVIDIA GPU with recent drivers and a stable internet connection. Revenue depends heavily on GPU model, pricing strategy, and market demand.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $300 (estimate) |
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

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Run it outside CashPilot

CashPilot cannot deploy Vast.ai. The catalog has no Docker image for it, so its row in **Catalog** shows **Visit** instead of **Add**. Run Vast.ai's host software on a Linux machine with a GPU. CashPilot does not read Vast.ai earnings either, so check them in the provider's dashboard.

## Docker Configuration

None. The catalog has no Docker image for Vast.ai.

The catalog defines a `VAST_API_KEY` field (your Vast.ai host API key), but nothing in CashPilot reads it yet.
