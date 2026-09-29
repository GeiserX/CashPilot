<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/CashPilot/main/docs/images/banner.svg" alt="CashPilot" width="100%">
</p>

<p align="center">
  <a href="https://github.com/GeiserX/CashPilot/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/GeiserX/CashPilot?style=flat-square"></a>
  <a href="https://github.com/GeiserX/CashPilot/actions/workflows/test.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/GeiserX/CashPilot/test.yml?style=flat-square&label=tests"></a>
  <a href="https://github.com/GeiserX/CashPilot/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/GeiserX/CashPilot?style=flat-square"></a>
  <a href="https://hub.docker.com/r/drumsergio/cashpilot"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/drumsergio/cashpilot?style=flat-square&logo=docker"></a>
  <a href="https://codecov.io/gh/GeiserX/CashPilot"><img alt="codecov" src="https://codecov.io/gh/GeiserX/CashPilot/graph/badge.svg"></a>
</p>

CashPilot is a self-hosted platform to deploy, manage and monitor passive income services from one web interface. It runs as two Docker containers, deploys the Docker-based services for you, and tracks the browser-extension and desktop-only ones with signup links and balance monitoring. Its catalog covers 39 active services (50 in total) across bandwidth sharing, DePIN, storage and GPU compute, and it collects their earnings into one dashboard with history.

