<p align="center">
  <img src="https://raw.githubusercontent.com/GeiserX/CashPilot/main/docs/images/banner.svg" alt="CashPilot" width="100%">
</p>

<p align="center">
  <a href="https://github.com/GeiserX/CashPilot/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/GeiserX/CashPilot?style=flat-square"></a>
  <a href="https://github.com/GeiserX/CashPilot/actions/workflows/test.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/GeiserX/CashPilot/test.yml?style=flat-square&label=tests"></a>
  <a href="https://github.com/GeiserX/CashPilot/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/GeiserX/CashPilot?style=flat-square"></a>
  <a href="https://hub.docker.com/r/drumsergio/cashpilot"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/drumsergio/cashpilot?style=flat-square&logo=docker"></a>
  <a href="https://github.com/GeiserX/CashPilot/stargazers"><img alt="GitHub Stars" src="https://img.shields.io/github/stars/GeiserX/CashPilot?style=flat-square&logo=github"></a>
</p>

CashPilot is a self-hosted platform that runs passive income services on your own servers and shows what they earn in one web dashboard. Two Docker containers start the 16 services that run in Docker, keep track of the 24 that run as a browser extension, a desktop app or a GPU node, and read the balances of 15 providers into one earnings history. Without it, each provider is a container you write by hand and a dashboard you log into separately.

