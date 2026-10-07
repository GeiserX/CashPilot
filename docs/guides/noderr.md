# Noderr Micronodes

> **Category:** DePIN | **Status:** Beta
>
> **Website:** [https://micronodes.noderr.xyz](https://micronodes.noderr.xyz)

## Description

Noderr Micronodes is the free entry tier of the Noderr Protocol, a DeFi project on Base L2. A micronode is a small agent on a spare Android phone, a Windows PC, a Mac or a Chromium browser. On Android it shares the phone's mobile connection: other Noderr traffic exits through the phone's carrier IP, so it needs a SIM with mobile data. On a PC or in the browser it runs automation tasks for the protocol with spare compute.

CashPilot only lists this service. It does not deploy it, run it or read its balance. You install the client yourself from the official download page and keep track of it there.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 today |
| Payout methods | crypto (NODR, on Base) |
| Minimum payout | Not documented |

The network runs on the Base Sepolia testnet during its beta. The provider's own docs say node rewards are unfunded there and none have been paid. The 5 to 10% APY shown on the site is a design target, not an observed figure. Treat anything you accrue now as testnet tokens with no market value, and check back when the network moves to mainnet.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP required | Not documented |
| VPS allowed | Not documented |
| Devices per account | Unlimited (one node per device) |
| Devices per IP | Not documented |

What each client needs, as published on the download page on 2026-10-07:

| Client | Version | Needs |
|--------|---------|-------|
| Android | 2.5.82 | Android 7 or newer, 64-bit ARM, a SIM with mobile data, kept plugged in |
| Windows | 1.1.6 | Windows 10 or later, x64. The installer is not code-signed, so SmartScreen shows an unknown-publisher notice |
| Mac | 1.0.3 | Apple Silicon. Unsigned and not notarized; the package declares two different minimum macOS versions |
| Browser | Web Store | Chrome, Edge or Brave, earns only while the browser is open |

There is no iOS client.

## What it does with your device

On Android the phone shares its carrier connection: other Noderr traffic exits through your mobile IP and counts against your data plan. The app asks for a recorded consent before it starts, and you can stop sharing from the same screen. The provider warns that some carriers' acceptable-use policies do not allow this, so check yours.

On Windows, Mac and in the browser the client runs what the provider calls social media and content automation tasks with spare compute. The provider says tasks are anonymised and sandboxed. It does not say whether they carry traffic for other people.

## Setup

1. Open [micronodes.noderr.xyz](https://micronodes.noderr.xyz/) and pick your platform. The Windows installer is `noderr-windows-micronode-setup.exe`; the browser client is on the [Chrome Web Store](https://chromewebstore.google.com/detail/noderr-micronode/mlbjidgmenkenbjinkknejaljlhmefhi).
2. Install it. On Windows, click through the SmartScreen notice; it installs for your user only, with no admin rights. On Android, allow installs from your browser, then open the app and choose **Share its connection**.
3. On first launch the client creates the node's wallet and mints a free soulbound Utility NFT to it. Use **Back up wallet** to save the encrypted keystore somewhere safe. The wallet is the node's identity: lose the device without a backup and the node, its reputation score and any unclaimed rewards are gone.
4. Keep it running. On Windows turn on **Keep node running** so it survives a reboot; on Android disable battery optimisation for the app and leave the phone on mobile data.
5. Check rewards in the client or at [dapp.noderr.xyz/nodes](https://dapp.noderr.xyz/nodes), which asks your wallet to sign a message to log in.

There is nothing to add in CashPilot. The service shows in the catalog with its signup link and no deploy button.

## Referral

Noderr has no referral programme, confirmed by the project in October 2026. The link above is the plain download page.

## Sources

- Download page and platform notes: [micronodes.noderr.xyz](https://micronodes.noderr.xyz/)
- Micronode docs: [requirements](https://docs.noderr.xyz/node-operators/micro-nodes/requirements), [setup](https://docs.noderr.xyz/node-operators/micro-nodes/setup-and-installation), [rewards](https://docs.noderr.xyz/node-operators/micro-nodes/rewards)
