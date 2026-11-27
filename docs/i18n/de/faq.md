---
source_hash: 915470497dbc
---
# FAQ { #faq }

**Ist das Teilen von Bandbreite sicher?**

Dienste zum Teilen von Bandbreite leiten in der Regel legitimen Verkehr (Marktforschung, Anzeigenprüfung, Preisvergleiche, Auslieferung von Inhalten) über deine Verbindung. Trotzdem teilst du deine IP-Adresse, lies also die Nutzungsbedingungen und die Datenschutzerklärung jedes Dienstes sorgfältig, bevor du dich registrierst. Bei manchen Diensten ist es eine Option, sie auf einem VPS statt mit einer Residential-IP zu betreiben. **Das ist keine Rechtsberatung -- wende dich an die Dienste, die du nutzen willst, und hol dir bei Bedarf unabhängigen Rechtsrat für deine Rechtsordnung.**

**Wie viel kann ich verdienen?**

Die Einnahmen schwanken stark je nach Standort, Internetanbieter, Anzahl der Geräte und den Diensten, die du betreibst. Das Dashboard verfolgt deine tatsächlichen Einnahmen über die Zeit, damit du deine Einrichtung optimieren kannst. Als grobe Orientierung, nicht als Versprechen: Ein Heimserver mit 10 bis 15 Diensten bringt etwa $30 bis $100 im Monat, und es kann weniger sein, bis hin zu null. Mehr Server oder GPU-Rechenleistung kommen noch hinzu.

**Kann ich das auf einem VPS oder Cloud-Server betreiben?**

Manche Dienste verlangen eine Residential-IP und zahlen nicht für VPS- oder Rechenzentrums-IPs (oder sperren sie). Der Katalog führt „Residential-IP“ unter dem auf, was sie brauchen. Dienste, die auf einem VPS funktionieren, sind ein guter Weg, ohne zusätzliche Hardware zu Hause zu wachsen.

**Wie werden Zugangsdaten gespeichert?**

Alle Zugangsdaten der Dienste sind im Ruhezustand in der SQLite-Datenbank verschlüsselt, mit einem Fernet-Schlüssel unter `/data/.fernet_key`, der beim ersten Start automatisch erzeugt wird. Die Datenbankdatei liegt im eingebundenen Docker-Volume (`cashpilot_data:/data`). Zugangsdaten werden nirgendwohin gesendet außer an die Container der Dienste selbst.

Beachte, dass das ein anderer Schlüssel ist als `CASHPILOT_SECRET_KEY`, der nur Anmeldesitzungen signiert.

### Den Verschlüsselungsschlüssel sichern { #backing-up-the-encryption-key }

Deine Zugangsdaten sind nur so wiederherstellbar wie `/data/.fernet_key`. Verlierst du diese Datei, musst du jede Zugangsangabe neu eingeben, denn ohne sie lassen sich die gespeicherten Werte nicht entschlüsseln.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Die Datei hat immer Vorrang vor der Umgebungsvariable, daher ändert das Setzen von `CASHPILOT_ENCRYPTION_KEY` bei einer Instanz, die schon einen Schlüssel hat, nichts und ist sicher. Die Variable wird nur übernommen, wenn keine Schlüsseldatei existiert, und genau das ist der Fall bei einer Wiederherstellung.

Kann CashPilot den Schlüssel überhaupt nicht auf die Festplatte schreiben, weil `/data` nicht beschreibbar oder nicht eingebunden ist, verweigert es den Start, statt deine Zugangsdaten mit einem Schlüssel zu verschlüsseln, der beim nächsten Neustart verschwindet. Setze `CASHPILOT_ALLOW_EPHEMERAL_KEY=true`, wenn du genau das wirklich willst.

<a id="forgot-password"></a>

### Passwort oder Benutzername vergessen { #forgot-password-or-username }

CashPilot hat keine Rücksetzung per E-Mail. Wer den Server betreibt, setzt das Passwort über die Konsole des UI-Containers von CashPilot zurück. Deine Dienste, Einnahmen und gespeicherten Zugangsdaten sind davon nicht betroffen: Sie sind mit `/data/.fernet_key` verschlüsselt, nicht mit deinem Passwort.

