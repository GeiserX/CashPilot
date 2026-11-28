---
source_hash: 4b8d25fab777
---
# Paano ikinukumpara ang CashPilot { #how-cashpilot-compares }

Ikinukumpara ng pahinang ito ang CashPilot sa iba pang bukas na proyekto na nagpapatakbo ng ilang passive income app sa Docker. Sinuri namin ang bawat proyekto noong 2026-11-04, at muli ang CashPilot noong 2026-11-28. Bawat cell tungkol sa ibang proyekto ay nagli-link sa file na pinagmulan nito, sa isang nakapirming commit, para ikaw mismo ang makapagsuri. Kung mali o luma na ang isang cell, pakiusap [magbukas ng issue](https://github.com/GeiserX/CashPilot/issues).

## Mga proyektong ikinumpara { #projects-compared }

| Proyekto | Ang sinuri namin | Stars noong 2026-11-04 | Lisensya |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, tag commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` sa `65e900d` (2026-10-20), pati ang mga pahayag ng README tungkol sa 3.0.0-beta.9 binary nito | 238 | Proprietary, [sariling lisensya v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` sa `db9338a` (2026-11-03) | 257 | Walang LICENSE file. Pinapayagan ng [README][ii-license] ang pagkopya ng orihinal at ipinagbabawal ang pamamahagi ng binagong kopya |
| [CashFactory][cf-tree] | `main` sa `0ff4bd0` (2025-04-08) | 410 | GPL-3.0 ang [LICENSE][cf-license-file] file, pero ipinagbabawal ng [README][cf-license] ang pamamahagi ng binagong kopya |
| [home-assistant-passive-income][ha-tree] (mga HA add-on) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

May dalawang linya ng code ang money4band. Hawak pa rin ng default branch nitong `main` (`3bfafb1`) ang 4.x na code, at ang huling pagbabago sa code doon ay noong 2026-03-03. Binuo ang release 5.0.0 mula sa hiwalay na history. Ikinukumpara namin ang 5.0.0 dahil iyon ang inilalabas ng pinakabago nitong release.

Closed source ang web UI, pamamahala ng fleet at installer binary ng IGM at wala sa repository nito. Kung saan nakadepende sa mga iyon ang isang cell, sinasabi nitong "README claims" (pahayag ng README) at nagli-link sa linya ng README. Ang lahat ng iba pa sa column ng IGM ay mula sa mga shell script at compose file sa repo.

Hindi isinama: walang commit ang [earning-machine](https://github.com/jf-m/earning-machine) at [passiveMachine](https://github.com/Xpl0itU/passiveMachine) mula noong 2024. Walang nahanap ang paghahanap sa GitHub na iba pang pinapanatiling proyekto na nagpapatakbo ng higit sa isang app, mga image lang na pang-iisang app.

## Maikling bersyon { #short-version }

- **Kayang kumita sa maraming IP sa pamamagitan ng mga proxy ang InternetIncome, money4band, IGM at, mula v1.69.0, ang CashPilot.** Pinapatakbo ng unang tatlo ang bawat app nang isang beses bawat proxy, at mga proxy ang pangunahing feature ng InternetIncome. Nagpapatakbo ang CashPilot ng mga dagdag na kopya ng serbisyong naka-deploy na sa isang worker, bawat isa sa pamamagitan ng SOCKS5, HTTP CONNECT o Tailscale exit-node proxy ([mga proxied copy](proxies.md)).
- **23 app ang sinisimulan ng InternetIncome, 20 ang sa IGM at <!-- n:docker -->21<!-- /n --> ang sa worker ng CashPilot.** Mas maraming serbisyo sa kabuuan ang sinusubaybayan ng CashPilot (<!-- n:live -->50<!-- /n -->) dahil sinusundan din nito ang mga serbisyong browser extension, desktop at GPU na hindi nito pinapatakbo. Mula v1.64.0, kaya rin nitong patakbuhin ang kahit anong image na pangalanan mo bilang [custom na serbisyo](custom-services.md).
- **Nagki-claim ng daily rewards para sa iyo ang money4band at IGM, at pinapanatiling updated ang mga app image gamit ang Watchtower.** Wala sa dalawang iyon ang ginagawa ng CashPilot. Kinukuha lang nitong muli ang isang image kapag nag-deploy o nag-redeploy ka.
- **Ang CashPilot lang dito ang bumabasa ng mga balanse mula sa iyong mga account sa provider at nagtatago ng history.** Nagpapakita ang money4band 5.0.0 ng mga tantya mula sa sarili nitong katalogo, hindi mula sa iyong mga account. Nagli-link ang iba sa dashboard ng bawat provider.
- **Ang CashPilot lang ang open-source dito na may iisang UI para sa maraming server.** Inaangkin ng README ng IGM ang pamamahala ng fleet, pero nasa closed binary nito ang code na iyon.
- **Mula v1.70.0, ang CashPilot lang dito ang naglalayo sa mga earner container mula sa iyong LAN bilang default, may mga limitasyon.** Naka-on ito para sa mga bagong install at para sa mga na-upgrade na install na walang earner app sa default na bridge ng Docker. Ang na-upgrade na install na nasa bridge na iyon na ang mga earner app ay pinapanatili sila roon hanggang i-on mo ang isolation, at walang bakod mula sa CashPilot ang network na pinangalanan mo sa `CASHPILOT_CONTAINER_NETWORK` ([isolation](isolation.md#modes)). Mula 2.0.7, tumatakbo na rin ang Mysterium sa likod ng bakod; ang node na na-deploy hanggang 2.0.6 ay nananatili sa network ng host, walang bakod, hanggang i-redeploy mo ito ([Mysterium sa likod ng bakod](mysterium-fence.md)).

## Magkatabi { #side-by-side }

Inilalarawan ng column ng CashPilot ang v3.0.1. Maikli ang bawat cell nito, at nasa [mga tala sa ilalim ng talahanayan](#cashpilot-notes) ang mga detalye at ang mga link sa code. Inilalarawan ng ibang column ang mga commit sa talahanayan sa itaas.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Mga HA add-on |
|---|---|---|---|---|---|---|
| Mga app na kaya nitong simulan (tingnan ang [paano kami nagbilang](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> na pinapatakbo ng worker, pati [mga custom image](custom-services.md); <!-- n:live -->50<!-- /n --> ang sinusubaybayan sa kabuuan | 15 ([katalogo][m4b-catalog]). Sinasabi ng README na 35, na [kasama][m4b-readme-35] ang mga community at itinigil nang app | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([compose file][cf-compose]) | 10 ([mga folder ng add-on][ha-tree]) |
| Paano ito ini-install | Docker Compose: isang UI, pati isang worker sa bawat server ([fleet](fleet.md)) | Python CLI o prebuilt binary na sumusulat ng compose file ([release][m4b-tree]) | `curl \| sh` installer ([README][igm-install]) na nagda-download ng closed binary, sinusuri lang laban sa SHA256SUMS file mula sa parehong release ([installer][igm-installer-sums]) | Isang bash script na may 1,608 linya na tumatawag sa `sudo docker run` ([script][ii-script]) | Isang static na compose file pati `setup.sh` na pinapatakbo gamit ang sudo ([setup][cf-setup]) | Isang Home Assistant add-on repository; kailangan ang Home Assistant OS o Supervised |
| Maraming server, iisang view | Oo ([fleet](fleet.md)) | Hindi, isang stack bawat device | Inaangkin ng README na oo, sa closed binary ([README][igm-features]) | Hindi | Hindi | Hindi |
| Maraming proxy o IP | Oo, sa pamamagitan ng SOCKS5, HTTP CONNECT o Tailscale exit-node proxy ([mga proxied copy](proxies.md), [mga tala](#cashpilot-notes)) | Oo ([README][m4b-features], [code][m4b-multiproxy]) | Oo ([README][igm-features], [compose][igm-proxy]) | Oo, ang pangunahing feature nito ([README][ii-readme-top]) | Hindi | Hindi |
| Kita | <!-- n:collectors -->20<!-- /n --> collector ang bumabasa ng mga balanse mula sa iyong mga account sa provider at nagtatago ng history | Mga tantya mula sa mga saklaw sa katalogo, hindi data ng account ([code][m4b-earnings]) | Walang nahanap sa mga script | Wala | Wala | Wala |
| Mga payout | Nagmumungkahi ng payout kapag bumaba ang isang balanse, at itinatala ito kapag kinumpirma mo ([schema][cp-payouts]) | Wala | Wala | Wala | Wala | Wala |
| Pag-claim ng daily rewards | Hindi | Oo, mga sidecar ([README][m4b-features]) | Oo ([README][igm-features], [compose][igm-sidecars]) | Hindi | Hindi | Hindi |
| Mga naka-imbak na credential | Naka-encrypt (Fernet) sa database ng UI ([mga tala](#cashpilot-notes)) | Naka-encrypt (Fernet); nasa data directory ang key file ([code][m4b-crypto]) | Naka-encrypt (AES-256 gamit ang openssl); nasa tabi ng vault ang key file ([code][igm-encryptor]) | Plain text sa `properties.conf`; ipinapasa ang ilang password bilang mga argumento ng `docker run` ([script][ii-password-arg]) | Plain text sa `.env` ([file][cf-env]) | Mga opsyon ng add-on, iniimbak ng Supervisor sa `/data/options.json` ([HA docs][ha-options]) |
| Mga setting ng earner container | Tinatanggal ang mga capability maliban sa ibinibigay ng katalogo; `no-new-privileges`, limitasyon sa pids; tinatanggihan ang privileged ([mga tala](#cashpilot-notes)) | `no-new-privileges` sa bawat hindi privileged na serbisyo ([code][m4b-nnp]); privileged na may `NET_ADMIN` ang proxy container ([template][m4b-tun]) | Walang nakatakda sa mga serbisyo ng app; nakakakuha ang Mysterium ng `NET_ADMIN` ([compose][igm-hosting-myst]); nakakakuha ang proxy container ng `NET_ADMIN`, na may `no-new-privileges` at limitasyon sa pids ([compose][igm-proxy]) | Tumatakbo ang Ebesucher nang may `seccomp=unconfined` ([script][ii-seccomp]); nakakakuha ng `NET_ADMIN` ang mga proxy container at ang Mysterium | Walang nakatakda | Walang add-on na humihingi ng privileged, host network o access sa Docker API ([halimbawang config][ha-config]) |
| Saan naka-mount ang Docker socket | Ang socket proxy, read-only, at isang minsanang migration container ([mga tala](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, na read-only na may `no-new-privileges` ([compose][igm-watchtower]) | Limang restart helper container ([script][ii-sock-helper]) at Watchtower ([script][ii-watchtower]) | Portainer, inilalathala sa mga port 8000, 9000 at 9443 sa lahat ng interface ([compose][cf-portainer]), at dalawang Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Wala |
| Mga image tag | <!-- n:pinned -->9<!-- /n --> sa <!-- n:docker -->21<!-- /n --> earner image ang naka-pin sa isang bersyon o digest; gumagalaw ang iba | Gumagamit ng `:latest` ang lahat ng 15 app image ([halimbawa][m4b-image]); naka-pin sa v2.6.0 ang proxy container, ang Watchtower sa `:1` | Walang tag, kaya `latest` ang ginagamit ng Docker ([compose][igm-hosting]); may tag lang para sa ilang ARM build | Karamihan ay `:latest` ([halimbawa][ii-seccomp]); EarnApp `:lite`, naka-pin ang Honeygain sa 0.6.6 kapag naka-proxy sa amd64 ([script][ii-honeygain]), mga tag bawat arch ng Traffmonetizer sa ARM; Watchtower `:nightly` | `:latest` o walang tag, maliban sa EarnApp `:lite` ([compose][cf-compose]) | Isang bersyon bawat add-on, itinataas ng isang araw-araw na CI job ([workflow][ha-bump], [halimbawa][ha-dockerfile]) |
| Mga update ng app image | Kinukuha muli sa bawat deploy o redeploy; walang awtomatikong updater | Watchtower ([template][m4b-watchtower]) | Watchtower bawat 4 na oras ([compose][igm-watchtower]) | Watchtower minsan sa isang araw, kung i-on mo ito ([script][ii-watchtower]) | Dalawang Watchtower, bawat isa ay limitado sa iisang app, PacketStream ([compose][cf-watchtower-ps]) at EarnFM ([compose][cf-watchtower-efm]); hindi naa-update ang iba pang 9 na app | Mga update ng add-on ng Home Assistant |
| LAN isolation | Naka-on bilang default para sa mga bagong install ([isolation](isolation.md#lan-isolation-by-default), [mga tala](#cashpilot-notes)) | Sariling bridge subnet ([config][m4b-subnet]), na hindi humaharang sa LAN | Walang naisama | Walang nahanap | Walang nahanap | Walang nahanap |
| ARM | arm64 na UI at worker, na may platform check bago ang bawat deploy ([ARM](arm.md)) | arm64 at armv7 na binary ([release][m4b-release]) | Inaangkin ng README ang amd64 at arm64, arm32 na may limitasyon, at nagse-set up ng QEMU ([README][igm-arch]) | Kailangan ng binfmt emulation para sa mga image na amd64 lang ([README][ii-arm]) | Sinasabi ng README na hindi ito gumagana sa Raspberry Pi ([README][cf-raspberry]) | Bawat add-on; amd64 lang ang ProxyRack ([config][ha-proxyrack]) |
| UI | Web UI, pati mga client na Desktop, Android, MCP at Home Assistant | CLI, mga menu at lokal na web dashboard na naka-bind sa 127.0.0.1 bilang default ([code][m4b-bind]) | CLI, mga menu, at ayon sa README, web UI sa port 4747 na naaabot sa LAN ([README][igm-webui]) | Wala, isang script | Isang bookmarks page sa port 80 pati Portainer ([README][cf-ui]) | Ang add-on panel ng Home Assistant |
| Pinakabagong release | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Walang release na may bersyon | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Mga outbound call maliban sa mga app | Update check, paghanap ng pampublikong IP, mga exchange rate at mga on-chain na balanse; mga font at Chart.js mula sa mga CDN ([mga tala](#cashpilot-notes)) | Mga release sa GitHub, para sa update check nito ([code][m4b-updater]); Docker Hub at ghcr.io, para tingnan ang mga image tag ([code][m4b-registry]); kapag pinatakbo mo ang IP check, `api.ipify.org`, `ifconfig.me` o `icanhazip.com` para sa iyong pampublikong IP at `ip-api.com` sa plain HTTP para sa mga IP score ([code][m4b-ipscore]) | Mga release sa GitHub ([code][igm-version]); `api.ipify.org`, `ifconfig.me` o `icanhazip.com` para sa iyong pampublikong IP ([code][igm-ifconfig]); `ip-api.com` sa plain HTTP para sa mga IP score ([code][igm-ipscore]). Hindi nasuri ang closed binary | Walang nahanap | Walang nahanap | Walang nahanap |

### Mga tala sa column ng CashPilot { #cashpilot-notes }

- **Maraming proxy o IP.** Mula v1.69.0, nagpapatakbo ang CashPilot ng mga dagdag na kopya ng isang serbisyong naka-deploy na sa isang worker, bawat isa sa pamamagitan ng sarili nitong proxy. TCP lang ang dala ng SOCKS5 at HTTP CONNECT: TCP lang papunta sa port ng proxy ang pinalalabas ng tunnel, kaya itinatapon ang mga SOCKS5 UDP relay. May dalang UDP rin ang Tailscale exit node. Nakikihati ang earner app sa network namespace ng isang tunnel container ([code][cp-proxy-deploy]). Naglalabas lang ang namespace na iyon ng loopback, ng tunnel at ng sariling koneksyon ng tunnel sa proxy: TCP papunta sa address at port nito, o ang mga minarkahang packet ng tailscaled ([tunnel firewall][cp-tunnel-fw]). Kaya pinapahinto ng patay na proxy ang earner app sa halip na tumagas ang traffic nito ([paano ito gumagana](proxies.md#how-it-works)). Hindi maaaring tumakbo sa pamamagitan ng proxy ang isang serbisyo kapag kailangan nito ang host networking, mga published port, volume, device, GPU o `NET_ADMIN`, `NET_RAW` o `SYS_ADMIN`, o kapag ipinagbabawal ng mga tuntunin nito ang proxy. Kaya <!-- n:noproxy -->10<!-- /n --> sa <!-- n:docker -->21<!-- /n --> earner app ang kumikita lang mula sa sariling IP ng server ([ang hindi puwede](proxies.md#what-cannot-run-through-a-proxy)).
- **Kita.** Kailangan ng ilang collector ang cookie o token na kinopya mula sa iyong browser, at nag-e-expire ang ilan sa mga iyon. Sinasabi ng gabay ng bawat serbisyo kung alin.
- **Mga naka-imbak na credential.** Itinatago ng UI ang encryption key file sa parehong data volume ng database ([code][cp-fernet]). Umaabot ang mga credential ng earner app sa bawat worker bilang mga environment variable ng container, kaya plain text sila sa Docker config ng worker na iyon (`docker inspect`).
- **Mga setting ng earner container.** Tinatanggal ng worker ang bawat capability, pagkatapos ibinabalik ang nakalista sa katalogo para sa serbisyo. Itinatakda nito ang `no-new-privileges` at isang limitasyon sa pids, at tinatanggihan nito ang mga privileged container ([code][cp-hardening], [code][cp-privileged], [mga default sa seguridad](security-defaults.md)). Tumatakbo ang Mysterium sa sarili nitong network namespace sa nabakurang bridge na may `NET_ADMIN`, `SETUID` at `SETGID`, sa image na naka-pin ayon sa digest ([katalogo][cp-myst]). Puwedeng magdagdag ng user-space kernel ang opsyonal na gVisor runtime ([mga runtime](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Docker socket.** Mula v1.71.0, walang socket ang worker. Ang socket proxy ang may hawak nito: sockguard 2.4.7, naka-pin ayon sa digest, read-only ([compose][cp-sock]). Nakakakuha ang worker ng sinalang kopya na tumatanggi sa mga privileged container, sa pag-bind ng `/` o ng socket, at sa mga capability o device na wala sa katalogo ([socket proxy](security-defaults.md#docker-socket-proxy)). Nagma-mount din ng socket ang minsanang `cashpilot-migrate` container. Nilalagyan nito ng owner label ang mga volume at ang bakod na network na ginawa ng mga lumang release, at muling ginagawa nito ang kanilang mga container sa mga iyon, para saklawin din sila ng owner isolation ng proxy. Lumalabas ito bago magsimula ang proxy ([compose][cp-migrate]). Hindi kailanman nakakakuha ng socket ang isang earner app ([code][cp-mounts]). Hindi pa root boundary ang proxy. Kapag nakatakda ang `CASHPILOT_COMPOSE_DIR` o `CASHPILOT_PROXY_BIND_MOUNTS`, puwedeng magtanim ang isang na-compromise na worker ng symlink sa pinapayagang folder gamit ang isang container, at maabot ang `/` ng host gamit ang pangalawa ([mga detalye](security-defaults.md#docker-socket-proxy)). Nagma-mount pa rin ng raw socket sa worker ang mga listing sa Unraid at TrueNAS ([mga app store](app-stores.md)).
- **LAN isolation.** Naka-on bilang default mula v1.70.0, para sa mga bagong install at para sa mga na-upgrade na install na walang earner app sa default na bridge ng Docker. Inilalagay ng worker ang mga earner app sa sarili nitong bridge at sumusulat ng firewall table para rito ([code][cp-fence]). Itinatapon ng table ang mga pribadong range, ang tailnet range, ang cloud metadata, ang mga konektadong subnet ng host at ang host mismo. Kapag naka-on ang pagtukoy ng pampublikong IP, itinatapon din nito ang pampublikong IP ng bahay ([isolation](isolation.md#lan-isolation-by-default)). Ang na-upgrade na install na nasa default na bridge na ang mga earner app ay nananatili roon hanggang pindutin mo ang **Turn on isolation** (I-on ang isolation). Pinapapatay ito ng `CASHPILOT_ISOLATION=off`. Kapag nakatakda ang `CASHPILOT_CONTAINER_NETWORK`, walang bakod na isinusulat ang CashPilot para sa network na iyon, at sa iyo ang mga firewall rule. Sa Podman ay walang bakod, at sinasabi iyon ng pahina ng fleet ([mga mode](isolation.md#modes), [code][cp-fence-mode]). Mula 2.0.7, nababakuran na rin ang Mysterium. Ang node na na-deploy hanggang 2.0.6 ay nananatili sa network ng host hanggang i-redeploy mo ito ([Mysterium sa likod ng bakod](mysterium-fence.md)). Ipinapakita ng isang check kung ano ang naaabot ng mga earner app ([check](isolation-check.md)).
- **Mga outbound call.** Bukod sa mga app mismo, tumatawag ang CashPilot sa:
    - Mga release sa GitHub, minsan sa isang araw, para sa update check nito (pinapahinto ito ng `CASHPILOT_UPDATE_CHECK=off`, [code][cp-update]).
    - `api.ipify.org`, `ifconfig.me` o `icanhazip.com` minsan bawat oras mula sa bawat worker, para sa pampublikong IP nito (pinapahinto ito ng `CASHPILOT_EGRESS_DETECT=off`, [code][cp-egress]).
    - CoinGecko at Frankfurter, para sa mga exchange rate ([code][cp-rates]).
    - mempool.space, api.kaspa.org at mga pampublikong RPC node ng Ethereum, Ethereum Classic, Polygon at Solana, para sa [mga on-chain na balanse](onchain.md).
    - iptoasn.com, para sa talahanayan ng CashPilot ng mga pangalan ng network, hindi hihigit sa minsan sa isang linggo at habang may worker lang na naka-on ang [aktibidad](activity.md#network-names-and-countries) ([code][cp-ipgeo]).
    - Bawat provider, para sa mga collector.

    Nilo-load ng browser ang Google Fonts ([template][cp-cdn]) at ang Chart.js mula sa jsDelivr ([template][cp-chartjs]).

Wala sa mga proyekto ang nagpapadala ng usage telemetry sa code na binasa namin. Hindi nabasa ang closed binary ng IGM.

Ipinapasa ng bawat proyekto rito ang mga credential ng app sa mga container bilang mga environment variable, at ipinapasa rin ng InternetIncome ang ilan bilang mga argumento ng command, kaya sa host na nagpapatakbo ng mga app, plain text sila sa container config ng Docker (`Env` at `Args` sa `docker inspect`), na nababasa ng sinumang may access sa Docker. Ang naka-imbak na kopya lang ang inilalarawan ng row na "Mga naka-imbak na credential".

## Paano kami nagbilang { #how-we-counted }

- **CashPilot.** Mga serbisyo sa katalogo na may status na active o beta at may Docker image, hindi binibilang ang GPU compute o mga mining pool. Ang numero sa pahinang ito ay mula sa `scripts/generate_readme_tables.py`, at pumapalya ang CI kapag lumihis ito.
- **money4band 5.0.0.** Isang JSON file bawat app sa `config/catalog/supported/`: 15. Binibilang din ng "35 apps" ng README ang community catalog, na naka-off bilang default ([config][m4b-community]), mga app na walang Docker image, at mga itinigil nang app.
- **IGM.** Mga entry sa `apps.json`: 20, lahat naka-enable. Hindi binibilang ang proxy container, Watchtower at ang mga claim sidecar.
- **InternetIncome.** Bawat comment block na `# Starting ... container` sa `internetIncome.sh`, maliban sa mga block ng proxy at Watchtower: 24. Iisang app ang mga block ng Chrome at Firefox ng Ebesucher, gayundin ang EarnFM at EarnFM Fleetshare, na gumagamit ng parehong EarnFM account. Sinisimulan ng block ng mga Depin extension ang Grass at Gradient ([script][ii-depin]), dalawang app. Kabuuang 23. Naglilista ang talahanayan ng README ng 27 app, ang ilan ay may signup link lang.
- **CashFactory.** Mga serbisyong kumikita sa `docker-compose.yml`: 11. Hindi binibilang ang Portainer, ang web server at ang dalawang Watchtower. Naka-comment out ang isang serbisyo.
- **Mga HA add-on.** Mga folder ng add-on na may config file: 10.

Hindi namin sinuri kung nagpa-payout pa ang bawat app sa bawat listahan.

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
