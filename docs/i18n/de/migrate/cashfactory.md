---
source_hash: 7f8476aeb8b6
---
# Umstieg von CashFactory { #moving-from-cashfactory }

CashPilot kann die `.env` von CashFactory lesen und deine Logins für die Dienste übernehmen, damit
du sie nicht erneut eintippen musst. Du prüfst alles, bevor CashPilot es speichert.

## Bevor du anfängst { #before-you-start }

Du brauchst das Eigentümerkonto von CashPilot und mindestens einen CashPilot-Worker.

Stoppe CashFactory auf einem Rechner, bevor du dort dieselben Dienste aus
CashPilot bereitstellst. Zwei Kopien hinter einer Verbindung verdienen wie eine, und dieselbe Geräte-ID
von EarnApp darf nicht zweimal laufen. Führe `docker compose down` im Ordner von CashFactory
aus. Seine
[Compose-Datei](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
startet außerdem drei Container, die den Docker-Socket einbinden: Portainer (Zeile 31)
und zwei Watchtower-Container (Zeilen 141 und 264). Stell sicher, dass auch sie weg sind: `docker ps` sollte
keinen davon auflisten.

## Welche Datei du verwendest { #which-file-to-use }

Verwende die `.env`-Datei in deinem CashFactory-Ordner, die du nach dem
[Muster](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env) ausgefüllt hast.

Docker Compose liest diese Datei, und es erweitert `$` in Werten, die nicht in
einfachen Anführungszeichen stehen. Ein solcher Wert ist nicht das, was die Datei zeigt, daher bittet CashPilot
dich, ihn neu einzutippen, statt zu raten.

## So importierst du { #how-to-import }

1. Öffne **Settings** (Einstellungen), dann **Import from another tool** (Aus einem anderen Werkzeug importieren) (oder geh zu `/import`).
2. Füge die `.env`-Datei hinzu oder füge ihren Text ein. Lass das Werkzeug auf **Tell from the
   files** (Anhand der Dateien erkennen) stehen oder wähle CashFactory.
3. Prüfe die Tabelle. Hake die Dienste an, die du willst, und fülle jeden Wert aus, der als
   fehlend markiert ist.
4. Drücke **Save the ticked services** (Angehakte Dienste speichern) und stelle sie dann von
   derselben Seite aus auf deinen Workern bereit.

## Was übernommen wird { #what-comes-over }

| App in CashFactory | Gelesene Schlüssel | Dienst in CashPilot | Was übernommen wird |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | Geräte-ID, damit dein verknüpftes Gerät weiter verdient |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | E-Mail, Passwort |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | E-Mail, Passwort |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | Token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | E-Mail, API-Schlüssel |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | Benutzer-ID |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | Geräte-UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API-Schlüssel |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | nichts: nicht mehr verfügbar |

Ein Wert, der noch den Platzhalter des Musters zeigt (`<email>`, `sdk-node-<md5sum>`),
gilt als nicht gesetzt, und ein Dienst mit nichts als Platzhaltern wird aus
der Tabelle weggelassen.

## Was nie übernommen wird { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot benennt jedes Gerät nach dem Worker, auf dem es läuft, damit
  zwei Worker nie denselben Namen melden. Deine alten Geräte bleiben im Dashboard jedes Anbieters
  als offline aufgeführt, bis du sie dort entfernst.
- **Bitping.** CashFactory bewahrt den Bitping-Login in einem Docker-Volume auf, nicht in
  `.env`, daher hat der Import nichts zu lesen und zeigt keine Bitping-Zeile. Tippe den
  Login in das Bereitstellungsformular von Bitping ein.
- **Portainer und Watchtower.** CashPilot verwaltet und aktualisiert seine eigenen
  Container.

## Verfolgung der Einnahmen { #earnings-tracking }

Bei Honeygain und IPRoyal Pawns ist der Login des Containers auch der Login des Kontos,
daher füllt CashPilot auch ihre Zugangsdaten für die Einnahmen aus, außer du hast
sie bereits in **Settings** (Einstellungen) gesetzt. Bei jedem anderen Dienst fügst du den Login für die Einnahmen unter
**Settings > Earnings collection** (Einstellungen > Erfassung der Einnahmen) hinzu.

## Sicherheit { #safety }

- Nichts in der Datei wird ausgeführt oder erweitert, und keine Adresse darin wird abgerufen.
- Die Datei wird einmal gelesen und nicht behalten. Was du speicherst, wird verschlüsselt gespeichert, wie
  alle anderen Zugangsdaten in CashPilot.
- Geheimnisse werden auf der Seite nur als **set** (gesetzt) angezeigt.
- Gespeicherte Importe bleiben auf der Importseite, bis du **Forget** (Vergessen) drückst, damit du
  sie später auf weiteren Workern bereitstellen kannst.
