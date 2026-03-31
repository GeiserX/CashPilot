# Salad

> **Category:** GPU Compute | **Status:** Active
> **Website:** [https://salad.io](https://salad.io)

## Description

Salad.io lets you share your GPU for distributed AI workloads and earn Salad balance redeemable for gift cards, games, or cash. Windows only with a native desktop application. Requires a dedicated GPU (NVIDIA or AMD). The platform routes AI inference, rendering, and other compute tasks to your machine when idle. One of the more user-friendly GPU sharing platforms.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $100 (estimate) |
| Per | GPU-hour |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal, Giftcard |

> Earnings depend on GPU model and availability of work. RTX 3060 ~$1-3/day. Windows only. Native app, no Docker support. Redeemable for gift cards, games, or PayPal.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | Yes |
| Minimum storage | None |
| Supported platforms | Windows |

## Setup Instructions

### 1. Create an account

Sign up at [Salad](https://salad.io) and install the desktop application on your Windows machine.

### 2. Get your auth cookie

Salad runs as a native Windows app — there is no Docker image. To let CashPilot track your earnings:

1. Open [salad.com](https://salad.com) in your browser and log in.
2. Press **F12** to open DevTools.
3. Go to **Application > Cookies > salad.com**.
4. Copy the value of the `auth` cookie (starts with `CfDJ8...`).

### 3. Configure CashPilot

Add the cookie to your CashPilot configuration:

```
salad_auth_cookie=<your auth cookie value>
```

CashPilot will poll `app-api.salad.com/api/v1/profile/balance` to fetch your current and lifetime balance.

## Docker Configuration

Salad is a native Windows desktop application — no Docker image is available. CashPilot monitors earnings via the Salad API only.
