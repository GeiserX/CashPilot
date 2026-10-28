# EarnApp

> **Category:** Bandwidth Sharing | **Status:** Active
>
> **Website:** [https://earnapp.com](https://earnapp.com)

!!! danger "EarnApp prohibits the way CashPilot runs it — read this first"

    EarnApp's help centre states: **"Installing EarnApp on Virtual Machines
    (VMs), Docker containers, or hosting services is strictly prohibited."** It
    names **personal or home servers** and **"any device used for business or
    monetization purposes"** as prohibited environments, and says the penalty is
    that your **account is terminated without prior notice** and any **pending
    payments are cancelled**.

    CashPilot deploys every service as a Docker container, usually on a home
    server. **Deploying EarnApp through CashPilot means knowingly accepting that
    risk.** This guide is kept so the decision is an informed one, not so the
    risk is hidden behind a signup link.

    EarnApp does support ordinary desktops, laptops, phones and Raspberry Pi via
    its own installer. If you want to earn with it, that is the route that does
    not put your account and balance at risk — and CashPilot cannot manage it.

## Description

EarnApp by Bright Data lets you sell your unused bandwidth for passive income. Bright Data is the world's largest proxy network, powering data collection for Fortune 500 companies.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $2.50 |
| Payout frequency | On request (auto-redeem available: PayPal $10 min, Wise $10 min, Amazon $50 min) |
| Payment methods | Paypal, Amazon Giftcard, Wise |

> Highly location-dependent. US/EU IPs earn the most. Earnings scale with bandwidth consumed.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android |

## Setup Instructions

### 1. Create an account

Sign up at [EarnApp](https://earnapp.com/i/TSMD9wSm).

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **EarnApp** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `drumsergio/cashpilot-earnapp:1.665.73-r1`, CashPilot's own image
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

The image holds no Bright Data code. At first start it downloads the pinned EarnApp build
from Bright Data's CDN, checks its sha256 and caches it in the `earnapp-data` volume, so the
first start needs that CDN reachable. `EARNAPP_UUID` must be `sdk-node-` followed by 32
lowercase hex characters, which is what `earnapp showid` prints. If `earnapp run` exits, the
image restarts it inside the same container and says so in the log: the container itself
keeps running. A device moved from `fazalfarhan01/earnapp:lite` keeps its UUID and volume.

One exception to the pin: Bright Data's CDN keeps only the build its installer serves today.
If the pinned build is gone and the volume holds no cached copy, the image runs the build the
installer names instead, checked only against the CDN's own unsigned `.sha256` file, and logs
that it did on every start. A cached copy of the pinned build is checked against the pin on every start. See the Upgrades section of
https://github.com/GeiserX/CashPilot/blob/main/images/earnapp/README.md

If you need another image, put it in the deploy form's **Advanced** box. For `venatum/earnapp`
only the `lite` tag works: `venatum/earnapp` (`latest`) and `venatum/earnapp:debian` boot
systemd and need a privileged container, so CashPilot refuses them, as it refuses any image
that boots an init system.

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNAPP_UUID` | Node UUID | Yes | No | Your EarnApp node ID: sdk-node- followed by 32 lowercase hex characters, as 'earnapp showid' prints it |
