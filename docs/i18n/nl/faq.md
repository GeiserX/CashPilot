---
source_hash: 915470497dbc
---
# Veelgestelde vragen { #faq }

**Is bandbreedte delen veilig?**

Diensten voor het delen van bandbreedte sturen over het algemeen legitiem verkeer (marktonderzoek, advertentiecontrole, prijsvergelijking, contentlevering) via je verbinding. Toch deel je je IP-adres, dus lees de gebruiksvoorwaarden en het privacybeleid van elke dienst zorgvuldig voordat je je aanmeldt. Voor sommige diensten is het een optie om ze op een VPS te draaien in plaats van op een residentieel IP-adres. **Dit is geen juridisch advies -- raadpleeg de diensten die je wilt gebruiken en zoek zo nodig onafhankelijk juridisch advies voor jouw rechtsgebied.**

**Hoeveel kan ik verdienen?**

De inkomsten lopen sterk uiteen, afhankelijk van locatie, internetprovider, aantal apparaten en welke diensten je draait. Het dashboard volgt je werkelijke inkomsten in de tijd, zodat je je opstelling kunt optimaliseren. Als ruwe richtlijn, en geen belofte: één thuisserver met 10 tot 15 diensten brengt ongeveer $30 tot $100 per maand op, en het kan minder zijn, tot nul. Meer servers, of GPU-rekenkracht, komen daarbovenop.

**Kan ik het op een VPS of cloudserver draaien?**

Sommige diensten vereisen een residentieel IP-adres en betalen niet voor IP-adressen van een VPS of datacenter (of blokkeren ze). De catalogus vermeldt "residentieel IP-adres" bij wat ze nodig hebben. Diensten die op een VPS werken, zijn een goede manier om op te schalen zonder extra hardware thuis.

**Hoe worden inloggegevens opgeslagen?**

Alle inloggegevens van diensten zijn in rust versleuteld in de SQLite-database met een Fernet-sleutel in `/data/.fernet_key`, die bij de eerste start automatisch wordt gemaakt. Het databasebestand staat in het gemounte Docker-volume (`cashpilot_data:/data`). Inloggegevens worden nooit ergens anders heen gestuurd dan naar de dienstcontainers zelf.

Let op: dit is een andere sleutel dan `CASHPILOT_SECRET_KEY`, die alleen inlogsessies ondertekent.

### Back-up van de versleutelingssleutel { #backing-up-the-encryption-key }

Je inloggegevens zijn maar zo herstelbaar als `/data/.fernet_key`. Verlies je dat bestand, dan moet je alle inloggegevens opnieuw invoeren, want zonder dat bestand zijn de opgeslagen waarden op geen enkele manier te ontsleutelen.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Het bestand gaat altijd voor op de omgevingsvariabele, dus `CASHPILOT_ENCRYPTION_KEY` instellen op een installatie die al een sleutel heeft, verandert niets en is veilig. De variabele wordt alleen overgenomen als er geen sleutelbestand bestaat, en dat is precies het geval bij het terugzetten.

Kan CashPilot de sleutel helemaal niet naar de schijf schrijven, omdat `/data` niet beschrijfbaar of niet gemount is, dan weigert het te starten, in plaats van je inloggegevens te versleutelen met een sleutel die bij de volgende herstart verdwijnt. Stel `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` in als je dat echt wilt.

<a id="forgot-password"></a>

### Wachtwoord of gebruikersnaam vergeten { #forgot-password-or-username }

CashPilot heeft geen herstel via e-mail. Wie de server beheert, zet het wachtwoord opnieuw in via de console van de CashPilot-UI-container. Je diensten, inkomsten en opgeslagen inloggegevens blijven onaangetast: die zijn versleuteld met `/data/.fernet_key`, niet met je wachtwoord.

