# Teneo Protocol

> **Category:** DePIN | **Status:** Active
>
> **Website:** [teneo.pro](https://hub.teneo.pro/signup?ref=PSA3BHPJ)
>
> <small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

## Description

Teneo Protocol gives AI agents access to the live web through a network of Beacons. The Teneo Beacon is Teneo's own app for Android, iOS, macOS, Windows and Linux, with a command-line version for servers and a Raspberry Pi. It shares your unused bandwidth after you accept its consent screen, and earns Teneo Protocol Points and Fragments while it is online. Fragments count toward seasonal draws paid in USDC (the Beacon Drop). Teneo says the Beacon earns twice the points of its older browser extension. One Beacon earns per internet connection. Other devices on the same connection stand by.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | None published |
| Payout frequency | Seasonal draw (Beacon Drop) |
| Payment methods | Crypto (USDC) |

> The Beacon earns Teneo Points and Fragments. Fragments count toward seasonal USDC draws, so a season pays a prize, not a rate. Claim the boost every 8 hours for up to 3x Fragments; a missed window lowers the multiplier.

## Referral bonus

| Who | What they get |
|-----|---------------|
| You, when you sign up with the link or the code | +100 Fragments at signup, then +150 Fragments once you reach 480 Fragments |
| The person who referred you | 8% of your Fragments, and 2% of the Fragments of the people you refer. Teneo starts this reward once you sign up within 7 days and earn 480 Fragments. |

The bonus never reduces your own earnings. Datacentre machines get no referral bonus. Sources: [Teneo Beacon](https://teneo-protocol.ai/beacon) and the referral page of the [Expedition Hub](https://hub.teneo.pro/quests/referral).

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes, except on hosting providers Teneo has enabled (see below) |
| Devices per connection | One earns, the others stand by |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Android, iOS (TestFlight), macOS, Windows, Linux |

A machine in a datacentre earns only on hosting providers Teneo has enabled, at half the Fragments, with no points and no referral bonus. A VPN connection never earns. Source: [Beacon CLI](https://teneo-protocol.ai/beacon/cli).

## Setup Instructions

### 1. Create an account

Open the [Expedition Hub sign-up page](https://hub.teneo.pro/signup?ref=PSA3BHPJ). The link fills in referral code `PSA3BHPJ`. If you open the Hub another way, type `PSA3BHPJ` in **Referral Code (optional)** on the sign-up page.

<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

### 2. Install the Beacon and sign in

Download the Beacon for your device from [teneo-protocol.ai/beacon](https://teneo-protocol.ai/beacon). Android gets it from Google Play and iOS from TestFlight. macOS gets a DMG, Windows an installer, and Linux DEB or RPM packages. Sign in with the account from step 1, accept the consent screen and go online.

For a Raspberry Pi or a home server, use the [Beacon CLI](https://teneo-protocol.ai/beacon/cli) instead. Run `teneo-beacon`, scan the QR code with your phone while you are signed in at the Hub, and confirm.

### 3. Run it outside CashPilot

CashPilot cannot deploy Teneo Protocol. The catalog has no Docker image for it, so its row in **Catalog** shows **Visit** instead of **Add**. CashPilot does not read Teneo Protocol earnings either, so check your Points and Fragments in the [Expedition Hub](https://hub.teneo.pro).

### 4. Bind a wallet for the USDC prizes

Beacon Drop prizes are paid in USDC to a wallet you bind in the Expedition Hub. The Hub shows how many days you have to bind one, and a prize with no wallet bound in time is forfeited.

Teneo's Chrome extension (the Community Node) still exists, but Teneo says the Beacon earns twice its points. If you already run the extension, sign in to the Beacon with the same account.

## Docker Configuration

None. The catalog has no Docker image for Teneo Protocol.
