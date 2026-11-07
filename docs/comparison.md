# How CashPilot compares

This page compares CashPilot with the other open projects that run several passive income apps in Docker. We checked every project on 2026-11-04. Each cell about another project links to the file it comes from, at a fixed commit, so you can check it yourself. If a cell is wrong or out of date, please [open an issue](https://github.com/GeiserX/CashPilot/issues).

## Projects compared

| Project | What we checked | Stars on 2026-11-04 | License |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, tag commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` at `65e900d` (2026-10-20), plus the README's claims about its 3.0.0-beta.9 binary | 238 | Proprietary, [own license v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` at `db9338a` (2026-11-03) | 257 | No LICENSE file. The [README][ii-license] allows copying the original and forbids distributing modified copies |
| [CashFactory][cf-tree] | `main` at `0ff4bd0` (2025-04-08) | 410 | The [LICENSE][cf-license-file] file is GPL-3.0, but the [README][cf-license] forbids distributing modified copies |
| [home-assistant-passive-income][ha-tree] (HA add-ons) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v1.64.0, `main` at `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band has two code lines. Its default branch `main` (`3bfafb1`) still holds the 4.x code, and its last code change there was on 2026-03-03. Release 5.0.0 is built from a separate history. We compare 5.0.0 because that is what its latest release ships.

IGM's web UI, fleet management and installer binary are closed source and not in its repository. Where a cell depends on them, it says "README claims" and links the README line. Everything else in IGM's column comes from the shell scripts and compose files in the repo.

Left out: [earning-machine](https://github.com/jf-m/earning-machine) and [passiveMachine](https://github.com/Xpl0itU/passiveMachine) have had no commits since 2024. A GitHub search found nothing else maintained that runs more than one app, only single-app images.

## Short version

- **InternetIncome, money4band, IGM and, since v1.69.0, CashPilot can earn on many IPs through proxies.** The first three run each app once per proxy, and proxies are InternetIncome's main feature. CashPilot runs extra copies of a service already deployed on a worker, each through a SOCKS5, HTTP CONNECT or Tailscale exit-node proxy ([proxied copies](proxies.md)).
- **InternetIncome (23) and IGM (20) start more apps than CashPilot's worker (<!-- n:docker -->17<!-- /n -->).** CashPilot tracks more services in total (<!-- n:live -->41<!-- /n -->) because it also follows browser extension, desktop and GPU services that it does not run. Since v1.64.0 it can also run any image you name as a [custom service](custom-services.md).
- **money4band and IGM claim daily rewards for you, and keep app images updated with Watchtower.** CashPilot does neither. It pulls an image again only when you deploy or redeploy.
- **CashPilot is the only one here that reads balances from your provider accounts and keeps a history.** money4band 5.0.0 shows estimates from its own catalog, not your accounts. The others link to each provider's dashboard.
- **CashPilot is the only open-source one here with one UI for many servers.** IGM's README claims fleet management, but that code is in its closed binary.
- **Since v1.70.0, CashPilot is the only one here that keeps earner containers off your LAN by default, with limits.** It is on for new installs and for upgraded installs with no earner on Docker's default bridge. An upgraded install whose earners already sit on that bridge keeps them there until you turn isolation on, a network you name in `CASHPILOT_CONTAINER_NETWORK` gets no fence from CashPilot, and host-networked Mysterium is never fenced ([isolation](isolation.md#modes)).

## Side by side

CashPilot's column describes v1.64.0, except the proxy, Docker socket and LAN isolation rows, which describe v1.71.1 (`0170dee`, 2026-11-06). The other columns describe the commits in the table above.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA add-ons |
|---|---|---|---|---|---|---|
| Apps it can start (see [how we counted](#how-we-counted)) | <!-- n:docker -->17<!-- /n --> run by the worker, plus [custom images](custom-services.md); <!-- n:live -->41<!-- /n --> tracked in total | 15 ([catalog][m4b-catalog]). The README says 35, which [includes][m4b-readme-35] community and dropped apps | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([compose file][cf-compose]) | 10 ([add-on folders][ha-tree]) |
| How you install it | Docker Compose: one UI plus a worker on each server; the worker starts earners through the Docker API ([fleet](fleet.md)) | Python CLI or a prebuilt binary that writes a compose file ([release][m4b-tree]) | `curl \| sh` installer ([README][igm-install]) that downloads a closed binary, checked only against a SHA256SUMS file from the same release ([installer][igm-installer-sums]) | One bash script of 1,608 lines that calls `sudo docker run` ([script][ii-script]) | A static compose file plus `setup.sh` run with sudo ([setup][cf-setup]) | A Home Assistant add-on repository; needs Home Assistant OS or Supervised |
| Many servers, one view | Yes ([fleet](fleet.md)) | No, one stack per device | README claims yes, in the closed binary ([README][igm-features]) | No | No | No |
| Many proxies or IPs | Yes, since v1.69.0: extra copies of a deployed service, each through a SOCKS5, HTTP CONNECT or Tailscale exit-node proxy. SOCKS5 and HTTP CONNECT carry TCP only (the tunnel lets out only TCP to the proxy's port, so SOCKS5 UDP relays are dropped); a Tailscale exit node carries UDP too. The earner shares a tunnel container's network namespace whose firewall lets out only loopback, the tunnel and the tunnel's own connection to the proxy (TCP to its address and port, or tailscaled's marked packets), so a dead proxy stops it instead of leaking ([proxied copies](proxies.md#how-it-works), [code][cp-proxy-deploy], [tunnel firewall][cp-tunnel-fw]). Services that need host networking, published ports, volumes, devices or `NET_ADMIN`, `NET_RAW` or `SYS_ADMIN` cannot run through a proxy ([proxied copies](proxies.md#what-cannot-run-through-a-proxy)) | Yes ([README][m4b-features], [code][m4b-multiproxy]) | Yes ([README][igm-features], [compose][igm-proxy]) | Yes, its main feature ([README][ii-readme-top]) | No | No |
| Earnings | <!-- n:collectors -->15<!-- /n --> collectors read balances from provider accounts and keep a history. Some need a cookie or token copied from your browser, and some of those expire (see each service's guide) | Estimates from catalog ranges, not account data ([code][m4b-earnings]) | None found in the scripts | None | None | None |
| Payouts | Proposes a payout when a balance drops, and records it once you confirm ([schema][cp-payouts]) | None | None | None | None | None |
| Daily reward claiming | No | Yes, sidecars ([README][m4b-features]) | Yes ([README][igm-features], [compose][igm-sidecars]) | No | No | No |
| Credentials at rest | Encrypted (Fernet) in the UI's database; the key file sits in the same data volume ([code][cp-fernet]). Earner credentials reach each worker as container environment variables, so they are plain text in that worker's Docker config (`docker inspect`) | Encrypted (Fernet); the key file sits in the data directory ([code][m4b-crypto]) | Encrypted (AES-256 with openssl); the key file sits beside the vault ([code][igm-encryptor]) | Plain text in `properties.conf`; some passwords are passed as `docker run` arguments ([script][ii-password-arg]) | Plain text in `.env` ([file][cf-env]) | Add-on options, stored by the Supervisor in `/data/options.json` ([HA docs][ha-options]) |
| Earner container settings | Every capability dropped, then the catalog adds back what a service needs; `no-new-privileges`; a pids limit; privileged refused ([code][cp-hardening], [code][cp-privileged]). Mysterium runs with host networking and `NET_ADMIN`, `SETUID` and `SETGID` ([catalog][cp-myst]) | `no-new-privileges` on every non-privileged service ([code][m4b-nnp]); the proxy container is privileged with `NET_ADMIN` ([template][m4b-tun]) | Nothing set on app services; Mysterium gets `NET_ADMIN` ([compose][igm-hosting-myst]); the proxy container gets `NET_ADMIN`, with `no-new-privileges` and a pids limit ([compose][igm-proxy]) | Ebesucher runs with `seccomp=unconfined` ([script][ii-seccomp]); proxy containers and Mysterium get `NET_ADMIN` | Nothing set | No add-on asks for privileged, host network or Docker API access ([example config][ha-config]) |
| Docker socket mounted into | Since v1.71.0, a socket proxy (sockguard 2.4.6, pinned by digest), read-only. The worker gets a filtered copy that refuses privileged containers, binds of `/` or of the socket, and capabilities or devices outside the catalog's ([compose][cp-sock], [details](security-defaults.md)); never an earner ([code][cp-mounts]) | Watchtower ([template][m4b-watchtower]) | Watchtower, which is read-only with `no-new-privileges` ([compose][igm-watchtower]) | Five restart helper containers ([script][ii-sock-helper]) and Watchtower ([script][ii-watchtower]) | Portainer, published on ports 8000, 9000 and 9443 on all interfaces ([compose][cf-portainer]), and two Watchtowers ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | None |
| Image tags | 4 of the <!-- n:docker -->17<!-- /n --> earner images are pinned to a version or digest; the rest float | All 15 app images use `:latest` ([example][m4b-image]); proxy container pinned to v2.6.0, Watchtower to `:1` | No tag, so Docker uses `latest` ([compose][igm-hosting]); a tag is set only for some ARM builds | Mostly `:latest` ([example][ii-seccomp]); EarnApp `:lite`, Honeygain pinned to 0.6.6 when proxied on amd64 ([script][ii-honeygain]), Traffmonetizer per-arch tags on ARM; Watchtower `:nightly` | `:latest` or no tag, except EarnApp `:lite` ([compose][cf-compose]) | One version per add-on, bumped by a daily CI job ([workflow][ha-bump], [example][ha-dockerfile]) |
| App image updates | Pulled again on each deploy or redeploy; no automatic updater | Watchtower ([template][m4b-watchtower]) | Watchtower every 4 hours ([compose][igm-watchtower]) | Watchtower once a day, if you turn it on ([script][ii-watchtower]) | Two Watchtowers, each limited to one app, PacketStream ([compose][cf-watchtower-ps]) and EarnFM ([compose][cf-watchtower-efm]); the other 9 apps are not updated | Home Assistant's add-on updates |
| LAN isolation | On by default since v1.70.0 for new installs and for upgraded installs with no earner on Docker's default bridge: the worker puts earners on its own bridge and writes a firewall table that drops private ranges, the tailnet range, cloud metadata, the host's connected subnets, the host itself and, with public IP detection on, the home's public IP ([isolation](isolation.md#lan-isolation-by-default), [code][cp-fence]). An upgraded install whose earners already sit on the default bridge stays there until you press **Turn on isolation**; `CASHPILOT_ISOLATION=off` turns it off; with `CASHPILOT_CONTAINER_NETWORK` set, CashPilot writes no fence for that network and the firewall rules are yours ([isolation](isolation.md#modes), [code][cp-fence-mode]). Host-networked Mysterium is not covered. A check shows what earners can reach ([check](isolation-check.md)) | Own bridge subnet ([config][m4b-subnet]), which does not block the LAN | None merged | None found | None found | None found |
| ARM | arm64 UI and worker; checks each service's platforms before a deploy ([ARM](arm.md)) | arm64 and armv7 binaries ([release][m4b-release]) | README claims amd64 and arm64, arm32 with limits, and sets up QEMU ([README][igm-arch]) | Needs binfmt emulation for amd64-only images ([README][ii-arm]) | README says it does not work on a Raspberry Pi ([README][cf-raspberry]) | Per add-on; ProxyRack is amd64 only ([config][ha-proxyrack]) |
| UI | Web UI, plus Desktop, Android, MCP and Home Assistant clients | CLI, menus and a local web dashboard bound to 127.0.0.1 by default ([code][m4b-bind]) | CLI, menus, and per the README a web UI on port 4747 reachable on the LAN ([README][igm-webui]) | None, a script | A bookmarks page on port 80 plus Portainer ([README][cf-ui]) | The Home Assistant add-on panel |
| Commits on the default branch, 2026-08-06 to 2026-11-04 | 286 | 6, all docs (5.0.0 is on a separate history) | 6 | 31 | 0 | 23 |
| Latest release | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | No versioned releases | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Outbound calls besides the apps | GitHub releases once a day (`CASHPILOT_UPDATE_CHECK=off` stops it, [code][cp-update]); `api.ipify.org`, `ifconfig.me` or `icanhazip.com` once an hour from each worker, for its public IP (`CASHPILOT_EGRESS_DETECT=off` stops it, [code][cp-egress]); CoinGecko and Frankfurter for exchange rates ([code][cp-rates]); public Ethereum, Polygon and Solana RPC nodes for on-chain balances ([code][cp-onchain]); each provider, for collectors. The browser loads Google Fonts ([template][cp-cdn]) and Chart.js from jsDelivr ([template][cp-chartjs]) | GitHub releases, for its update check ([code][m4b-updater]); Docker Hub and ghcr.io, to check image tags ([code][m4b-registry]); when you run the IP check, `api.ipify.org`, `ifconfig.me` or `icanhazip.com` for your public IP and `ip-api.com` over plain HTTP for IP scores ([code][m4b-ipscore]) | GitHub releases ([code][igm-version]); `api.ipify.org`, `ifconfig.me` or `icanhazip.com` for your public IP ([code][igm-ifconfig]); `ip-api.com` over plain HTTP for IP scores ([code][igm-ipscore]). The closed binary was not checked | None found | None found | None found |

None of the projects sends usage telemetry in the code we read. IGM's closed binary could not be read.

Every project here passes app credentials to containers as environment variables, and InternetIncome passes some as command arguments too, so on the host that runs the apps they are plain text in Docker's container config (`Env` and `Args` in `docker inspect`), readable by anyone with Docker access. The "Credentials at rest" row describes the stored copy only.

## How we counted

- **CashPilot.** Services in the catalog with status active or beta and a Docker image, not counting GPU compute. The number on this page comes from `scripts/generate_readme_tables.py`, and CI fails if it drifts.
- **money4band 5.0.0.** One JSON file per app in `config/catalog/supported/`: 15. The README's "35 apps" also counts the community catalog, which is off by default ([config][m4b-community]), apps with no Docker image, and dropped apps.
- **IGM.** Entries in `apps.json`: 20, all enabled. The proxy container, Watchtower and the claim sidecars are not counted.
- **InternetIncome.** Each `# Starting ... container` comment block in `internetIncome.sh`, other than the proxy and Watchtower blocks: 24. Ebesucher's Chrome and Firefox blocks are one app, and so are EarnFM and EarnFM Fleetshare, which use the same EarnFM account. The Depin extensions block starts Grass and Gradient ([script][ii-depin]), two apps. Total 23. The README table lists 27 apps, some with a signup link only.
- **CashFactory.** Earning services in `docker-compose.yml`: 11. Portainer, the web server and the two Watchtowers are not counted. One service is commented out.
- **HA add-ons.** Add-on folders with a config file: 10.

We did not check whether each app on each list still pays out.

## Where CashPilot is behind

- Services that need host networking, published ports, volumes, devices or extra network capabilities cannot run through a proxy, so 8 of the <!-- n:docker -->17<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia and Anyone Protocol) earn only from the server's own IP ([proxied copies](proxies.md#what-cannot-run-through-a-proxy)).
- Fewer apps that it starts itself than IGM or InternetIncome.
- No daily reward claiming and no automatic image updates.
- 13 of the <!-- n:docker -->17<!-- /n --> earner images float on their publisher's latest tag.
- The socket proxy is not yet a root boundary: a compromised worker can still create containers within its policy, and two-step escapes (joining another container's process namespace, a symlink in an allowed folder) are not refused ([details](security-defaults.md)).
- The encryption key for stored credentials sits in the same volume as the data, and on each worker the earner credentials are plain text in Docker's container config.
- Some collectors need a cookie or token copied from the browser, and some of those expire, so earnings tracking needs upkeep for those services.
- The UI loads fonts and Chart.js from third-party CDNs.
- LAN isolation stays off on an upgraded install whose earners sit on Docker's default bridge until you turn it on, it gives no fence to a network named in `CASHPILOT_CONTAINER_NETWORK`, and it never covers host-networked Mysterium ([isolation](isolation.md#modes)).
- A much smaller community than money4band's.
- It releases often, sometimes several times a day.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/services/bandwidth/mysterium.yml#L83-L91
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-onchain]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/onchain.py#L84-L88
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