![The CashPilot dashboard: balance tiles, a 30-day earnings chart, a payout waiting to be confirmed, and the deployed services table](https://raw.githubusercontent.com/GeiserX/CashPilot/main/docs/images/screenshots/dashboard.png)

## Features

- Starts a Docker service with one click from the catalog; no compose file to write, no YAML to edit.
- Keeps every balance as history: 15 providers are read by built-in collectors every hour, so "running but not earning" shows as a flat line.
- Treats a balance drop as a probable payout and asks you to confirm it; nothing is counted as income by guess.
- Runs a fleet: one worker per server, one dashboard for all of them, every figure per server and per service.
- Checks before you deploy whether the machine fits (residential IP, GPU, disk), and warns when a stored credential is about to expire.
- Encrypts stored credentials at rest; only the worker touches the Docker socket, and the dashboard listens on loopback until you say otherwise.
- Runs on x86-64 and ARM: Raspberry Pi, Apple Silicon and ARM cloud boxes.
- Works from a phone: the dashboard, catalog and wizard are responsive, dark by default, with a light theme.
- Exports Prometheus metrics, and a compose file per service if you would rather run it yourself.

## Quick Start

```bash
curl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/main/docker-compose.yml
docker compose up -d
docker compose logs cashpilot-ui | grep -i "setup token"
```

You need Docker on a Linux, macOS or Windows host, amd64 or arm64. Open [http://localhost:8080](http://localhost:8080): the welcome page asks for the token from that log line, creates the owner account and opens the setup wizard. The dashboard listens on loopback only and the worker's port 8081 is never published, because both can command the Docker socket; [Getting started](https://geiserx.github.io/CashPilot/getting-started/) covers remote access, updating and pinning a version.

## Supported Services

39 active services, 50 catalogued. Each has a [guide](https://geiserx.github.io/CashPilot/guides/) with what it needs, whether it runs in Docker, the payout method and the minimum payout. Services that need a residential IP are marked there; the rest run on a VPS.

<!-- BEGIN GENERATED: docker-services -->
**Run in Docker by CashPilot (16):** [Anyone Protocol](https://anyone.io), [Bitping](https://app.bitping.com), [Earn.fm](https://earn.fm/ref/GEISYB91), [EarnApp](https://earnapp.com/i/TSMD9wSm) \*, [Honeygain](https://dashboard.honeygain.com/ref/SERGIB4014), [IPRoyal Pawns](https://pawns.app?r=19266874), [MystNodes](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE), [PacketStream](https://packetstream.io/?psr=7xgZ), [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO), [ProxyBase Markets](https://proxybase.xyz?referral=nXzS3c6iTO), [ProxyLite](https://proxylite.ru/?r=KMUPRZIZ), [ProxyRack](https://peer.proxyrack.com/ref/mpwiok3xlaxeycnn5znqlg7ipjeutxyxr6xl7vmn), [Repocket](https://repocket.com/), [Storj](https://storj.dev/node/get-started/setup), [Traffmonetizer](https://traffmonetizer.com/?aff=2111758), [URnetwork](https://ur.io/?referral_code=1Q3G19)
<!-- END GENERATED: docker-services -->

<!-- BEGIN GENERATED: extension-services -->
**Browser extension or desktop app, tracked (18):** [Bytebenefit](https://bytebenefit.io/invited?ref=Brl4z3), [Bytelixir](https://bytelixir.com/r/OYEIRE0VSZBZ), [Dawn Internet](https://dawninternet.com/?code=2QLQV97F), [Deeper Network](https://deeper.network), [Ebesucher](https://www.ebesucher.com/?ref=geiserx), [Gradient Network](https://app.gradient.network/signup?referralCode=YSKMY7), [Grass](https://app.grass.io/register?referralCode=kn8FNEPnUr2tMqE), [Helium](https://helium.com), [Nodepay](https://app.nodepay.ai/register?ref=0wzzyznen64j9zx), [Noderr Micronodes](https://micronodes.noderr.xyz/), [Nodle](https://nodle.com), [PassiveApp](https://passiveapp.com/i/bqpC4M), [Sentinel dVPN](https://sentinel.co), [Spide](https://spide.network/register.html?f3bc51), [Teneo Protocol](https://dashboard.teneo.pro/?code=CAqef), [Theta Edge Node](https://thetatoken.org), [Titan Network](https://edge.titannet.info/signup?inviteCode=2GKKJ495), [Uprock](https://link.uprock.com/i/33e8492e)
<!-- END GENERATED: extension-services -->

<!-- BEGIN GENERATED: gpu-services -->
**GPU compute, tracked (6):** [Flux](https://runonflux.io), [Golem Network](https://golem.network), [io.net](https://io.net), [Nosana](https://nosana.io), [Salad](https://salad.io), [Vast.ai](https://cloud.vast.ai/?ref_id=452772)
<!-- END GENERATED: gpu-services -->

> \* EarnApp's help centre **prohibits** Docker containers, VMs, hosting services and home servers, with account termination and cancellation of pending payments as the stated penalty, which is exactly how CashPilot deploys it. Read the [guide](https://geiserx.github.io/CashPilot/guides/earnapp/) before deploying.
>
> These lists are **generated from the service YAML** by `scripts/generate_readme_tables.py` and checked in CI, so they cannot drift from the catalog. Edit the YAML, not the list.

> **Disclosure.** The signup links in CashPilot and in this README are referral links. If you sign up through one, the maintainer may earn a commission, at no cost to you, which helps fund CashPilot's development. To avoid them, sign up on the provider's own website instead.

## FAQ

**How much can I earn?** It depends on your country, your ISP, and how many devices and services you run. One home server running 10 to 15 services makes about $30 to $100 a month; more servers, or GPU compute, add to that. The dashboard shows what you really made.

**Is bandwidth sharing safe?** These services route other people's traffic (market research, ad verification, price checks) through your connection, so strangers use your IP. Read each provider's terms, and read [Protecting your home network](https://geiserx.github.io/CashPilot/home-network-security/) before running them on a LAN you care about. This is not legal advice.

**Can I run it on a VPS?** The services marked residential-only will not pay, or will ban, a datacenter IP. The others run anywhere and are the way to add machines without more home hardware.

**Where are my credentials?** Encrypted at rest in SQLite with a key at `/data/.fernet_key`. Back that file up: without it nothing can be decrypted. More in the [FAQ](https://geiserx.github.io/CashPilot/faq/).

## Documentation

Full documentation: [geiserx.github.io/CashPilot](https://geiserx.github.io/CashPilot/).

- [Getting started](https://geiserx.github.io/CashPilot/getting-started/): install, first run, updating, pinning a version
- [Configuration](https://geiserx.github.io/CashPilot/configuration/): every setting and which source wins; [fleet management](https://geiserx.github.io/CashPilot/fleet/) and [running on ARM](https://geiserx.github.io/CashPilot/arm/)
- Security: [security defaults](https://geiserx.github.io/CashPilot/security-defaults/), [protecting your home network](https://geiserx.github.io/CashPilot/home-network-security/), [network isolation](https://geiserx.github.io/CashPilot/isolation/)
- [Service guides](https://geiserx.github.io/CashPilot/guides/): one page per service, plus [discontinued services](https://geiserx.github.io/CashPilot/discontinued-services/)
- Operations: [backup and restore](https://geiserx.github.io/CashPilot/backup-restore/), [backing up node identities](https://geiserx.github.io/CashPilot/backup/), [Prometheus metrics](https://geiserx.github.io/CashPilot/guides/prometheus-metrics/)
- [How it works](https://geiserx.github.io/CashPilot/how-it-works/): the UI and worker split
- [FAQ](https://geiserx.github.io/CashPilot/faq/) and [how CashPilot compares](https://geiserx.github.io/CashPilot/comparison/)
- [Development](https://geiserx.github.io/CashPilot/development/): adding a service, running the tests; [related projects](https://geiserx.github.io/CashPilot/related/)

Upgrading an existing install? Read [UPGRADING.md](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md) first; it lists only the releases that need you to do something. Release notes are on [GitHub Releases](https://github.com/GeiserX/CashPilot/releases).

## License

[GPL-3.0-or-later](https://github.com/GeiserX/CashPilot/blob/main/LICENSE). Sergio Fernandez, 2026.
