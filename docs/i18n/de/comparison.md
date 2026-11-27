---
source_hash: 1a93abea95d7
---
# Wie CashPilot im Vergleich abschneidet { #how-cashpilot-compares }

Diese Seite vergleicht CashPilot mit den anderen offenen Projekten, die mehrere Apps für passives Einkommen in Docker betreiben. Wir haben jedes Projekt am 2026-11-04 geprüft. Jede Zelle zu einem anderen Projekt verlinkt auf die Datei, aus der sie stammt, bei einem festen Commit, damit du es selbst prüfen kannst. Ist eine Zelle falsch oder veraltet, [eröffne bitte ein Issue](https://github.com/GeiserX/CashPilot/issues).

## Verglichene Projekte { #projects-compared }

| Projekt | Was wir geprüft haben | Sterne am 2026-11-04 | Lizenz |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, Tag-Commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` bei `65e900d` (2026-10-20), dazu die Aussagen der README über ihre Binärdatei 3.0.0-beta.9 | 238 | Proprietär, [eigene Lizenz v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` bei `db9338a` (2026-11-03) | 257 | Keine LICENSE-Datei. Die [README][ii-license] erlaubt, das Original zu kopieren, und verbietet, veränderte Kopien zu verbreiten |
| [CashFactory][cf-tree] | `main` bei `0ff4bd0` (2025-04-08) | 410 | Die Datei [LICENSE][cf-license-file] ist GPL-3.0, aber die [README][cf-license] verbietet, veränderte Kopien zu verbreiten |
| [home-assistant-passive-income][ha-tree] (HA-Add-ons) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v1.64.0, `main` bei `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band hat zwei Codelinien. Sein Standard-Branch `main` (`3bfafb1`) enthält noch den 4.x-Code, und die letzte Codeänderung dort war am 2026-03-03. Release 5.0.0 ist aus einer separaten Historie gebaut. Wir vergleichen 5.0.0, weil sein neuestes Release genau das ausliefert.

Die Web-UI, die Flottenverwaltung und die Installer-Binärdatei von IGM sind Closed Source und nicht in seinem Repository. Wo eine Zelle davon abhängt, steht dort „README behauptet“, mit einem Link auf die Zeile der README. Alles andere in der Spalte von IGM stammt aus den Shell-Skripten und Compose-Dateien im Repository.

Weggelassen: [earning-machine](https://github.com/jf-m/earning-machine) und [passiveMachine](https://github.com/Xpl0itU/passiveMachine) haben seit 2024 keine Commits mehr. Eine Suche auf GitHub hat nichts anderes Gepflegtes gefunden, das mehr als eine App betreibt, nur Images für eine einzelne App.

## Kurzfassung { #short-version }

- **InternetIncome, money4band, IGM und seit v1.69.0 CashPilot können über Proxys auf vielen IPs verdienen.** Die ersten drei starten jede App einmal pro Proxy, und Proxys sind die Hauptfunktion von InternetIncome. CashPilot betreibt zusätzliche Kopien eines Dienstes, der bereits auf einem Worker bereitgestellt ist, jede über einen Proxy per SOCKS5, HTTP CONNECT oder Tailscale-Exit-Node ([Proxy-Kopien](proxies.md)).
- **InternetIncome (23) startet mehr Apps als der Worker von CashPilot (<!-- n:docker -->21<!-- /n -->); IGM startet 20.** CashPilot verfolgt insgesamt mehr Dienste (<!-- n:live -->50<!-- /n -->), weil es auch Dienste als Browser-Erweiterung, Desktop-App und GPU-Dienst verfolgt, die es nicht selbst betreibt. Seit v1.64.0 kann es außerdem jedes Image, das du nennst, als [eigenen Dienst](custom-services.md) betreiben.
- **money4band und IGM holen tägliche Belohnungen für dich ab und halten die App-Images mit Watchtower aktuell.** CashPilot tut beides nicht. Es lädt ein Image nur dann erneut, wenn du bereitstellst oder neu bereitstellst.
- **CashPilot ist hier das einzige, das Guthaben aus deinen Anbieterkonten liest und eine Historie führt.** money4band 5.0.0 zeigt Schätzungen aus seinem eigenen Katalog, nicht aus deinen Konten. Die anderen verlinken auf das Dashboard jedes Anbieters.
- **CashPilot ist hier das einzige Open-Source-Projekt mit einer UI für viele Server.** Die README von IGM behauptet eine Flottenverwaltung, aber dieser Code steckt in seiner geschlossenen Binärdatei.
- **Seit v1.70.0 ist CashPilot hier das einzige, das die Container der Verdienst-Apps standardmäßig aus deinem LAN heraushält, mit Einschränkungen.** Das ist bei neuen Installationen eingeschaltet und bei aktualisierten Installationen ohne Verdienst-App auf der Standard-Bridge von Docker. Eine aktualisierte Installation, deren Verdienst-Apps schon auf dieser Bridge sitzen, lässt sie dort, bis du die Isolierung einschaltest, und ein Netzwerk, das du in `CASHPILOT_CONTAINER_NETWORK` nennst, bekommt von CashPilot keine Sperre ([Isolierung](isolation.md#modes)). Seit 2.0.7 läuft auch Mysterium hinter der Sperre; ein Node, der bis 2.0.6 bereitgestellt wurde, bleibt ohne Sperre im Netzwerk des Hosts, bis du ihn neu bereitstellst ([Mysterium hinter der Sperre](mysterium-fence.md)).

## Nebeneinander { #side-by-side }

Die Spalte von CashPilot beschreibt v1.64.0, außer den Zeilen zu Proxy, Docker-Socket und LAN-Isolierung, die v1.71.1 beschreiben (`0170dee`, 2026-11-06), und dem Netzwerk von Mysterium in den Zeilen zu den Container-Einstellungen und zur LAN-Isolierung, das das Release nach 2.0.6 beschreibt (`01e7310`). Die Zeile zu ausgehenden Aufrufen schließt die Explorer-Aufrufe aus der [aktuellen On-Chain-Anleitung](onchain.md) ein. Die anderen Spalten beschreiben die Commits in der Tabelle oben.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA-Add-ons |
|---|---|---|---|---|---|---|
| Apps, die es starten kann (siehe [wie wir gezählt haben](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> betrieben vom Worker, dazu [eigene Images](custom-services.md); <!-- n:live -->50<!-- /n --> insgesamt verfolgt | 15 ([Katalog][m4b-catalog]). Die README sagt 35, was Community-Apps und eingestellte Apps [einschließt][m4b-readme-35] | 20 ([apps.json][igm-apps]) | 23 ([Skript][ii-script]) | 11 ([Compose-Datei][cf-compose]) | 10 ([Add-on-Ordner][ha-tree]) |
| Wie du es installierst | Docker Compose: eine UI plus ein Worker auf jedem Server; der Worker startet die Verdienst-Apps über die Docker-API ([Flotte](fleet.md)) | Python-CLI oder eine fertig gebaute Binärdatei, die eine Compose-Datei schreibt ([Release][m4b-tree]) | Installer per `curl \| sh` ([README][igm-install]), der eine geschlossene Binärdatei herunterlädt, die nur gegen eine SHA256SUMS-Datei aus demselben Release geprüft wird ([Installer][igm-installer-sums]) | Ein einziges Bash-Skript mit 1.608 Zeilen, das `sudo docker run` aufruft ([Skript][ii-script]) | Eine statische Compose-Datei plus `setup.sh`, mit sudo ausgeführt ([Setup][cf-setup]) | Ein Add-on-Repository für Home Assistant; braucht Home Assistant OS oder Supervised |
| Viele Server, eine Ansicht | Ja ([Flotte](fleet.md)) | Nein, ein Stack pro Gerät | README behauptet ja, in der geschlossenen Binärdatei ([README][igm-features]) | Nein | Nein | Nein |
| Viele Proxys oder IPs | Ja, seit v1.69.0: zusätzliche Kopien eines bereitgestellten Dienstes, jede über einen Proxy per SOCKS5, HTTP CONNECT oder Tailscale-Exit-Node. SOCKS5 und HTTP CONNECT tragen nur TCP (der Tunnel lässt nur TCP zum Port des Proxys hinaus, daher werden UDP-Relays von SOCKS5 verworfen); ein Tailscale-Exit-Node trägt auch UDP. Die Verdienst-App teilt den Netzwerk-Namespace eines Tunnel-Containers, dessen Firewall nur Loopback, den Tunnel und die eigene Verbindung des Tunnels zum Proxy hinauslässt (TCP zu dessen Adresse und Port oder die markierten Pakete von tailscaled), daher stoppt ein toter Proxy sie, statt dass etwas durchsickert ([Proxy-Kopien](proxies.md#how-it-works), [Code][cp-proxy-deploy], [Tunnel-Firewall][cp-tunnel-fw]). Dienste, die Host-Netzwerk, veröffentlichte Ports, Volumes, Geräte oder `NET_ADMIN`, `NET_RAW` oder `SYS_ADMIN` brauchen, können nicht über einen Proxy laufen ([Proxy-Kopien](proxies.md#what-cannot-run-through-a-proxy)) | Ja ([README][m4b-features], [Code][m4b-multiproxy]) | Ja ([README][igm-features], [Compose][igm-proxy]) | Ja, seine Hauptfunktion ([README][ii-readme-top]) | Nein | Nein |
| Einnahmen | <!-- n:collectors -->20<!-- /n --> Collectors lesen Guthaben aus Anbieterkonten und führen eine Historie. Manche brauchen ein Cookie oder Token, das du aus deinem Browser kopierst, und manche davon laufen ab (siehe die Anleitung des jeweiligen Dienstes) | Schätzungen aus Spannen im Katalog, keine Kontodaten ([Code][m4b-earnings]) | Keine in den Skripten gefunden | Keine | Keine | Keine |
| Auszahlungen | Schlägt eine Auszahlung vor, wenn ein Guthaben sinkt, und erfasst sie, sobald du sie bestätigst ([Schema][cp-payouts]) | Keine | Keine | Keine | Keine | Keine |
| Tägliche Belohnungen abholen | Nein | Ja, Sidecars ([README][m4b-features]) | Ja ([README][igm-features], [Compose][igm-sidecars]) | Nein | Nein | Nein |
| Zugangsdaten im Ruhezustand | Verschlüsselt (Fernet) in der Datenbank der UI; die Schlüsseldatei liegt im selben Daten-Volume ([Code][cp-fernet]). Die Zugangsdaten der Verdienst-Apps erreichen jeden Worker als Umgebungsvariablen des Containers, daher stehen sie im Klartext in der Docker-Konfiguration dieses Workers (`docker inspect`) | Verschlüsselt (Fernet); die Schlüsseldatei liegt im Datenverzeichnis ([Code][m4b-crypto]) | Verschlüsselt (AES-256 mit openssl); die Schlüsseldatei liegt neben dem Tresor ([Code][igm-encryptor]) | Klartext in `properties.conf`; manche Passwörter werden als Argumente von `docker run` übergeben ([Skript][ii-password-arg]) | Klartext in `.env` ([Datei][cf-env]) | Add-on-Optionen, vom Supervisor in `/data/options.json` gespeichert ([HA-Doku][ha-options]) |
| Container-Einstellungen der Verdienst-Apps | Jede Capability entzogen, dann fügt der Katalog wieder hinzu, was ein Dienst braucht; `no-new-privileges`; ein pids-Limit; privilegiert wird abgelehnt ([Code][cp-hardening], [Code][cp-privileged]). Mysterium läuft in seinem eigenen Netzwerk-Namespace auf der abgesperrten Bridge mit `NET_ADMIN`, `SETUID` und `SETGID`, auf einem per Digest festgelegten Image ([Katalog][cp-myst]) | `no-new-privileges` bei jedem nicht privilegierten Dienst ([Code][m4b-nnp]); der Proxy-Container ist privilegiert mit `NET_ADMIN` ([Vorlage][m4b-tun]) | Bei App-Diensten nichts gesetzt; Mysterium bekommt `NET_ADMIN` ([Compose][igm-hosting-myst]); der Proxy-Container bekommt `NET_ADMIN`, mit `no-new-privileges` und einem pids-Limit ([Compose][igm-proxy]) | Ebesucher läuft mit `seccomp=unconfined` ([Skript][ii-seccomp]); Proxy-Container und Mysterium bekommen `NET_ADMIN` | Nichts gesetzt | Kein Add-on verlangt privilegierten Modus, Host-Netzwerk oder Zugriff auf die Docker-API ([Beispielkonfiguration][ha-config]) |
| Docker-Socket eingebunden in | Seit v1.71.0 einen Socket-Proxy (sockguard 2.4.5, per Digest festgelegt), schreibgeschützt. Der Worker bekommt eine gefilterte Kopie, die privilegierte Container, Bind-Mounts von `/` oder des Sockets sowie Capabilities oder Geräte außerhalb derer des Katalogs ablehnt ([Compose][cp-sock], [Details](security-defaults.md)); nie in eine Verdienst-App ([Code][cp-mounts]) | Watchtower ([Vorlage][m4b-watchtower]) | Watchtower, schreibgeschützt mit `no-new-privileges` ([Compose][igm-watchtower]) | Fünf Hilfscontainer für Neustarts ([Skript][ii-sock-helper]) und Watchtower ([Skript][ii-watchtower]) | Portainer, veröffentlicht auf den Ports 8000, 9000 und 9443 auf allen Schnittstellen ([Compose][cf-portainer]), und zwei Watchtowers ([Compose][cf-watchtower-ps], [Compose][cf-watchtower-efm]) | Keiner |
| Image-Tags | 9 der <!-- n:docker -->21<!-- /n --> Images von Verdienst-Apps sind auf eine Version oder einen Digest festgelegt; der Rest ist beweglich | Alle 15 App-Images verwenden `:latest` ([Beispiel][m4b-image]); Proxy-Container auf v2.6.0 festgelegt, Watchtower auf `:1` | Kein Tag, daher verwendet Docker `latest` ([Compose][igm-hosting]); ein Tag ist nur bei manchen ARM-Builds gesetzt | Meist `:latest` ([Beispiel][ii-seccomp]); EarnApp `:lite`, Honeygain auf 0.6.6 festgelegt, wenn über Proxy auf amd64 ([Skript][ii-honeygain]), Traffmonetizer mit Tags pro Architektur auf ARM; Watchtower `:nightly` | `:latest` oder kein Tag, außer EarnApp `:lite` ([Compose][cf-compose]) | Eine Version pro Add-on, angehoben durch einen täglichen CI-Job ([Workflow][ha-bump], [Beispiel][ha-dockerfile]) |
| Updates der App-Images | Bei jeder Bereitstellung oder neuen Bereitstellung erneut geladen; kein automatischer Updater | Watchtower ([Vorlage][m4b-watchtower]) | Watchtower alle 4 Stunden ([Compose][igm-watchtower]) | Watchtower einmal am Tag, wenn du es einschaltest ([Skript][ii-watchtower]) | Zwei Watchtowers, jeder auf eine App beschränkt, PacketStream ([Compose][cf-watchtower-ps]) und EarnFM ([Compose][cf-watchtower-efm]); die anderen 9 Apps werden nicht aktualisiert | Die Add-on-Updates von Home Assistant |
| LAN-Isolierung | Seit v1.70.0 standardmäßig eingeschaltet bei neuen Installationen und bei aktualisierten Installationen ohne Verdienst-App auf der Standard-Bridge von Docker: Der Worker setzt die Verdienst-Apps auf seine eigene Bridge und schreibt eine Firewall-Tabelle, die private Bereiche, den Tailnet-Bereich, Cloud-Metadaten, die verbundenen Subnetze des Hosts, den Host selbst und, bei eingeschalteter Erkennung der öffentlichen IP, die öffentliche IP des Haushalts verwirft ([Isolierung](isolation.md#lan-isolation-by-default), [Code][cp-fence]). Eine aktualisierte Installation, deren Verdienst-Apps schon auf der Standard-Bridge sitzen, bleibt dort, bis du **Turn on isolation** (Isolierung einschalten) drückst; `CASHPILOT_ISOLATION=off` schaltet sie aus; ist `CASHPILOT_CONTAINER_NETWORK` gesetzt, schreibt CashPilot für dieses Netzwerk keine Sperre, und die Firewall-Regeln sind deine Sache ([Isolierung](isolation.md#modes), [Code][cp-fence-mode]). Seit 2.0.7 ist auch Mysterium abgesperrt; ein Node, der bis 2.0.6 bereitgestellt wurde, bleibt im Netzwerk des Hosts, bis du ihn neu bereitstellst ([Mysterium hinter der Sperre](mysterium-fence.md)). Eine Prüfung zeigt, was Verdienst-Apps erreichen können ([Prüfung](isolation-check.md)) | Eigenes Bridge-Subnetz ([Konfiguration][m4b-subnet]), das das LAN nicht blockiert | Nichts gemergt | Nichts gefunden | Nichts gefunden | Nichts gefunden |
| ARM | arm64-UI und -Worker; prüft vor einer Bereitstellung die Plattformen jedes Dienstes ([ARM](arm.md)) | Binärdateien für arm64 und armv7 ([Release][m4b-release]) | README behauptet amd64 und arm64, arm32 mit Einschränkungen, und richtet QEMU ein ([README][igm-arch]) | Braucht binfmt-Emulation für Images nur für amd64 ([README][ii-arm]) | README sagt, dass es auf einem Raspberry Pi nicht funktioniert ([README][cf-raspberry]) | Je nach Add-on; ProxyRack nur für amd64 ([Konfiguration][ha-proxyrack]) |
| UI | Web-UI, dazu Clients für Desktop, Android, MCP und Home Assistant | CLI, Menüs und ein lokales Web-Dashboard, standardmäßig an 127.0.0.1 gebunden ([Code][m4b-bind]) | CLI, Menüs und laut README eine Web-UI auf Port 4747, im LAN erreichbar ([README][igm-webui]) | Keine, ein Skript | Eine Lesezeichenseite auf Port 80 plus Portainer ([README][cf-ui]) | Das Add-on-Panel von Home Assistant |
| Commits auf dem Standard-Branch, 2026-08-06 bis 2026-11-04 | 286 | 6, alle Doku (5.0.0 liegt in einer separaten Historie) | 6 | 31 | 0 | 23 |
| Neuestes Release | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Keine versionierten Releases | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Ausgehende Aufrufe neben den Apps | GitHub-Releases einmal am Tag (`CASHPILOT_UPDATE_CHECK=off` stoppt das, [Code][cp-update]); `api.ipify.org`, `ifconfig.me` oder `icanhazip.com` einmal pro Stunde von jedem Worker, für seine öffentliche IP (`CASHPILOT_EGRESS_DETECT=off` stoppt das, [Code][cp-egress]); CoinGecko und Frankfurter für Wechselkurse ([Code][cp-rates]); mempool.space, api.kaspa.org und öffentliche RPC-Nodes für Ethereum, Polygon und Solana für [On-Chain-Guthaben](onchain.md); jeder Anbieter, für die Collectors. Der Browser lädt Google Fonts ([Vorlage][cp-cdn]) und Chart.js von jsDelivr ([Vorlage][cp-chartjs]) | GitHub-Releases, für seine Update-Prüfung ([Code][m4b-updater]); Docker Hub und ghcr.io, um Image-Tags zu prüfen ([Code][m4b-registry]); wenn du die IP-Prüfung ausführst, `api.ipify.org`, `ifconfig.me` oder `icanhazip.com` für deine öffentliche IP und `ip-api.com` über einfaches HTTP für IP-Bewertungen ([Code][m4b-ipscore]) | GitHub-Releases ([Code][igm-version]); `api.ipify.org`, `ifconfig.me` oder `icanhazip.com` für deine öffentliche IP ([Code][igm-ifconfig]); `ip-api.com` über einfaches HTTP für IP-Bewertungen ([Code][igm-ipscore]). Die geschlossene Binärdatei wurde nicht geprüft | Nichts gefunden | Nichts gefunden | Nichts gefunden |

Keines der Projekte sendet in dem Code, den wir gelesen haben, Nutzungstelemetrie. Die geschlossene Binärdatei von IGM konnte nicht gelesen werden.

Jedes Projekt hier übergibt die Zugangsdaten der Apps als Umgebungsvariablen an die Container, und InternetIncome übergibt manche zusätzlich als Befehlsargumente, daher stehen sie auf dem Host, der die Apps betreibt, im Klartext in der Container-Konfiguration von Docker (`Env` und `Args` in `docker inspect`), lesbar für jeden mit Docker-Zugriff. Die Zeile „Zugangsdaten im Ruhezustand“ beschreibt nur die gespeicherte Kopie.

## Wie wir gezählt haben { #how-we-counted }

- **CashPilot.** Dienste im Katalog mit dem Status active oder beta und einem Docker-Image, ohne GPU-Rechenleistung und Mining-Pools. Die Zahl auf dieser Seite stammt aus `scripts/generate_readme_tables.py`, und CI schlägt fehl, wenn sie abweicht.
- **money4band 5.0.0.** Eine JSON-Datei pro App in `config/catalog/supported/`: 15. Die „35 apps“ der README zählen auch den Community-Katalog mit, der standardmäßig aus ist ([Konfiguration][m4b-community]), Apps ohne Docker-Image und eingestellte Apps.
- **IGM.** Einträge in `apps.json`: 20, alle aktiviert. Der Proxy-Container, Watchtower und die Sidecars zum Abholen sind nicht mitgezählt.
- **InternetIncome.** Jeder Kommentarblock `# Starting ... container` in `internetIncome.sh`, außer den Blöcken für Proxy und Watchtower: 24. Die Chrome- und Firefox-Blöcke von Ebesucher sind eine App, ebenso EarnFM und EarnFM Fleetshare, die dasselbe EarnFM-Konto verwenden. Der Block für die Depin-Erweiterungen startet Grass und Gradient ([Skript][ii-depin]), zwei Apps. Insgesamt 23. Die Tabelle der README listet 27 Apps, manche nur mit einem Registrierungslink.
- **CashFactory.** Verdienende Dienste in `docker-compose.yml`: 11. Portainer, der Webserver und die beiden Watchtowers sind nicht mitgezählt. Ein Dienst ist auskommentiert.
- **HA-Add-ons.** Add-on-Ordner mit einer Konfigurationsdatei: 10.

Wir haben nicht geprüft, ob jede App auf jeder Liste noch auszahlt.

## Wo CashPilot zurückliegt { #where-cashpilot-is-behind }

- Dienste, die Host-Netzwerk, veröffentlichte Ports, Volumes, Geräte oder zusätzliche Netzwerk-Capabilities brauchen, können nicht über einen Proxy laufen, daher verdienen 10 der <!-- n:docker -->21<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi und Kryptex Pool (Pearl)) nur über die eigene IP des Servers ([Proxy-Kopien](proxies.md#what-cannot-run-through-a-proxy)).
- Weniger Apps, die es selbst startet, als InternetIncome.
- Kein tägliches Abholen von Belohnungen und keine automatischen Image-Updates.
- 12 der <!-- n:docker -->21<!-- /n --> Images von Verdienst-Apps folgen beweglich dem latest-Tag ihres Herausgebers.
- Der Socket-Proxy ist noch keine root-Grenze: Ein kompromittierter Worker kann innerhalb seiner Richtlinie weiterhin Container erstellen, und zweistufige Ausbrüche (Beitritt zum Prozess-Namespace eines anderen Containers, ein Symlink in einem erlaubten Ordner) werden nicht abgelehnt ([Details](security-defaults.md)).
- Der Verschlüsselungsschlüssel für gespeicherte Zugangsdaten liegt im selben Volume wie die Daten, und auf jedem Worker stehen die Zugangsdaten der Verdienst-Apps im Klartext in der Container-Konfiguration von Docker.
- Manche Collectors brauchen ein Cookie oder Token, das aus dem Browser kopiert wird, und manche davon laufen ab, daher braucht die Verfolgung der Einnahmen bei diesen Diensten Pflege.
- Die UI lädt Schriften und Chart.js von CDNs Dritter.
- Die LAN-Isolierung bleibt bei einer aktualisierten Installation, deren Verdienst-Apps auf der Standard-Bridge von Docker sitzen, aus, bis du sie einschaltest; sie gibt einem in `CASHPILOT_CONTAINER_NETWORK` genannten Netzwerk keine Sperre ([Isolierung](isolation.md#modes)), und ein Mysterium-Node, der bis 2.0.6 bereitgestellt wurde, bleibt ohne Sperre im Netzwerk des Hosts, bis du ihn neu bereitstellst ([Mysterium hinter der Sperre](mysterium-fence.md)).
- Eine viel kleinere Community als die von money4band.
- Es veröffentlicht oft Releases, manchmal mehrmals am Tag.

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
