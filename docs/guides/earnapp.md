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
| Minimum payout | $10 |
| Payout frequency | On request (auto-redeem available: PayPal $10 min, Wise $10 min, Amazon $50 min) |
| Payment methods | Paypal, Amazon Giftcard, Wise |

> Highly location-dependent. US/EU IPs earn the most. Earnings scale with bandwidth consumed.

## Cashing out

Turn on auto-redeem once and EarnApp pays by itself whenever the balance reaches the method's minimum: PayPal $10, Wise $10, Amazon $50. PayPal payments arrive from Bright Data Ltd. In October 2026 a $37.54 balance arrived as $36.81 in PayPal, about 2% less.

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

### 2. Make a node UUID

Each device needs its own UUID: `sdk-node-` followed by 32 lowercase hex characters. Make one with:

```sh
echo sdk-node-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
```

Use a new UUID on every machine. Two containers with the same UUID count as one device.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **EarnApp** in the service catalog, click **Deploy** and paste the UUID into **Node UUID**.

### 4. Link the device to your account

This step is easy to miss, and it costs you money if you do. A node that is never linked
still runs and still carries traffic, but EarnApp credits what it earns to the device, not to
you. Your balance does not move, so it looks as if the node earns nothing.

While signed in to EarnApp in your browser, open this once for each device:

```text
https://earnapp.com/r/<your UUID>
```

The page should say "Device successfully linked". The container log prints the same address
at every start (`docker logs cashpilot-earnapp`).

To check, open **Passive income** in the EarnApp dashboard. Every device you run should be in
the list. If one is missing, it is not linked yet. Linking it late is fine: what it earned
while unlinked moves to your balance when you link it. One of our own nodes ran unlinked for
95 days, and linking it added that whole period's earnings at once.

Link again whenever you redeploy with a new UUID. A redeploy that keeps the UUID needs nothing.

## Docker Configuration

- **Image:** `drumsergio/cashpilot-earnapp:1.665.73-r2`, CashPilot's own image
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