Het commando `python -m app.users` vereist CashPilot 2.3 of nieuwer. Op 2.2 of ouder mislukt het met `No module named app.users`. Werk eerst bij: zet met Docker Compose de tags van `drumsergio/cashpilot` en `drumsergio/cashpilot-worker` op `2.3` of nieuwer (een pin zoals `2.2` of `2.2.9` blijft op die release), en voer daarna `docker compose up -d` uit ([CashPilot bijwerken](getting-started.md#updating-cashpilot)). Werk op Unraid de container bij.

1. Toon de accounts. Zo zie je ook een gebruikersnaam die je vergeten bent. Gebruikersnamen zijn hoofdlettergevoelig.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Stel een nieuw willekeurig wachtwoord in voor het account. Vervang `alice` door de gebruikersnaam uit stap 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Met precies één eigenaar kun je de gebruikersnaam weglaten, en zet het commando het wachtwoord van die eigenaar opnieuw in. Begint de gebruikersnaam met `-`, zet er dan `--` voor: `reset-password -- -alice`.

    Het commando toont het nieuwe wachtwoord één keer.

3. Kan iemand anders toegang tot het account hebben gehad, herstart de UI-container dan nu (`docker restart cashpilot-ui`). Browsers die nog als die gebruiker waren ingelogd, worden pas na een herstart uitgelogd. Ben je alleen het wachtwoord vergeten, dan is de herstart optioneel.
4. Log in met het nieuwe wachtwoord en wijzig het daarna via het avatarmenu (rechtsboven), **Change password** (Wachtwoord wijzigen).

De containernaam hangt af van hoe je CashPilot hebt geïnstalleerd:

| Installatie | UI-container |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | een gegenereerde naam; `docker ps` toont hem |

Portainer, Unraid en CasaOS hebben ook een consoleknop voor een container. Het commando heeft geen invoer van de terminal nodig, dus het werkt daar ook.

Een gebruikersnaam wijzigen:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

De nieuwe naam volgt de regel voor registratie: 3 tot 32 letters, cijfers, `_` of `-`. Log uit en weer in om hem te zien.

**Na een vermoedelijke inbraak**, bijvoorbeeld een verloren back-up met `/data/.secret_key` erin, is alleen het wachtwoord opnieuw instellen niet genoeg. Wie die sleutel heeft, kan een geldige inlogcookie ondertekenen, en een nieuw wachtwoord houdt dat niet tegen. Vervang de sleutel en herstart daarna de UI-container. De `&&` herstart hem alleen als de nieuwe sleutel er staat; toont het commando een fout, los die dan eerst op:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Na de herstart is elke browser uitgelogd, en logt iedereen opnieuw in met zijn wachtwoord. Opgeslagen inloggegevens blijven onaangetast. Heb je `CASHPILOT_SECRET_KEY` zelf ingesteld, dan weigert het commando: zet dan een nieuwe willekeurige waarde in die variabele en maak de container opnieuw. Een `docker run` vanuit de image ziet die variabele niet en kan niet weigeren, dus gebruik `docker exec` op de UI-container.

Een nieuwe sleutel maakt een einde aan vervalste cookies, maar niet aan wat de aanvaller deed terwijl hij binnen was. Nog twee stappen:

1. Voer `docker exec cashpilot-ui python -m app.users list` uit. Verwijder elk account dat je niet herkent via het dashboard.
2. Bevatte de verloren kopie heel `/data`, wijzig dan de wachtwoorden van je accounts bij de aanbieders. `.fernet_key` en `cashpilot.db` samen ontsleutelen alle opgeslagen inloggegevens.

Zet je later een back-up terug die vóór de vervanging is gemaakt, laat dan zijn `.secret_key` weg ([Back-up en herstel](backup-restore.md#restore)), of vervang de sleutel en herstart opnieuw. Anders komt de oude sleutel terug. De teruggezette database brengt ook de accounts en wachtwoorden terug die erin stonden, dus herhaal de controle van de accounts en het eventuele opnieuw instellen van wachtwoorden.

**Start de UI-container niet**, voer het commando dan uit vanuit dezelfde image op dezelfde gegevens. Zoek eerst de hostmap die de `/data` van de UI bevat. Dit werkt voor een gestopte container, en zowel voor een benoemd volume als voor een bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Mount daarna die map en gebruik de image-tag die je draait:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Controleer of de lijst je accounts toont, en voer daarna dezelfde regel uit met `reset-password alice` in plaats van `list`.

Een pad zonder database geeft een foutmelding "no database", en het commando maakt of wijzigt daar niets. Docker kan toch een lege map of een leeg volume met die naam achterlaten; verwijder dat.

Verwijder het datavolume **niet**: dat wist `/data/.fernet_key` en daarmee alle opgeslagen inloggegevens. Verwijder ook **geen** rijen uit de tabel `users`.

**Hoe verwijder ik CashPilot volledig?**

`docker compose down -v` verwijdert alleen de eigen containers van CashPilot. De diensten die het uitrolde, blijven draaien, en hun gegevens, het afgeschermde netwerk en een firewalltabel blijven staan. [CashPilot volledig verwijderen](uninstall.md) verwijdert alles, zegt wat voorgoed verloren gaat en laat zien hoe je controleert dat er niets over is.

**Hoe zit het met de beveiliging?**

Elke dienst die CashPilot uitrolt, draait in een eigen container met alle Linux-capabilities verwijderd (een paar diensten voegen alleen de capabilities terug die ze opgeven) en met `--security-opt no-new-privileges`, zodat een proces erin geen extra rechten kan krijgen. Containers zien niets van je hostbestandssysteem buiten de volumes die een dienst opgeeft. Op een nieuwe installatie schermt de worker ze ook af van je LAN, de host, je tailnet en cloudmetadata, zodat ze het internet bereiken en niets lokaals ([Netwerkisolatie](isolation.md)). Op Podman is de afscherming niet beschikbaar: verdien-apps draaien op het standaardnetwerk van Podman, dat je LAN kan bereiken, en de pagina **Fleet** (Vloot) zegt dat ([Netwerkisolatie](isolation.md) noemt de opties). Een installatie die is bijgewerkt vanaf een release van vóór 1.70 houdt zijn verdien-apps op de standaardbridge van Docker, die je LAN kan bereiken, tot je op de pagina **Fleet** (Vloot) op **Turn on isolation** (Isolatie inschakelen) klikt. Sinds 2.0.7 draait Mysterium ook achter de afscherming; een node die tot en met 2.0.6 is uitgerold, blijft op het netwerk van de host tot je hem opnieuw uitrolt ([Je Mysterium-node achter de afscherming zetten](mysterium-fence.md)). [Je thuisnetwerk beschermen](home-network-security.md) beschrijft in plaats daarvan hoe je je eigen bridge met een firewall afschermt. De inloggegevens van diensten zijn in rust versleuteld met symmetrische Fernet-versleuteling. De UI heeft geen toegang tot Docker. Met de meegeleverde compose-bestanden krijgt de worker nooit de kale Docker-socket: hij bereikt Docker via `cashpilot-socket-proxy`, die geprivilegieerde containers en binds van `/` of van de socket weigert (tenzij je een daarvan, of een map boven de socket, in `CASHPILOT_PROXY_BIND_MOUNTS` of `CASHPILOT_COMPOSE_DIR` zet: die neemt de proxy zoals ze zijn), en die de worker beperkt tot containers, volumes en netwerken met zijn eigenaarslabel ([standaard beveiligingsinstellingen](security-defaults.md)). De Unraid-templates en de TrueNAS-app mounten nog steeds de kale socket in de worker, en dat is root op de host ([app stores](app-stores.md)).

Toch is geen enkele opstelling waterdicht. Je draait nog steeds software van derden die extern verkeer via je netwerk stuurt. Isolatie met Docker verkleint het aanvalsoppervlak aanzienlijk vergeleken met het rechtstreeks draaien van deze diensten op je host, maar haalt niet elk risico weg. We raden aan CashPilot op een eigen machine of VLAN te draaien, Docker en het besturingssysteem van je host bijgewerkt te houden, en de opensourcecode van elke dienst te bekijken voordat je hem uitrolt.

**Wat gebeurt er als een dienstcontainer crasht?**

CashPilot bewaakt de gezondheid van containers voortdurend. Stopt een dienstcontainer onverwacht, dan wordt hij automatisch herstart. Het dashboard toont de uptime en de gezondheidsstatus van elke draaiende dienst.

**Mijn Mysterium-node start niet na opnieuw uitrollen. Waarom?**

De meest voorkomende oorzaak is een poort in zijn UDP-bereik die een ander programma op de host al bezet houdt. Docker moet elke poort in het bereik reserveren, dus één bezette poort houdt de start tegen. [Het UDP-poortbereik kiezen](mysterium-fence.md#choosing-the-udp-port-range) legt uit hoe je een bereik kiest dat vrij blijft.

**Mijn proxy-kopie draait maar verdient niets. Waarom?**

De proxy weigert misschien verbinding te maken met de servers van die verdien-app, of staat alleen de poorten 80 en 443 toe. De **Test** (Testen) van CashPilot controleert alleen of de proxy het internet bereikt. [De servers van een verdien-app via de proxy testen](proxies.md#probe-an-earners-servers-through-the-proxy) laat zien hoe je de eigen host en poort van de verdien-app controleert.

**Welke diensten zijn zwaar, en waar moeten ze draaien?**

Opslagnodes, relays en VPN-exits, en GPU-werk gebruiken het meest. [Een kleine machine budgetteren](fleet.md#budgeting-a-small-box) noemt ze en laat zien hoe je elke container meet voordat je beslist.

<a id="worker-lost-docker"></a>

### De worker verloor Docker na een Docker-update { #the-worker-lost-docker-after-a-docker-update }

**Wat je ziet.** De worker blijft online op de pagina **Fleet** (Vloot), maar CashPilot kan zijn containers niet starten, stoppen of bijwerken. De pagina **Fleet** (Vloot) toont **Docker unreachable** (Docker onbereikbaar) naast de worker. Na 10 minuten faalt de healthcheck van de worker (`docker ps` toont de worker als `unhealthy`). Na 30 minuten melden de bel en je meldingen dat de worker Docker niet kan bereiken. `docker logs cashpilot-socket-proxy` toont `upstream Docker socket unreachable`, en met een actueel compose-bestand toont `docker ps` de proxy binnen ongeveer 3 minuten als `unhealthy`. Je verdien-apps blijven draaien.

**Oorzaak.** De meegeleverde compose-bestanden binden het socketbestand `/var/run/docker.sock` in `cashpilot-socket-proxy`. Een bind van een bestand houdt dat ene bestand vast. Een Docker-update (bijvoorbeeld `unattended-upgrades` die een nieuwe `docker-ce` installeert) herstart Docker, en Docker maakt een nieuw socketbestand op hetzelfde pad. Met live-restore van Docker aan blijft de proxy door die herstart heen draaien en houdt hij het oude bestand vast. Op het oude bestand antwoordt niets.

**Snelle oplossing.** Herstart op die machine de proxy:

```bash
docker restart cashpilot-socket-proxy
```

De herstart bindt de nieuwe socket, en de worker vindt Docker terug bij zijn volgende levenssignaal. Je hoeft de worker niet te herstarten. Op Unraid en TrueNAS houdt de worker de socket zelf vast, dus herstart daar de worker.

**Blijvende oplossing.** Bind de map van de socket, niet het socketbestand. Een bind van een map toont een vervangen socket meteen. Vervang in de dienst `cashpilot-socket-proxy` van je compose-bestand de regel `- /var/run/docker.sock:/var/run/docker.sock:ro` door de bind hieronder, en voeg de regel `SOCKGUARD_UPSTREAM_SOCKET` toe aan zijn `environment`:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Voer daarna `docker compose up -d` uit. Dezelfde wijziging werkt in `docker-compose.worker.yml` en `docker-compose.fleet.yml`. Compose leest die bestanden alleen als je ze noemt, dus voer `docker compose -f docker-compose.worker.yml up -d` of `docker compose -f docker-compose.fleet.yml up -d` uit, tenzij `COMPOSE_FILE` het bestand al noemt.

- `recursive: disabled` is noodzakelijk. `/var/run` bevat andere mounts, bijvoorbeeld de netwerknamespaces van Docker onder `/run/docker/netns` en `/run/user/...`. Een recursieve bind haalt ze allemaal in de proxy. Een niet-recursieve bind toont alleen de map zelf.
- `SOCKGUARD_UPSTREAM_SOCKET` stuurt de proxy naar het nieuwe pad. Het beleidsblok en zijn vingerafdruk blijven zoals ze zijn, omdat de omgevingsvariabele `upstream.socket` in het beleid overschrijft. Zonder de variabele start de proxy niet (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` kan zijn bind van het bestand houden. Hij start bij elke `docker compose up` opnieuw, dus hij krijgt altijd de actuele socket. Geef je hem dezelfde bind van de map, voeg dan `DOCKER_HOST=unix:///host-run/docker.sock` toe aan zijn `environment`. Worker 2.8.4 en nieuwer lezen die variabele. Laat hem nooit naar de socket van de proxy wijzen: de migrator heeft die van de host zelf nodig.
- De bind van de map geeft de proxy elke socket in `/var/run`, niet alleen die van Docker. Op een gewone server horen daar de eigen socket van systemd, D-Bus en de sockets van tools zoals Tailscale of snapd bij. `read_only` houdt een programma niet tegen om met een socket te verbinden, en de proxy draait als root. Toegang tot de Docker-socket geeft al root op de host, dus een gecompromitteerde proxy wint weinig wat hij nog niet had. Wil je dat de proxy alleen de Docker-socket vasthoudt, houd dan de bind van het bestand en herstart de proxy na een Docker-update: de melding hierboven vertelt je wanneer.
- Het vereist Docker Compose 2.30.0 of nieuwer. Oudere releases weigeren het hele bestand met `Additional property recursive is not allowed`. Voer `docker compose version` uit om dat te controleren. Debian 13 levert Compose 2.26.1 mee, dus installeer Compose op Debian uit de eigen repository van Docker. De update in de app gebruikt zijn eigen Compose 2.33, dus die leest het gewijzigde bestand.
- Het werkt alleen op Linux. Docker Desktop op macOS en Windows koppelt alleen `/var/run/docker.sock` aan zijn virtuele machine. Daar is `/var/run` een map op je Mac of pc, zonder Docker-socket erin.
- Met rootless Docker staat de socket in `/run/user/<your uid>`, en dat is een aparte mount. Gebruik die map als `source`.
- Houd op Podman de bind van het bestand. De bind van de map hebben we daar niet getest.

De meegeleverde bestanden houden de bind van het bestand, omdat de bind van de map Compose 2.30 en Linux vereist, en CashPilot ook oudere Compose-releases en Docker Desktop ondersteunt. Een nieuwer compose-bestand dat je downloadt, heeft jouw wijziging niet, dus breng die opnieuw aan nadat je het bestand hebt vervangen.
