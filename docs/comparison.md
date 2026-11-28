# How CashPilot compares

This page compares CashPilot with the other open projects that run several passive income apps in Docker. We checked every project on 2026-11-04, and CashPilot again on 2026-11-28. Each cell about another project links to the file it comes from, at a fixed commit, so you can check it yourself. If a cell is wrong or out of date, please [open an issue](https://github.com/GeiserX/CashPilot/issues).

## Projects compared

| Project | What we checked | Stars on 2026-11-04 | License |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, tag commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` at `65e900d` (2026-10-20), plus the README's claims about its 3.0.0-beta.9 binary | 238 | Proprietary, [own license v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` at `db9338a` (2026-11-03) | 257 | No LICENSE file. The [README][ii-license] allows copying the original and forbids distributing modified copies |
| [CashFactory][cf-tree] | `main` at `0ff4bd0` (2025-04-08) | 410 | The [LICENSE][cf-license-file] file is GPL-3.0, but the [README][cf-license] forbids distributing modified copies |
| [home-assistant-passive-income][ha-tree] (HA add-ons) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band has two code lines. Its default branch `main` (`3bfafb1`) still holds the 4.x code, and its last code change there was on 2026-03-03. Release 5.0.0 is built from a separate history. We compare 5.0.0 because that is what its latest release ships.

IGM's web UI, fleet management and installer binary are closed source and not in its repository. Where a cell depends on them, it says "README claims" and links the README line. Everything else in IGM's column comes from the shell scripts and compose files in the repo.

Left out: [earning-machine](https://github.com/jf-m/earning-machine) and [passiveMachine](https://github.com/Xpl0itU/passiveMachine) have had no commits since 2024. A GitHub search found nothing else maintained that runs more than one app, only single-app images.

## Short version

- **InternetIncome, money4band, IGM and, since v1.69.0, CashPilot can earn on many IPs through proxies.** The first three run each app once per proxy, and proxies are InternetIncome's main feature. CashPilot runs extra copies of a service already deployed on a worker, each through a SOCKS5, HTTP CONNECT or Tailscale exit-node proxy ([proxied copies](proxies.md)).
- **InternetIncome starts 23 apps, IGM starts 20 and CashPilot's worker starts <!-- n:docker -->21<!-- /n -->.** CashPilot tracks more services in total (<!-- n:live -->50<!-- /n -->) because it also follows browser extension, desktop and GPU services that it does not run. Since v1.64.0 it can also run any image you name as a [custom service](custom-services.md).
- **money4band and IGM claim daily rewards for you, and keep app images updated with Watchtower.** CashPilot does neither. It pulls an image again only when you deploy or redeploy.
- **CashPilot is the only one here that reads balances from your provider accounts and keeps a history.** money4band 5.0.0 shows estimates from its own catalog, not your accounts. The others link to each provider's dashboard.
- **CashPilot is the only open-source one here with one UI for many servers.** IGM's README claims fleet management, but that code is in its closed binary.
- **Since v1.70.0, CashPilot is the only one here that keeps earner containers off your LAN by default, with limits.** It is on for new installs and for upgraded installs with no earner on Docker's default bridge. An upgraded install whose earners already sit on that bridge keeps them there until you turn isolation on, and a network you name in `CASHPILOT_CONTAINER_NETWORK` gets no fence from CashPilot ([isolation](isolation.md#modes)). Since 2.0.7 Mysterium runs behind the fence too; a node deployed through 2.0.6 stays on the host's network, unfenced, until you redeploy it ([Mysterium behind the fence](mysterium-fence.md)).

## Side by side

CashPilot's column describes v3.0.1. Each of its cells is short, and the [notes under the table](#cashpilot-notes) hold the details and the code links. The other columns describe the commits in the table above.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA add-ons |
|---|---|---|---|---|---|---|
| Apps it can start (see [how we counted](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> run by the worker, plus [custom images](custom-services.md); <!-- n:live -->50<!-- /n --> tracked in total | 15 ([catalog][m4b-catalog]). The README says 35, which [includes][m4b-readme-35] community and dropped apps | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([compose file][cf-compose]) | 10 ([add-on folders][ha-tree]) |
| How you install it | Docker Compose: one UI, plus a worker on each server ([fleet](fleet.md)) | Python CLI or a prebuilt binary that writes a compose file ([release][m4b-tree]) | `curl \| sh` installer ([README][igm-install]) that downloads a closed binary, checked only against a SHA256SUMS file from the same release ([installer][igm-installer-sums]) | One bash script of 1,608 lines that calls `sudo docker run` ([script][ii-script]) | A static compose file plus `setup.sh` run with sudo ([setup][cf-setup]) | A Home Assistant add-on repository; needs Home Assistant OS or Supervised |
| Many servers, one view | Yes ([fleet](fleet.md)) | No, one stack per device | README claims yes, in the closed binary ([README][igm-features]) | No | No | No |
| Many proxies or IPs | Yes, through SOCKS5, HTTP CONNECT or Tailscale exit-node proxies ([proxied copies](proxies.md), [notes](#cashpilot-notes)) | Yes ([README][m4b-features], [code][m4b-multiproxy]) | Yes ([README][igm-features], [compose][igm-proxy]) | Yes, its main feature ([README][ii-readme-top]) | No | No |
| Earnings | <!-- n:collectors -->20<!-- /n --> collectors read balances from your provider accounts and keep a history | Estimates from catalog ranges, not account data ([code][m4b-earnings]) | None found in the scripts | None | None | None |
| Payouts | Proposes a payout when a balance drops, and records it once you confirm ([schema][cp-payouts]) | None | None | None | None | None |
| Daily reward claiming | No | Yes, sidecars ([README][m4b-features]) | Yes ([README][igm-features], [compose][igm-sidecars]) | No | No | No |
| Credentials at rest | Encrypted (Fernet) in the UI's database ([notes](#cashpilot-notes)) | Encrypted (Fernet); the key file sits in the data directory ([code][m4b-crypto]) | Encrypted (AES-256 with openssl); the key file sits beside the vault ([code][igm-encryptor]) | Plain text in `properties.conf`; some passwords are passed as `docker run` arguments ([script][ii-password-arg]) | Plain text in `.env` ([file][cf-env]) | Add-on options, stored by the Supervisor in `/data/options.json` ([HA docs][ha-options]) |
| Earner container settings | Capabilities dropped except those the catalog grants; `no-new-privileges`, a pids limit; privileged refused ([notes](#cashpilot-notes)) | `no-new-privileges` on every non-privileged service ([code][m4b-nnp]); the proxy container is privileged with `NET_ADMIN` ([template][m4b-tun]) | Nothing set on app services; Mysterium gets `NET_ADMIN` ([compose][igm-hosting-myst]); the proxy container gets `NET_ADMIN`, with `no-new-privileges` and a pids limit ([compose][igm-proxy]) | Ebesucher runs with `seccomp=unconfined` ([script][ii-seccomp]); proxy containers and Mysterium get `NET_ADMIN` | Nothing set | No add-on asks for privileged, host network or Docker API access ([example config][ha-config]) |
| Docker socket mounted into | The socket proxy, read-only, and a one-shot migration container ([notes](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, which is read-only with `no-new-privileges` ([compose][igm-watchtower]) | Five restart helper containers ([script][ii-sock-helper]) and Watchtower ([script][ii-watchtower]) | Portainer, published on ports 8000, 9000 and 9443 on all interfaces ([compose][cf-portainer]), and two Watchtowers ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | None |
| Image tags | <!-- n:pinned -->9<!-- /n --> of the <!-- n:docker -->21<!-- /n --> earner images pinned to a version or digest; the rest float | All 15 app images use `:latest` ([example][m4b-image]); proxy container pinned to v2.6.0, Watchtower to `:1` | No tag, so Docker uses `latest` ([compose][igm-hosting]); a tag is set only for some ARM builds | Mostly `:latest` ([example][ii-seccomp]); EarnApp `:lite`, Honeygain pinned to 0.6.6 when proxied on amd64 ([script][ii-honeygain]), Traffmonetizer per-arch tags on ARM; Watchtower `:nightly` | `:latest` or no tag, except EarnApp `:lite` ([compose][cf-compose]) | One version per add-on, bumped by a daily CI job ([workflow][ha-bump], [example][ha-dockerfile]) |
| App image updates | Pulled again on each deploy or redeploy; no automatic updater | Watchtower ([template][m4b-watchtower]) | Watchtower every 4 hours ([compose][igm-watchtower]) | Watchtower once a day, if you turn it on ([script][ii-watchtower]) | Two Watchtowers, each limited to one app, PacketStream ([compose][cf-watchtower-ps]) and EarnFM ([compose][cf-watchtower-efm]); the other 9 apps are not updated | Home Assistant's add-on updates |
| LAN isolation | On by default for new installs ([isolation](isolation.md#lan-isolation-by-default), [notes](#cashpilot-notes)) | Own bridge subnet ([config][m4b-subnet]), which does not block the LAN | None merged | None found | None found | None found |
| ARM | arm64 UI and worker, with a platform check before each deploy ([ARM](arm.md)) | arm64 and armv7 binaries ([release][m4b-release]) | README claims amd64 and arm64, arm32 with limits, and sets up QEMU ([README][igm-arch]) | Needs binfmt emulation for amd64-only images ([README][ii-arm]) | README says it does not work on a Raspberry Pi ([README][cf-raspberry]) | Per add-on; ProxyRack is amd64 only ([config][ha-proxyrack]) |
| UI | Web UI, plus Desktop, Android, MCP and Home Assistant clients | CLI, menus and a local web dashboard bound to 127.0.0.1 by default ([code][m4b-bind]) | CLI, menus, and per the README a web UI on port 4747 reachable on the LAN ([README][igm-webui]) | None, a script | A bookmarks page on port 80 plus Portainer ([README][cf-ui]) | The Home Assistant add-on panel |
| Latest release | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | No versioned releases | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Outbound calls besides the apps | Update check, public-IP lookup, exchange rates and on-chain balances; fonts and Chart.js from CDNs ([notes](#cashpilot-notes)) | GitHub releases, for its update check ([code][m4b-updater]); Docker Hub and ghcr.io, to check image tags ([code][m4b-registry]); when you run the IP check, `api.ipify.org`, `ifconfig.me` or `icanhazip.com` for your public IP and `ip-api.com` over plain HTTP for IP scores ([code][m4b-ipscore]) | GitHub releases ([code][igm-version]); `api.ipify.org`, `ifconfig.me` or `icanhazip.com` for your public IP ([code][igm-ifconfig]); `ip-api.com` over plain HTTP for IP scores ([code][igm-ipscore]). The closed binary was not checked | None found | None found | None found |

### Notes on CashPilot's column { #cashpilot-notes }

- **Many proxies or IPs.** Since v1.69.0 CashPilot runs extra copies of a service already deployed on a worker, each through its own proxy. SOCKS5 and HTTP CONNECT carry TCP only: the tunnel lets out only TCP to the proxy's port, so SOCKS5 UDP relays are dropped. A Tailscale exit node carries UDP too. The earner shares the network namespace of a tunnel container ([code][cp-proxy-deploy]). That namespace lets out only loopback, the tunnel and the tunnel's own connection to the proxy: TCP to its address and port, or tailscaled's marked packets ([tunnel firewall][cp-tunnel-fw]). So a dead proxy stops the earner instead of leaking its traffic ([how it works](proxies.md#how-it-works)). A service cannot run through a proxy when it needs host networking, published ports, volumes, devices, a GPU or `NET_ADMIN`, `NET_RAW` or `SYS_ADMIN`, or when its terms forbid proxies. So <!-- n:noproxy -->7<!-- /n --> of the <!-- n:docker -->21<!-- /n --> earners earn only from the server's own IP ([what cannot](proxies.md#what-cannot-run-through-a-proxy)).
- **Earnings.** Some collectors need a cookie or token copied from your browser, and some of those expire. Each service's guide says which.
- **Credentials at rest.** The UI keeps the encryption key file in the same data volume as the database ([code][cp-fernet]). Earner credentials reach each worker as container environment variables, so they are plain text in that worker's Docker config (`docker inspect`).
- **Earner container settings.** The worker drops every capability, then adds back what the catalog lists for the service. It sets `no-new-privileges` and a pids limit, and it refuses privileged containers ([code][cp-hardening], [code][cp-privileged], [security defaults](security-defaults.md)). Mysterium runs in its own network namespace on the fenced bridge with `NET_ADMIN`, `SETUID` and `SETGID`, on an image pinned by digest ([catalog][cp-myst]). An optional gVisor runtime can add a user-space kernel ([runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Docker socket.** Since v1.71.0 the worker has no socket. The socket proxy holds it: sockguard 2.4.7, pinned by digest, read-only ([compose][cp-sock]). The worker gets a filtered copy that refuses privileged containers, binds of `/` or of the socket, and capabilities or devices outside the catalog's ([socket proxy](security-defaults.md#docker-socket-proxy)). The one-shot `cashpilot-migrate` container also mounts the socket. It gives the owner label to the volumes and the fence network that older releases created, and recreates their containers on them, so the proxy's owner isolation covers them. It exits before the proxy starts ([compose][cp-migrate]). An earner never gets the socket ([code][cp-mounts]). The proxy is not yet a root boundary. With `CASHPILOT_COMPOSE_DIR` or `CASHPILOT_PROXY_BIND_MOUNTS` set, a compromised worker can plant a symlink in an allowed folder with one container and reach the host's `/` with a second ([details](security-defaults.md#docker-socket-proxy)). The Unraid and TrueNAS listings still mount the raw socket in the worker ([app stores](app-stores.md)).
- **LAN isolation.** On by default since v1.70.0, for new installs and for upgraded installs with no earner on Docker's default bridge. The worker puts earners on its own bridge and writes a firewall table for it ([code][cp-fence]). The table drops private ranges, the tailnet range, cloud metadata, the host's connected subnets and the host itself. With public IP detection on, it also drops the home's public IP ([isolation](isolation.md#lan-isolation-by-default)). An upgraded install whose earners already sit on the default bridge stays there until you press **Turn on isolation**. `CASHPILOT_ISOLATION=off` turns it off. With `CASHPILOT_CONTAINER_NETWORK` set, CashPilot writes no fence for that network, and the firewall rules are yours. On Podman there is no fence, and the fleet page says so ([modes](isolation.md#modes), [code][cp-fence-mode]). Since 2.0.7 Mysterium is fenced too. A node deployed through 2.0.6 stays on the host's network until you redeploy it ([Mysterium behind the fence](mysterium-fence.md)). A check shows what earners can reach ([check](isolation-check.md)).
- **Outbound calls.** Besides the apps themselves, CashPilot calls:
    - GitHub releases, once a day, for its update check (`CASHPILOT_UPDATE_CHECK=off` stops it, [code][cp-update]).
    - `api.ipify.org`, `ifconfig.me` or `icanhazip.com` once an hour from each worker, for its public IP (`CASHPILOT_EGRESS_DETECT=off` stops it, [code][cp-egress]).
    - CoinGecko and Frankfurter, for exchange rates ([code][cp-rates]).
    - mempool.space, api.kaspa.org and public Ethereum, Ethereum Classic, Polygon and Solana RPC nodes, for [on-chain balances](onchain.md).
    - iptoasn.com, for CashPilot's network-name table, at most once a week and only while a worker has [activity](activity.md#network-names-and-countries) turned on ([code][cp-ipgeo]).
    - each provider, for collectors.

    The browser loads Google Fonts ([template][cp-cdn]) and Chart.js from jsDelivr ([template][cp-chartjs]).

None of the projects sends usage telemetry in the code we read. IGM's closed binary could not be read.

Every project here passes app credentials to containers as environment variables, and InternetIncome passes some as command arguments too, so on the host that runs the apps they are plain text in Docker's container config (`Env` and `Args` in `docker inspect`), readable by anyone with Docker access. The "Credentials at rest" row describes the stored copy only.

## How we counted

- **CashPilot.** Services in the catalog with status active or beta and a Docker image, not counting GPU compute or mining pools. The number on this page comes from `scripts/generate_readme_tables.py`, and CI fails if it drifts.
- **money4band 5.0.0.** One JSON file per app in `config/catalog/supported/`: 15. The README's "35 apps" also counts the community catalog, which is off by default ([config][m4b-community]), apps with no Docker image, and dropped apps.
- **IGM.** Entries in `apps.json`: 20, all enabled. The proxy container, Watchtower and the claim sidecars are not counted.
- **InternetIncome.** Each `# Starting ... container` comment block in `internetIncome.sh`, other than the proxy and Watchtower blocks: 24. Ebesucher's Chrome and Firefox blocks are one app, and so are EarnFM and EarnFM Fleetshare, which use the same EarnFM account. The Depin extensions block starts Grass and Gradient ([script][ii-depin]), two apps. Total 23. The README table lists 27 apps, some with a signup link only.
- **CashFactory.** Earning services in `docker-compose.yml`: 11. Portainer, the web server and the two Watchtowers are not counted. One service is commented out.
- **HA add-ons.** Add-on folders with a config file: 10.

We did not check whether each app on each list still pays out.

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