![Dashboard](https://raw.githubusercontent.com/GeiserX/CashPilot/main/docs/images/screenshots/dashboard.png)

## Features

- **Web-based setup wizard** with guided account creation for each service
- **One-click container deployment** for 16 passive income services
- **Real-time earnings dashboard** with historical charts and trend analysis
- **Container health monitoring** -- CPU, memory, network, and uptime at a glance
- **Multi-category support** -- bandwidth sharing, DePIN, storage sharing, GPU compute
- **Automatic earnings collection** from service APIs and dashboards
- **Mobile-responsive dark UI** -- manage your fleet from any device
- **Simple two-container setup** -- UI + Worker, no dependencies to install
- **Runs on x86-64 and ARM** -- Raspberry Pi, Apple Silicon and ARM cloud boxes; see [Running on ARM](https://github.com/GeiserX/CashPilot/blob/main/docs/arm.md)
- **Service catalog** with earning estimates, requirements, and platform details

## Quick Start

```bash
curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/main/docker-compose.yml
docker compose up -d
docker compose logs cashpilot-ui | grep -i "setup token"   # then open http://localhost:8080
```

This starts **cashpilot-ui** (dashboard, earnings collection, catalog, port 8080) and **cashpilot-worker** (Docker agent, port 8081, needs the Docker socket). Open [http://localhost:8080](http://localhost:8080) and enter the one-time **setup token** from `docker compose logs cashpilot-ui` to create the owner account. See [Getting Started](https://geiserx.github.io/CashPilot/getting-started/) for details.

> **Security.** The dashboard is published on loopback only (`127.0.0.1:8080`) because it can command the Docker-socket worker. **Never publish the worker's port (`8081`) on a public interface.** Remote access and fleet setup are in the [configuration reference](https://github.com/GeiserX/CashPilot/blob/main/docs/configuration.md) and [fleet guide](https://github.com/GeiserX/CashPilot/blob/main/docs/fleet.md).

## Supported Services

### Docker-Deployable Services

Services CashPilot can deploy and manage automatically via Docker.

<!-- BEGIN GENERATED: docker-services -->
| Service | Guide | Residential IP required | VPS allowed | Devices / Acct | Devices / IP | Payout |
|---------|-------|:-:|:-:|:-:|:-:|--------|
| [Anyone Protocol](https://anyone.io) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/anyone-protocol.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto |
| [Bitping](https://app.bitping.com) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/bitping.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto (SOL) |
| [Earn.fm](https://earn.fm/ref/GEISYB91) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/earnfm.md) | ✅ | ✅ | ? \*\*\* | 1 | Crypto |
| [EarnApp](https://earnapp.com/i/TSMD9wSm) \*\*\*\* | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/earnapp.md) | ✅ | ❌ | 15 | ? \*\*\* | PayPal, Amazon Gift Card, Wise |
| [Honeygain](https://dashboard.honeygain.com/ref/SERGIB4014) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/honeygain.md) | ✅ | ❌ | 10 | 1 | PayPal, Crypto |
| [IPRoyal Pawns](https://pawns.app?r=19266874) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/iproyal.md) | ✅ | ❌ | ? \*\*\* | 1 | PayPal, Crypto, Bank Transfer |
| [MystNodes](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/mysterium.md) | ❌ | ✅ | ? \*\*\* | Unlimited | Crypto |
| [PacketStream](https://packetstream.io/?psr=7xgZ) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/packetstream.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | PayPal |
| [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxybase.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto |
| [ProxyBase Markets](https://proxybase.xyz?referral=nXzS3c6iTO) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxybase-xyz.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto (USDC) |
| [ProxyLite](https://proxylite.ru/?r=KMUPRZIZ) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxylite.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto, PayPal |
| [ProxyRack](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxyrack.md) | ❌ | ✅ | 500 | ? \*\*\* | PayPal, Crypto |
| [Repocket](https://repocket.com/) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/repocket.md) | ✅ | ❌ | 5 | ? \*\*\* | PayPal, Crypto |
| [Storj](https://storj.dev/node/get-started/setup) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/storj.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto (USDC) |
| [Traffmonetizer](https://traffmonetizer.com/?aff=2111758) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/traffmonetizer.md) | ❌ | ✅ | ? \*\*\* | Unlimited | Crypto (USDT), PayPal |
| [URnetwork](https://ur.io/?referral_code=1Q3G19) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/urnetwork.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto |
<!-- END GENERATED: docker-services -->

> \* Storj nodes on the same /24 subnet share data allocation, reducing per-node earnings.
>
> \*\* Traffmonetizer ToS requires residential IP, but VPS nodes are accepted in practice.
>
> \*\*\*\* EarnApp's help centre **prohibits** Docker containers, VMs, hosting services and home servers, with account termination and cancellation of pending payments as the stated penalty — which is exactly how CashPilot deploys it. Read the [guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/earnapp.md) before deploying.
>
> \*\*\* `?` means the catalog does not record this, so nobody has verified it against the provider. It is **not** a synonym for "no limit" — see [per-IP device limits](https://github.com/GeiserX/CashPilot/blob/main/docs/research/per-ip-device-limits.md) for the values that are sourced. A number widely repeated on review sites is not a source.
>
> These tables are **generated from the service YAML** by `scripts/generate_readme_tables.py` and checked in CI, so they cannot drift from the catalog. Edit the YAML, not the table.

### Browser Extension / Desktop Only

These services have no Docker image. CashPilot lists them in the catalog with signup links and earning estimates, but cannot deploy or monitor them.

<!-- BEGIN GENERATED: extension-services -->
| Service | Guide | Residential IP required | VPS allowed | Devices / Acct | Devices / IP | Payout | Status |
|---------|-------|:-:|:-:|:-:|:-:|--------|--------|
| [Bytebenefit](https://bytebenefit.io/invited?ref=Brl4z3) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/bytebenefit.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | PayPal | Active |
| [Bytelixir](https://bytelixir.com/r/OYEIRE0VSZBZ) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/bytelixir.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Dawn Internet](https://dawninternet.com/?code=2QLQV97F) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/dawn.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Deeper Network](https://deeper.network) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/deeper-network.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Ebesucher](https://www.ebesucher.com/?ref=geiserx) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/ebesucher.md) | ✅ | ❌ | ? \*\*\* | 1 | PayPal | Active |
| [Gradient Network](https://app.gradient.network/signup?referralCode=YSKMY7) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/gradient.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Grass](https://app.grass.io/register?referralCode=kn8FNEPnUr2tMqE) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/grass.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Helium](https://helium.com) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/helium.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Nodepay](https://app.nodepay.ai/register?ref=0wzzyznen64j9zx) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/nodepay.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Nodle](https://nodle.com) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/nodle.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [PassiveApp](https://passiveapp.com/i/bqpC4M) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/passiveapp.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto, PayPal | Active |
| [Sentinel dVPN](https://sentinel.co) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/sentinel-dvpn.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Spide](https://spide.network/register.html?f3bc51) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/spide.md) | ✅ | ❌ | ? \*\*\* | 1 | Crypto | Active |
| [Teneo Protocol](https://dashboard.teneo.pro/?code=CAqef) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/teneo.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Theta Edge Node](https://thetatoken.org) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/theta-edge.md) | ❌ | ✅ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Titan Network](https://edge.titannet.info/signup?inviteCode=2GKKJ495) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/titan.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
| [Uprock](https://link.uprock.com/i/33e8492e) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/uprock.md) | ✅ | ❌ | ? \*\*\* | ? \*\*\* | Crypto | Active |
<!-- END GENERATED: extension-services -->

### GPU Compute

GPU-intensive computing services. Requires compatible hardware.

<!-- BEGIN GENERATED: gpu-services -->
| Service | Guide | Residential IP required | GPU | Min Storage | Payout | Status |
|---------|-------|:-:|:-:|:-:|--------|--------|
| [Flux](https://runonflux.io) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/flux.md) | ❌ | ❌ | 220GB | Crypto | Active |
| [Golem Network](https://golem.network) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/golem.md) | ❌ | ❌ | 20GB | Crypto | Active |
| [io.net](https://io.net) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/ionet.md) | ❌ | ✅ | N/A | Crypto | Active |
| [Nosana](https://nosana.io) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/nosana.md) | ❌ | ✅ | 50GB | Crypto | Active |
| [Salad](https://salad.io) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/salad.md) | ✅ | ✅ | N/A | PayPal, Gift Cards | Active |
| [Vast.ai](https://cloud.vast.ai/?ref_id=452772) | [Guide](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/vast-ai.md) | ❌ | ✅ | 100GB | Crypto, Bank Transfer | Active |
<!-- END GENERATED: gpu-services -->

> **Disclosure.** The signup links in CashPilot and in this README are referral links. If you sign up through one, the maintainer may earn a commission, at no cost to you, which helps fund CashPilot's development. To avoid them, sign up on the provider's own website instead.

## FAQ

Is bandwidth sharing safe? How much can I earn? Can I run on a VPS? How are credentials stored, and how do I back up the key? The answers are in the [FAQ](https://github.com/GeiserX/CashPilot/blob/main/docs/faq.md).

## Documentation

Full documentation: [geiserx.github.io/CashPilot](https://geiserx.github.io/CashPilot/).

- [Getting started](https://geiserx.github.io/CashPilot/getting-started/): install, first run, updating
- [Configuration](https://geiserx.github.io/CashPilot/configuration/): every setting and which source wins; also [fleet management](https://geiserx.github.io/CashPilot/fleet/), [running on ARM](https://geiserx.github.io/CashPilot/arm/) and [protecting your home network](https://geiserx.github.io/CashPilot/home-network-security/)
- [Service guides](https://geiserx.github.io/CashPilot/guides/): one page per service, plus [discontinued services](https://geiserx.github.io/CashPilot/discontinued-services/)
- [How it works](https://geiserx.github.io/CashPilot/how-it-works/): the UI and worker split
- [FAQ](https://geiserx.github.io/CashPilot/faq/)
- [Development](https://geiserx.github.io/CashPilot/development/): adding a service, running the tests
- [Related projects](https://geiserx.github.io/CashPilot/related/) and [how CashPilot compares](https://geiserx.github.io/CashPilot/comparison/)

Upgrading an existing install? Read [UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md) first. It lists only the releases that need you to do something.

## License

[GPL-3.0-or-later](https://github.com/GeiserX/CashPilot/blob/main/LICENSE). Sergio Fernandez, 2026.