Der Befehl `python -m app.users` braucht CashPilot 2.3 oder neuer. Unter 2.2 oder älter scheitert er mit `No module named app.users`. Aktualisiere zuerst: Ändere bei Docker Compose die Tags von `drumsergio/cashpilot` und `drumsergio/cashpilot-worker` auf `2.3` oder neuer (eine Festlegung wie `2.2` oder `2.2.9` bleibt auf diesem Release) und führe dann `docker compose up -d` aus ([CashPilot aktualisieren](getting-started.md#updating-cashpilot)). Unter Unraid aktualisierst du den Container.

1. Liste die Konten auf. Das zeigt auch einen Benutzernamen, den du vergessen hast. Bei Benutzernamen wird zwischen Groß- und Kleinschreibung unterschieden.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Setze ein neues zufälliges Passwort für das Konto. Ersetze `alice` durch den Benutzernamen aus Schritt 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Gibt es genau einen Eigentümer, kannst du den Benutzernamen weglassen, und der Befehl setzt diesen Eigentümer zurück. Beginnt der Benutzername mit `-`, setze `--` davor: `reset-password -- -alice`.

    Der Befehl gibt das neue Passwort einmal aus.

3. Wenn jemand anderes Zugriff auf das Konto gehabt haben könnte, starte jetzt den UI-Container neu (`docker restart cashpilot-ui`). Browser, die noch als dieser Benutzer angemeldet waren, werden erst nach einem Neustart abgemeldet. Hast du nur das Passwort vergessen, ist der Neustart optional.
4. Melde dich mit dem neuen Passwort an und ändere es dann über das Avatar-Menü (oben rechts), **Change password** (Passwort ändern).

Der Name des Containers hängt davon ab, wie du CashPilot installiert hast:

| Installation | UI-Container |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | ein erzeugter Name; `docker ps` zeigt ihn |

Portainer, Unraid und CasaOS haben auch eine Konsolen-Schaltfläche für einen Container. Der Befehl braucht keine Eingabe im Terminal, daher funktioniert er auch dort.

Um einen Benutzernamen zu ändern:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Der neue Name folgt der Regel für die Registrierung: 3 bis 32 Buchstaben, Ziffern, `_` oder `-`. Melde dich ab und wieder an, um ihn zu sehen.

**Nach einer vermuteten Kompromittierung**, zum Beispiel einer verlorenen Sicherung, die `/data/.secret_key` enthält, reicht eine Passwortrücksetzung allein nicht. Wer diesen Schlüssel hat, kann ein gültiges Anmelde-Cookie signieren, und eine Rücksetzung hält das nicht auf. Ersetze den Schlüssel und starte dann den UI-Container neu. Das `&&` startet ihn nur neu, wenn der neue Schlüssel an seinem Platz ist; gibt der Befehl einen Fehler aus, behebe zuerst diesen:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Nach dem Neustart ist jeder Browser abgemeldet, und alle melden sich mit ihrem Passwort neu an. Gespeicherte Zugangsdaten sind nicht betroffen. Hast du `CASHPILOT_SECRET_KEY` selbst gesetzt, verweigert der Befehl die Arbeit: Setze stattdessen einen neuen zufälligen Wert in diese Variable und erstelle den Container neu. Ein `docker run` aus dem Image sieht diese Variable nicht und kann nicht verweigern, verwende also `docker exec` auf dem UI-Container.

Ein neuer Schlüssel beendet gefälschte Cookies, aber nicht das, was der Angreifer getan hat, während er drin war. Zwei weitere Schritte:

1. Führe `docker exec cashpilot-ui python -m app.users list` aus. Lösche über das Dashboard jedes Konto, das du nicht erkennst.
2. Enthielt die verlorene Kopie das ganze `/data`, ändere die Passwörter deiner Konten bei den Anbietern. `.fernet_key` und `cashpilot.db` zusammen entschlüsseln alle gespeicherten Zugangsdaten.

Stellst du später eine Sicherung von vor dem Schlüsselwechsel wieder her, lass ihre `.secret_key` weg ([Sicherung und Wiederherstellung](backup-restore.md#restore)) oder wechsle den Schlüssel und starte erneut neu. Sonst kommt der alte Schlüssel zurück. Die wiederhergestellte Datenbank bringt außerdem die Konten und Passwörter zurück, die sie enthielt, wiederhole also die Kontoprüfung und jede Passwortrücksetzung.

**Startet der UI-Container nicht**, führe den Befehl aus demselben Image gegen dieselben Daten aus. Finde zuerst den Host-Ordner, der das `/data` der UI enthält. Das funktioniert bei einem gestoppten Container, und bei einem benannten Volume ebenso wie bei einem Bind-Mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Binde dann diesen Ordner ein und verwende das Image-Tag, das du betreibst:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Prüfe, dass die Liste deine Konten zeigt, und führe dann dieselbe Zeile mit `reset-password alice` anstelle von `list` aus.

Ein Pfad ohne Datenbank führt zu einem Fehler „no database“, und der Befehl legt dort nichts an und ändert nichts. Docker kann trotzdem einen leeren Ordner oder ein leeres Volume mit diesem Namen zurücklassen; entferne es.

Lösche das Daten-Volume **nicht**: Das löscht `/data/.fernet_key` und damit alle gespeicherten Zugangsdaten. Lösche auch **keine** Zeilen aus der Tabelle `users`.

**Wie entferne ich CashPilot vollständig?**

`docker compose down -v` entfernt nur die eigenen Container von CashPilot. Die Dienste, die es bereitgestellt hat, laufen weiter, und ihre Daten, das abgesperrte Netzwerk und eine Firewall-Tabelle bleiben. [CashPilot vollständig entfernen](uninstall.md) entfernt alles davon, sagt, was endgültig verloren geht, und zeigt, wie du prüfst, dass nichts übrig ist.

**Wie steht es um die Sicherheit?**

Jeder Dienst, den CashPilot bereitstellt, läuft in seinem eigenen Container, ohne jede Linux-Capability (einige Dienste fügen nur die wieder hinzu, die sie angeben) und mit gesetztem `--security-opt no-new-privileges`, sodass ein Prozess darin keine Rechte hinzugewinnen kann. Container sehen dein Host-Dateisystem nicht über die Volumes hinaus, die ein Dienst angibt. Bei einer neuen Installation sperrt der Worker sie außerdem von deinem LAN, dem Host, deinem Tailnet und Cloud-Metadaten ab, sodass sie das Internet erreichen und nichts Lokales ([Netzwerkisolierung](isolation.md)). Unter Podman ist die Sperre nicht verfügbar: Verdienst-Apps laufen im Standardnetzwerk von Podman, das dein LAN erreichen kann, und die Seite **Fleet** (Flotte) sagt das ([Netzwerkisolierung](isolation.md) listet die Möglichkeiten auf). Eine Installation, die von einem Release vor 1.70 aktualisiert wurde, lässt ihre Verdienst-Apps auf der Standard-Bridge von Docker, die dein LAN erreichen kann, bis du auf der Seite **Fleet** (Flotte) auf **Turn on isolation** (Isolierung einschalten) klickst. Seit 2.0.7 läuft auch Mysterium hinter der Sperre; ein Node, der bis 2.0.6 bereitgestellt wurde, bleibt im Netzwerk des Hosts, bis du ihn neu bereitstellst ([Deinen Mysterium-Node hinter die Sperre verlegen](mysterium-fence.md)). [Dein Heimnetz schützen](home-network-security.md) beschreibt stattdessen, wie du deine eigene Bridge per Firewall absicherst. Die Zugangsdaten der Dienste sind im Ruhezustand mit symmetrischer Fernet-Verschlüsselung verschlüsselt. Die UI hat keinen Docker-Zugriff. Mit den mitgelieferten Compose-Dateien bekommt der Worker nie den rohen Docker-Socket: Er erreicht Docker über `cashpilot-socket-proxy`, der privilegierte Container und Bind-Mounts von `/` oder des Sockets ablehnt (außer du trägst einen davon oder einen Ordner oberhalb des Sockets in `CASHPILOT_PROXY_BIND_MOUNTS` oder `CASHPILOT_COMPOSE_DIR` ein: Diese nimmt der Proxy als gegeben hin) und den Worker auf Container, Volumes und Netzwerke mit seinem Eigentümer-Label beschränkt ([Sicherheitsvoreinstellungen](security-defaults.md)). Die Unraid-Vorlagen und die TrueNAS-App binden weiterhin den rohen Socket in den Worker ein, und das ist root auf dem Host ([App-Stores](app-stores.md)).

Trotzdem ist keine Einrichtung absolut sicher. Du betreibst weiterhin Software von Dritten, die fremden Verkehr über dein Netzwerk leitet. Die Docker-Isolierung verkleinert die Angriffsfläche deutlich im Vergleich dazu, diese Dienste direkt auf deinem Host zu betreiben, beseitigt aber nicht jedes Risiko. Wir empfehlen, CashPilot auf einem eigenen Rechner oder in einem eigenen VLAN zu betreiben, Docker und das Betriebssystem deines Hosts aktuell zu halten und den Open-Source-Code jedes Dienstes vor der Bereitstellung zu prüfen.

**Was passiert, wenn der Container eines Dienstes abstürzt?**

CashPilot überwacht den Zustand der Container laufend. Beendet sich der Container eines Dienstes unerwartet, wird er automatisch neu gestartet. Das Dashboard zeigt Laufzeit und Zustand jedes laufenden Dienstes.

**Mein Mysterium-Node startet nach einer neuen Bereitstellung nicht. Warum?**

Die häufigste Ursache ist ein Port in seinem UDP-Bereich, den ein anderes Programm auf dem Host schon belegt. Docker muss jeden Port im Bereich reservieren, daher verhindert ein einziger belegter Port den Start. [Den UDP-Portbereich wählen](mysterium-fence.md#choosing-the-udp-port-range) erklärt, wie du einen Bereich wählst, der frei bleibt.

**Meine Proxy-Kopie läuft, verdient aber nichts. Warum?**

Der Proxy verweigert vielleicht die Verbindung zu den Servern dieser Verdienst-App oder erlaubt nur die Ports 80 und 443. **Test** (Testen) in CashPilot prüft nur, dass der Proxy das Internet erreicht. [Die Server einer Verdienst-App über den Proxy prüfen](proxies.md#probe-an-earners-servers-through-the-proxy) zeigt, wie du den eigenen Host und Port der Verdienst-App prüfst.

**Welche Dienste sind schwer, und wo sollten sie laufen?**

Speicher-Nodes, Relays und VPN-Exits sowie GPU-Arbeit brauchen am meisten. [Einen kleinen Rechner einplanen](fleet.md#budgeting-a-small-box) listet sie auf und zeigt, wie du jeden Container misst, bevor du dich entscheidest.

<a id="worker-lost-docker"></a>

### Der Worker hat nach einem Docker-Update den Zugang zu Docker verloren { #the-worker-lost-docker-after-a-docker-update }

**Was du siehst.** Der Worker bleibt auf der Seite **Fleet** (Flotte) online, aber CashPilot kann seine Container nicht starten, stoppen oder aktualisieren. Die Seite **Fleet** (Flotte) zeigt neben dem Worker **Docker unreachable** (Docker nicht erreichbar). Nach 10 Minuten schlägt der Healthcheck des Workers fehl (`docker ps` zeigt den Worker als `unhealthy`). Nach 30 Minuten melden die Glocke und deine Benachrichtigungen, dass der Worker Docker nicht erreichen kann. `docker logs cashpilot-socket-proxy` zeigt `upstream Docker socket unreachable`, und mit einer aktuellen Compose-Datei zeigt `docker ps` den Proxy innerhalb von etwa 3 Minuten als `unhealthy`. Deine Verdienst-Apps laufen weiter.

**Ursache.** Die mitgelieferten Compose-Dateien binden die Socket-Datei `/var/run/docker.sock` in `cashpilot-socket-proxy` ein. Ein Datei-Bind hält genau diese eine Datei. Ein Docker-Update (zum Beispiel `unattended-upgrades`, das ein neues `docker-ce` installiert) startet Docker neu, und Docker legt eine neue Socket-Datei unter demselben Pfad an. Ist Live-Restore von Docker eingeschaltet, läuft der Proxy während dieses Neustarts weiter und behält die alte Datei. Auf der alten Datei antwortet nichts.

**Schnelle Lösung.** Starte auf diesem Rechner den Proxy neu:

```bash
docker restart cashpilot-socket-proxy
```

Der Neustart bindet den neuen Socket ein, und der Worker findet Docker bei seinem nächsten Lebenszeichen wieder. Den Worker musst du nicht neu starten. Unter Unraid und TrueNAS hält der Worker den Socket selbst, starte also dort den Worker neu.

**Dauerhafte Lösung.** Binde den Ordner des Sockets ein, nicht die Socket-Datei. Ein Ordner-Bind zeigt einen ersetzten Socket sofort. Ersetze im Dienst `cashpilot-socket-proxy` deiner Compose-Datei die Zeile `- /var/run/docker.sock:/var/run/docker.sock:ro` durch den Bind unten und füge die Zeile `SOCKGUARD_UPSTREAM_SOCKET` zu seinem `environment` hinzu:

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

Führe dann `docker compose up -d` aus. Dieselbe Änderung funktioniert in `docker-compose.worker.yml` und `docker-compose.fleet.yml`. Compose liest diese Dateien nur, wenn du sie nennst, führe also `docker compose -f docker-compose.worker.yml up -d` oder `docker compose -f docker-compose.fleet.yml up -d` aus, außer `COMPOSE_FILE` nennt die Datei bereits.

- `recursive: disabled` ist notwendig. `/var/run` enthält andere Mounts, zum Beispiel die Netzwerk-Namespaces von Docker unter `/run/docker/netns` und `/run/user/...`. Ein rekursiver Bind holt sie alle in den Proxy. Ein nicht rekursiver Bind zeigt nur den Ordner selbst.
- `SOCKGUARD_UPSTREAM_SOCKET` schickt den Proxy auf den neuen Pfad. Der Richtlinienblock und sein Fingerabdruck bleiben, wie sie sind, denn die Umgebungsvariable überschreibt `upstream.socket` in der Richtlinie. Ohne die Variable startet der Proxy nicht (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` kann seinen Datei-Bind behalten. Er startet bei jedem `docker compose up` neu und bekommt daher immer den aktuellen Socket. Gibst du ihm denselben Ordner-Bind, füge `DOCKER_HOST=unix:///host-run/docker.sock` zu seinem `environment` hinzu. Worker 2.8.4 und neuer lesen diese Variable. Lass sie nie auf den Socket des Proxys zeigen: Der Migrator braucht den eigenen Socket des Hosts.
- Der Ordner-Bind gibt dem Proxy jeden Socket in `/var/run`, nicht nur den von Docker. Auf einem typischen Server gehören dazu der eigene Socket von systemd, D-Bus und die Sockets von Werkzeugen wie Tailscale oder snapd. `read_only` hindert ein Programm nicht daran, sich mit einem Socket zu verbinden, und der Proxy läuft als root. Zugriff auf den Docker-Socket gibt bereits root auf dem Host, daher gewinnt ein kompromittierter Proxy wenig, was er nicht schon hatte. Soll der Proxy nur den Docker-Socket halten, behalte den Datei-Bind und starte den Proxy nach einem Docker-Update neu: Die Warnung oben sagt dir, wann.
- Es braucht Docker Compose 2.30.0 oder neuer. Ältere Releases lehnen die ganze Datei mit `Additional property recursive is not allowed` ab. Prüfe das mit `docker compose version`. Debian 13 liefert Compose 2.26.1 aus, installiere Compose unter Debian also aus dem eigenen Repository von Docker. Das In-App-Update verwendet sein eigenes Compose 2.33 und liest daher die geänderte Datei.
- Es funktioniert nur unter Linux. Docker Desktop unter macOS und Windows bildet nur `/var/run/docker.sock` in seine virtuelle Maschine ab. Dort ist `/var/run` ein Ordner auf deinem Mac oder PC, ohne Docker-Socket darin.
- Bei rootless Docker liegt der Socket in `/run/user/<your uid>`, einem eigenen Mount. Verwende diesen Ordner als `source`.
- Unter Podman behältst du den Datei-Bind. Den Ordner-Bind haben wir dort nicht getestet.

Die mitgelieferten Dateien behalten den Datei-Bind, denn der Ordner-Bind braucht Compose 2.30 und Linux, und CashPilot unterstützt auch ältere Compose-Releases und Docker Desktop. Eine neuere Compose-Datei, die du herunterlädst, enthält deine Änderung nicht, nimm sie also erneut vor, nachdem du die Datei ersetzt hast.
