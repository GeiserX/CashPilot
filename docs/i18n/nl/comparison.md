---
source_hash: 1a93abea95d7
---
# Hoe CashPilot zich verhoudt tot andere projecten { #how-cashpilot-compares }

Deze pagina vergelijkt CashPilot met de andere open projecten die meerdere apps voor passief inkomen in Docker draaien. We hebben elk project op 2026-11-04 gecontroleerd. Elke cel over een ander project linkt naar het bestand waar ze vandaan komt, op een vaste commit, zodat je het zelf kunt nagaan. Klopt een cel niet of is ze verouderd, [open dan een issue](https://github.com/GeiserX/CashPilot/issues).

## Vergeleken projecten { #projects-compared }

| Project | Wat we controleerden | Sterren op 2026-11-04 | Licentie |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, tag-commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` op `65e900d` (2026-10-20), plus wat de README beweert over zijn binary 3.0.0-beta.9 | 238 | Propriëtair, [eigen licentie v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` op `db9338a` (2026-11-03) | 257 | Geen LICENSE-bestand. De [README][ii-license] staat kopiëren van het origineel toe en verbiedt het verspreiden van aangepaste kopieën |
| [CashFactory][cf-tree] | `main` op `0ff4bd0` (2025-04-08) | 410 | Het bestand [LICENSE][cf-license-file] is GPL-3.0, maar de [README][cf-license] verbiedt het verspreiden van aangepaste kopieën |
| [home-assistant-passive-income][ha-tree] (HA-add-ons) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v1.64.0, `main` op `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band heeft twee codelijnen. Zijn standaardbranch `main` (`3bfafb1`) bevat nog de 4.x-code, en de laatste codewijziging daar was op 2026-03-03. Release 5.0.0 is gebouwd vanuit een aparte geschiedenis. We vergelijken 5.0.0 omdat dat is wat zijn nieuwste release levert.

De web-UI, het vlootbeheer en de installatiebinary van IGM zijn gesloten broncode en staan niet in zijn repository. Waar een cel daarvan afhangt, staat er "README beweert" en linkt ze naar de regel in de README. Al het andere in de kolom van IGM komt uit de shellscripts en compose-bestanden in de repo.

Weggelaten: [earning-machine](https://github.com/jf-m/earning-machine) en [passiveMachine](https://github.com/Xpl0itU/passiveMachine) hebben sinds 2024 geen commits meer gehad. Een zoekopdracht op GitHub vond niets anders dat wordt onderhouden en meer dan één app draait, alleen images voor één app.

## Kort samengevat { #short-version }

- **InternetIncome, money4band, IGM en, sinds v1.69.0, CashPilot kunnen via proxy's op veel IP-adressen verdienen.** De eerste drie draaien elke app één keer per proxy, en proxy's zijn de hoofdfunctie van InternetIncome. CashPilot draait extra kopieën van een dienst die al op een worker is uitgerold, elk via een SOCKS5-, HTTP CONNECT- of Tailscale-exit-node-proxy ([proxy-kopieën](proxies.md)).
- **InternetIncome (23) start meer apps dan de worker van CashPilot (<!-- n:docker -->21<!-- /n -->); IGM start er 20.** CashPilot volgt in totaal meer diensten (<!-- n:live -->50<!-- /n -->) omdat het ook browserextensies, desktop- en GPU-diensten volgt die het niet draait. Sinds v1.64.0 kan het ook elke image draaien die je noemt, als [eigen dienst](custom-services.md).
- **money4band en IGM claimen dagelijkse beloningen voor je, en houden app-images bijgewerkt met Watchtower.** CashPilot doet geen van beide. Het haalt een image alleen opnieuw op wanneer je uitrolt of opnieuw uitrolt.
- **CashPilot is hier de enige die saldi uit je accounts bij de aanbieders leest en een geschiedenis bijhoudt.** money4band 5.0.0 toont schattingen uit zijn eigen catalogus, niet uit je accounts. De andere linken naar het dashboard van elke aanbieder.
- **CashPilot is hier de enige opensourceoplossing met één UI voor veel servers.** De README van IGM beweert vlootbeheer, maar die code zit in zijn gesloten binary.
- **Sinds v1.70.0 is CashPilot hier de enige die containers van verdien-apps standaard van je LAN af houdt, met beperkingen.** Het staat aan voor nieuwe installaties en voor bijgewerkte installaties zonder verdien-app op de standaardbridge van Docker. Een bijgewerkte installatie waarvan de verdien-apps al op die bridge staan, houdt ze daar tot je isolatie aanzet, en een netwerk dat je in `CASHPILOT_CONTAINER_NETWORK` noemt, krijgt geen afscherming van CashPilot ([isolatie](isolation.md#modes)). Sinds 2.0.7 draait Mysterium ook achter de afscherming; een node die tot en met 2.0.6 is uitgerold, blijft zonder afscherming op het netwerk van de host tot je hem opnieuw uitrolt ([Mysterium achter de afscherming](mysterium-fence.md)).

## Naast elkaar { #side-by-side }

De kolom van CashPilot beschrijft v1.64.0, behalve de rijen over proxy's, de Docker-socket en LAN-isolatie, die v1.71.1 beschrijven (`0170dee`, 2026-11-06), en het netwerk van Mysterium in de rijen over containerinstellingen en LAN-isolatie, die de release na 2.0.6 beschrijven (`01e7310`). De rij over uitgaande verbindingen omvat de aanroepen naar explorers in de [huidige handleiding voor on-chain saldi](onchain.md). De andere kolommen beschrijven de commits in de tabel hierboven.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA-add-ons |
|---|---|---|---|---|---|---|
| Apps die het kan starten (zie [hoe we telden](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> gedraaid door de worker, plus [eigen images](custom-services.md); <!-- n:live -->50<!-- /n --> gevolgd in totaal | 15 ([catalogus][m4b-catalog]). De README zegt 35, wat [ook][m4b-readme-35] community-apps en geschrapte apps omvat | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([compose-bestand][cf-compose]) | 10 ([add-on-mappen][ha-tree]) |
| Hoe je het installeert | Docker Compose: één UI plus een worker op elke server; de worker start verdien-apps via de Docker API ([vloot](fleet.md)) | Python-CLI of een kant-en-klare binary die een compose-bestand schrijft ([release][m4b-tree]) | Installer via `curl \| sh` ([README][igm-install]) die een gesloten binary downloadt, alleen gecontroleerd tegen een SHA256SUMS-bestand uit dezelfde release ([installer][igm-installer-sums]) | Eén bashscript van 1.608 regels dat `sudo docker run` aanroept ([script][ii-script]) | Een statisch compose-bestand plus `setup.sh`, uitgevoerd met sudo ([setup][cf-setup]) | Een Home Assistant-add-on-repository; vereist Home Assistant OS of Supervised |
| Veel servers, één overzicht | Ja ([vloot](fleet.md)) | Nee, één stack per apparaat | README beweert ja, in de gesloten binary ([README][igm-features]) | Nee | Nee | Nee |
| Veel proxy's of IP-adressen | Ja, sinds v1.69.0: extra kopieën van een uitgerolde dienst, elk via een SOCKS5-, HTTP CONNECT- of Tailscale-exit-node-proxy. SOCKS5 en HTTP CONNECT dragen alleen TCP (de tunnel laat alleen TCP naar de poort van de proxy naar buiten, dus UDP-relays van SOCKS5 worden verworpen); een Tailscale-exit-node draagt ook UDP. De verdien-app deelt de netwerknamespace van een tunnelcontainer waarvan de firewall alleen loopback, de tunnel en de eigen verbinding van de tunnel met de proxy naar buiten laat (TCP naar zijn adres en poort, of de gemarkeerde pakketten van tailscaled), dus een dode proxy houdt hem tegen in plaats van te lekken ([proxy-kopieën](proxies.md#how-it-works), [code][cp-proxy-deploy], [tunnelfirewall][cp-tunnel-fw]). Diensten die hostnetwerk, gepubliceerde poorten, volumes, apparaten of `NET_ADMIN`, `NET_RAW` of `SYS_ADMIN` nodig hebben, kunnen niet via een proxy draaien ([proxy-kopieën](proxies.md#what-cannot-run-through-a-proxy)) | Ja ([README][m4b-features], [code][m4b-multiproxy]) | Ja ([README][igm-features], [compose][igm-proxy]) | Ja, zijn hoofdfunctie ([README][ii-readme-top]) | Nee | Nee |
| Inkomsten | <!-- n:collectors -->20<!-- /n --> collectors lezen saldi uit accounts bij de aanbieders en houden een geschiedenis bij. Sommige hebben een cookie of token nodig dat uit je browser is gekopieerd, en sommige daarvan verlopen (zie de handleiding van elke dienst) | Schattingen uit bereiken in de catalogus, geen accountgegevens ([code][m4b-earnings]) | Niets gevonden in de scripts | Geen | Geen | Geen |
| Uitbetalingen | Stelt een uitbetaling voor wanneer een saldo daalt, en legt die vast zodra je bevestigt ([schema][cp-payouts]) | Geen | Geen | Geen | Geen | Geen |
| Dagelijkse beloningen claimen | Nee | Ja, sidecars ([README][m4b-features]) | Ja ([README][igm-features], [compose][igm-sidecars]) | Nee | Nee | Nee |
| Inloggegevens in rust | Versleuteld (Fernet) in de database van de UI; het sleutelbestand staat in hetzelfde datavolume ([code][cp-fernet]). Inloggegevens van verdien-apps bereiken elke worker als omgevingsvariabelen van de container, dus ze staan als platte tekst in de Docker-configuratie van die worker (`docker inspect`) | Versleuteld (Fernet); het sleutelbestand staat in de datamap ([code][m4b-crypto]) | Versleuteld (AES-256 met openssl); het sleutelbestand staat naast de kluis ([code][igm-encryptor]) | Platte tekst in `properties.conf`; sommige wachtwoorden worden als argumenten van `docker run` meegegeven ([script][ii-password-arg]) | Platte tekst in `.env` ([bestand][cf-env]) | Add-on-opties, door de Supervisor opgeslagen in `/data/options.json` ([HA-documentatie][ha-options]) |
| Containerinstellingen van verdien-apps | Alle capabilities verwijderd, daarna voegt de catalogus terug wat een dienst nodig heeft; `no-new-privileges`; een pids-limiet; privileged geweigerd ([code][cp-hardening], [code][cp-privileged]). Mysterium draait in zijn eigen netwerknamespace op de afgeschermde bridge met `NET_ADMIN`, `SETUID` en `SETGID`, op een image die op digest is gepind ([catalogus][cp-myst]) | `no-new-privileges` op elke niet-geprivilegieerde dienst ([code][m4b-nnp]); de proxycontainer is privileged met `NET_ADMIN` ([template][m4b-tun]) | Niets ingesteld op app-diensten; Mysterium krijgt `NET_ADMIN` ([compose][igm-hosting-myst]); de proxycontainer krijgt `NET_ADMIN`, met `no-new-privileges` en een pids-limiet ([compose][igm-proxy]) | Ebesucher draait met `seccomp=unconfined` ([script][ii-seccomp]); proxycontainers en Mysterium krijgen `NET_ADMIN` | Niets ingesteld | Geen enkele add-on vraagt om privileged, hostnetwerk of toegang tot de Docker API ([voorbeeldconfiguratie][ha-config]) |
| Docker-socket gemount in | Sinds v1.71.0 een socket-proxy (sockguard 2.4.5, op digest gepind), alleen-lezen. De worker krijgt een gefilterde kopie die geprivilegieerde containers, binds van `/` of van de socket, en capabilities of apparaten buiten die van de catalogus weigert ([compose][cp-sock], [details](security-defaults.md)); nooit in een verdien-app ([code][cp-mounts]) | Watchtower ([template][m4b-watchtower]) | Watchtower, alleen-lezen met `no-new-privileges` ([compose][igm-watchtower]) | Vijf hulpcontainers voor herstarten ([script][ii-sock-helper]) en Watchtower ([script][ii-watchtower]) | Portainer, gepubliceerd op de poorten 8000, 9000 en 9443 op alle interfaces ([compose][cf-portainer]), en twee Watchtowers ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Geen |
| Image-tags | 9 van de <!-- n:docker -->21<!-- /n --> images van verdien-apps zijn gepind op een versie of digest; de rest beweegt mee | Alle 15 app-images gebruiken `:latest` ([voorbeeld][m4b-image]); proxycontainer gepind op v2.6.0, Watchtower op `:1` | Geen tag, dus Docker gebruikt `latest` ([compose][igm-hosting]); alleen voor sommige ARM-builds is een tag ingesteld | Meestal `:latest` ([voorbeeld][ii-seccomp]); EarnApp `:lite`, Honeygain gepind op 0.6.6 bij gebruik via proxy op amd64 ([script][ii-honeygain]), Traffmonetizer met tags per architectuur op ARM; Watchtower `:nightly` | `:latest` of geen tag, behalve EarnApp `:lite` ([compose][cf-compose]) | Eén versie per add-on, opgehoogd door een dagelijkse CI-job ([workflow][ha-bump], [voorbeeld][ha-dockerfile]) |
| Updates van app-images | Opnieuw opgehaald bij elke uitrol of bij opnieuw uitrollen; geen automatische updater | Watchtower ([template][m4b-watchtower]) | Watchtower elke 4 uur ([compose][igm-watchtower]) | Watchtower één keer per dag, als je dat aanzet ([script][ii-watchtower]) | Twee Watchtowers, elk beperkt tot één app, PacketStream ([compose][cf-watchtower-ps]) en EarnFM ([compose][cf-watchtower-efm]); de andere 9 apps worden niet bijgewerkt | De add-on-updates van Home Assistant |
| LAN-isolatie | Standaard aan sinds v1.70.0 voor nieuwe installaties en voor bijgewerkte installaties zonder verdien-app op de standaardbridge van Docker: de worker zet verdien-apps op zijn eigen bridge en schrijft een firewalltabel die privébereiken, het tailnetbereik, cloudmetadata, de verbonden subnetten van de host, de host zelf en, met detectie van het publieke IP-adres aan, het publieke IP-adres van het huis verwerpt ([isolatie](isolation.md#lan-isolation-by-default), [code][cp-fence]). Een bijgewerkte installatie waarvan de verdien-apps al op de standaardbridge staan, blijft daar tot je op **Turn on isolation** (Isolatie inschakelen) drukt; `CASHPILOT_ISOLATION=off` zet het uit; met `CASHPILOT_CONTAINER_NETWORK` ingesteld schrijft CashPilot geen afscherming voor dat netwerk en zijn de firewallregels aan jou ([isolatie](isolation.md#modes), [code][cp-fence-mode]). Sinds 2.0.7 wordt Mysterium ook afgeschermd; een node die tot en met 2.0.6 is uitgerold, blijft op het netwerk van de host tot je hem opnieuw uitrolt ([Mysterium achter de afscherming](mysterium-fence.md)). Een controle toont wat verdien-apps kunnen bereiken ([controle](isolation-check.md)) | Eigen bridgesubnet ([configuratie][m4b-subnet]), dat het LAN niet blokkeert | Niets samengevoegd | Niets gevonden | Niets gevonden | Niets gevonden |
| ARM | arm64-UI en -worker; controleert vóór een uitrol de platforms van elke dienst ([ARM](arm.md)) | arm64- en armv7-binary's ([release][m4b-release]) | README beweert amd64 en arm64, arm32 met beperkingen, en zet QEMU op ([README][igm-arch]) | Vereist binfmt-emulatie voor images die alleen voor amd64 zijn ([README][ii-arm]) | README zegt dat het niet werkt op een Raspberry Pi ([README][cf-raspberry]) | Per add-on; ProxyRack is alleen amd64 ([configuratie][ha-proxyrack]) |
| UI | Web-UI, plus clients voor Desktop, Android, MCP en Home Assistant | CLI, menu's en een lokaal webdashboard dat standaard aan 127.0.0.1 is gebonden ([code][m4b-bind]) | CLI, menu's en volgens de README een web-UI op poort 4747 die op het LAN bereikbaar is ([README][igm-webui]) | Geen, een script | Een bladwijzerpagina op poort 80 plus Portainer ([README][cf-ui]) | Het add-on-paneel van Home Assistant |
| Commits op de standaardbranch, 2026-08-06 tot 2026-11-04 | 286 | 6, allemaal documentatie (5.0.0 staat in een aparte geschiedenis) | 6 | 31 | 0 | 23 |
| Nieuwste release | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Geen releases met versienummer | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Uitgaande verbindingen naast die van de apps | GitHub-releases één keer per dag (`CASHPILOT_UPDATE_CHECK=off` stopt dat, [code][cp-update]); `api.ipify.org`, `ifconfig.me` of `icanhazip.com` één keer per uur vanaf elke worker, voor zijn publieke IP-adres (`CASHPILOT_EGRESS_DETECT=off` stopt dat, [code][cp-egress]); CoinGecko en Frankfurter voor wisselkoersen ([code][cp-rates]); mempool.space, api.kaspa.org en openbare RPC-nodes van Ethereum, Polygon en Solana voor [on-chain saldi](onchain.md); elke aanbieder, voor collectors. De browser laadt Google Fonts ([template][cp-cdn]) en Chart.js van jsDelivr ([template][cp-chartjs]) | GitHub-releases, voor zijn updatecontrole ([code][m4b-updater]); Docker Hub en ghcr.io, om image-tags te controleren ([code][m4b-registry]); wanneer je de IP-controle uitvoert, `api.ipify.org`, `ifconfig.me` of `icanhazip.com` voor je publieke IP-adres en `ip-api.com` via gewone HTTP voor IP-scores ([code][m4b-ipscore]) | GitHub-releases ([code][igm-version]); `api.ipify.org`, `ifconfig.me` of `icanhazip.com` voor je publieke IP-adres ([code][igm-ifconfig]); `ip-api.com` via gewone HTTP voor IP-scores ([code][igm-ipscore]). De gesloten binary is niet gecontroleerd | Niets gevonden | Niets gevonden | Niets gevonden |

Geen van de projecten stuurt gebruikstelemetrie in de code die we lazen. De gesloten binary van IGM kon niet worden gelezen.

Elk project hier geeft inloggegevens van apps als omgevingsvariabelen aan containers door, en InternetIncome geeft er sommige ook als commandoargumenten mee, dus op de host die de apps draait staan ze als platte tekst in de containerconfiguratie van Docker (`Env` en `Args` in `docker inspect`), leesbaar voor iedereen met toegang tot Docker. De rij "Inloggegevens in rust" beschrijft alleen de opgeslagen kopie.

## Hoe we telden { #how-we-counted }

- **CashPilot.** Diensten in de catalogus met de status active of beta en een Docker-image, zonder GPU-rekenkracht of miningpools mee te tellen. Het getal op deze pagina komt uit `scripts/generate_readme_tables.py`, en CI faalt als het afwijkt.
- **money4band 5.0.0.** Eén JSON-bestand per app in `config/catalog/supported/`: 15. De "35 apps" van de README tellen ook de communitycatalogus mee, die standaard uit staat ([configuratie][m4b-community]), apps zonder Docker-image, en geschrapte apps.
- **IGM.** Vermeldingen in `apps.json`: 20, allemaal ingeschakeld. De proxycontainer, Watchtower en de sidecars voor het claimen zijn niet meegeteld.
- **InternetIncome.** Elk commentaarblok `# Starting ... container` in `internetIncome.sh`, behalve de blokken voor de proxy en Watchtower: 24. De blokken voor Chrome en Firefox van Ebesucher zijn één app, en dat geldt ook voor EarnFM en EarnFM Fleetshare, die hetzelfde EarnFM-account gebruiken. Het blok voor de Depin-extensies start Grass en Gradient ([script][ii-depin]), twee apps. Totaal 23. De tabel in de README noemt 27 apps, sommige alleen met een aanmeldlink.
- **CashFactory.** Verdiendiensten in `docker-compose.yml`: 11. Portainer, de webserver en de twee Watchtowers zijn niet meegeteld. Eén dienst is uitgecommentarieerd.
- **HA-add-ons.** Add-on-mappen met een configuratiebestand: 10.

We hebben niet gecontroleerd of elke app op elke lijst nog uitbetaalt.

## Waar CashPilot achterloopt { #where-cashpilot-is-behind }

- Diensten die hostnetwerk, gepubliceerde poorten, volumes, apparaten of extra netwerkcapabilities nodig hebben, kunnen niet via een proxy draaien, dus 10 van de <!-- n:docker -->21<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi en Kryptex Pool (Pearl)) verdienen alleen vanaf het eigen IP-adres van de server ([proxy-kopieën](proxies.md#what-cannot-run-through-a-proxy)).
- Minder apps die het zelf start dan InternetIncome.
- Geen dagelijkse beloningen claimen en geen automatische image-updates.
- 12 van de <!-- n:docker -->21<!-- /n --> images van verdien-apps bewegen mee met de latest-tag van hun uitgever.
- De socket-proxy is nog geen grens voor root: een gecompromitteerde worker kan nog steeds containers binnen zijn beleid maken, en ontsnappingen in twee stappen (meedoen in de procesnamespace van een andere container, een symlink in een toegestane map) worden niet geweigerd ([details](security-defaults.md)).
- De versleutelingssleutel voor opgeslagen inloggegevens staat in hetzelfde volume als de gegevens, en op elke worker staan de inloggegevens van verdien-apps als platte tekst in de containerconfiguratie van Docker.
- Sommige collectors hebben een cookie of token nodig dat uit de browser is gekopieerd, en sommige daarvan verlopen, dus het volgen van inkomsten vraagt onderhoud voor die diensten.
- De UI laadt lettertypen en Chart.js van CDN's van derden.
- LAN-isolatie blijft uit op een bijgewerkte installatie waarvan de verdien-apps op de standaardbridge van Docker staan, tot je haar aanzet, ze geeft geen afscherming aan een netwerk dat in `CASHPILOT_CONTAINER_NETWORK` is genoemd ([isolatie](isolation.md#modes)), en een Mysterium-node die tot en met 2.0.6 is uitgerold, blijft zonder afscherming op het netwerk van de host tot je hem opnieuw uitrolt ([Mysterium achter de afscherming](mysterium-fence.md)).
- Een veel kleinere community dan die van money4band.
- Het brengt vaak releases uit, soms meerdere keren per dag.

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
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
