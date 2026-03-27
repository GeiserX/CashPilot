# WizardGain

> **Category:** Bandwidth Sharing | **Status:** Broken
> **Website:** [https://wizardgain.com](https://wizardgain.com)

## Description

WizardGain turns your unused internet bandwidth into a recurring revenue stream. Uses email-based authentication. Pays in cryptocurrency. Official Docker image available as wizardgain/worker.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $1 - $4 |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Crypto payouts. Earnings depend on location and bandwidth demand.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [WizardGain](https://wizardgain.com).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **WizardGain** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `wizardgain/worker`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EMAIL` | Email | Yes | No | Your WizardGain account email |

### Manual Docker Run

If running outside CashPilot:

```bash
docker run -d \
  --name cashpilot-wizardgain \
  -e EMAIL="<Email>" \
  wizardgain/worker
```

## Referral Program

| | Details |
|---|---------|
| Referrer bonus | N/A |
| New user bonus | N/A |

---

*This guide was auto-generated from [`services/bandwidth/wizardgain.yml`](../../services/bandwidth/wizardgain.yml). Edit the YAML source and run `python scripts/generate_docs.py` to update.*
