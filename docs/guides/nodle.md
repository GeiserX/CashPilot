# Nodle

> **Category:** DePIN | **Status:** Active
> **Website:** [https://nodle.com](https://nodle.com)

## Description

Nodle uses smartphone Bluetooth to create IoT infrastructure. The app passively detects and relays data from nearby IoT devices, earning NODL tokens. Featured in Forbes, enterprise partnerships with Vivendi and Hayden AI. Mobile-only (iOS and Android).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout |  |
| Payout frequency | Continuous |
| Payment methods | Crypto |

> Very low earnings. Background phone app using Bluetooth. Web3-only — no web dashboard for earnings, check via app or Polkadot blockchain explorer only.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Ios, Android |

## Setup Instructions

### 1. Install the app

Download the Nodle app from [Google Play](https://play.google.com/store/apps/details?id=io.nodle.cash) or [App Store](https://apps.apple.com/app/nodle-cash/id1480763553). There is no Docker image — Nodle is mobile-only and uses your phone's Bluetooth to detect nearby IoT devices.

### 2. Create a wallet

The app creates a Polkadot-based wallet on first launch. Your NODL earnings are on-chain. There is **no web dashboard** — you can only check earnings inside the app or via a Polkadot/Subscan blockchain explorer.

### 3. Enable permissions

Grant Bluetooth, Location, and Background Activity permissions. The app earns passively by scanning for nearby IoT beacons.

## Docker Configuration

Nodle does not support Docker deployment. It is a mobile-only app that requires Bluetooth hardware.

## Important Notes

- **Web3-only**: Nodle runs on the Nodle parachain (Polkadot ecosystem). There is no centralized API or web dashboard to check earnings or connected devices.
- **Token**: NODL — can be viewed on Subscan or other Polkadot explorers using your wallet address.
- **No IP conflicts**: Since Nodle uses Bluetooth (not internet bandwidth), it does not conflict with other bandwidth-sharing services on the same network.
