---
source_hash: 05d0f97e7d36
---
# Umstieg von money4band { #moving-from-money4band }

CashPilot kann die Konfiguration von money4band lesen und deine Logins für die Dienste übernehmen, damit
du sie nicht erneut eintippen musst. Du prüfst alles, bevor CashPilot es speichert.

## Bevor du anfängst { #before-you-start }

Du brauchst das Eigentümerkonto von CashPilot und mindestens einen CashPilot-Worker auf dem
Rechner, auf dem money4band jetzt läuft, oder auf einem anderen Rechner.

Stoppe money4band auf einem Rechner, bevor du dort dieselben Dienste aus
CashPilot bereitstellst. Zwei Kopien hinter einer Verbindung verdienen wie eine, und dieselbe Geräte-ID von EarnApp
oder ProxyRack darf nicht zweimal laufen. Verwende **Stop apps stack** im
Menü von money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
oder führe `docker compose down` in seinem Ordner aus. Hast du zusätzliche Proxy-Instanzen
eingerichtet, stoppe auch jede davon.

## Welche Datei du verwendest { #which-file-to-use }

Verwende `config/user-config.json` in deinem money4band-Ordner. Wie du sie zu
CashPilot bringst, hängt von deiner money4band-Version ab.

In money4band 4.x schreibt money4band die Datei, wenn du **Setup Apps** ausführst, und
sie enthält genau das, was du eingetippt hast. Die `.env`
daneben wird aus dieser Datei erzeugt und funktioniert ebenfalls, genau wie die von Hand bearbeitete
`.env` von money4band 3.x. Beide bleiben nur auf deiner Festplatte: Die
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
von money4band führt sie auf.

money4band 5.0 verschlüsselt `config/user-config.json` auf der Festplatte
([Sicherheitshinweise](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
und es löscht seine `.env` nach jedem Start
([env-Builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot kann die verschlüsselte Datei nicht lesen. Führe in deinem money4band-Ordner
seinen Befehl `config edit` aus: `./Money4Band-<os>-<arch> config edit` für die
Release-Binärdatei oder `python main.py config edit` aus dem Quellcode. Das öffnet
die entschlüsselte Datei in deinem Editor
([CLI-Referenz](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Kopiere ihren ganzen Text, füge ihn auf der Seite **Import from another tool** (Aus einem anderen Werkzeug importieren) ein und schließe dann den Editor.

Nimm lieber die JSON-Datei. In einer `.env` erweitert Docker Compose `$` in Werten ohne Anführungszeichen,
daher ist ein Passwort mit `$` darin nicht das, was die Datei zeigt. CashPilot rät
nicht: Es bittet dich, diesen Wert neu einzutippen.

## So importierst du { #how-to-import }

1. Öffne **Settings** (Einstellungen), dann **Import from another tool** (Aus einem anderen Werkzeug importieren) (oder geh zu `/import`).
2. Füge `user-config.json` hinzu oder füge ihren Text ein. Lass das Werkzeug auf **Tell from the
   files** (Anhand der Dateien erkennen) stehen oder wähle money4band.
3. Prüfe die Tabelle. Hake die Dienste an, die du willst, und fülle jeden Wert aus, der als
   fehlend markiert ist.
4. Drücke **Save the ticked services** (Angehakte Dienste speichern) und stelle sie dann von
   derselben Seite aus auf deinen Workern bereit.

## Was übernommen wird { #what-comes-over }

Die Feldnamen stammen aus der
[user-config-Vorlage](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
von money4band und die `.env`-Namen aus denen, die ihr
[Generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
schreibt (`<APP>_<FLAG>`, zum Beispiel `REPOCKET_APIKEY`). money4band 5.0 behält
dieselben Feldnamen in seinem
[App-Katalog](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported) bei.

| App in money4band | Dienst in CashPilot | Was übernommen wird |
|---|---|---|
| `earnapp` | EarnApp | Geräte-ID (`uuid`), damit dein verknüpftes Gerät weiter verdient |
| `honeygain` | Honeygain | E-Mail, Passwort |
| `iproyalpawns` | IPRoyal Pawns | E-Mail, Passwort |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | Token |
| `repocket` | Repocket | E-Mail, API-Schlüssel |
| `earnfm` | Earn.fm | API-Schlüssel |
| `proxyrack` | ProxyRack | API-Schlüssel, Geräte-UUID |
| `proxylite` | ProxyLite | Benutzer-ID |
| `bitping` | Bitping | E-Mail, Passwort |
| `mystnode` | Mysterium | eingeschaltet; siehe den Hinweis zu Mysterium unten |

Eine App, die du in money4band ausgeschaltet hast, erscheint nicht angehakt. Eine App, die aus ist und
nichts außer den Platzhaltern der Vorlage (`yourHONEYGAINMail`) und Portlisten enthält,
wird weggelassen, daher ergibt eine unveränderte `user-config.json` eine leere Tabelle.

Diese Apps werden aufgeführt, aber nicht übernommen:

| App in money4band | Warum |
|---|---|
| `proxybase` | money4band betreibt den alten Client von ProxyBase mit einer Benutzer-ID. CashPilot betreibt den aktuellen, der das Access Token von proxybase.org braucht. |
| `urnetwork` | money4band behält ein Sitzungs-Token. CashPilot meldet URnetwork mit deiner E-Mail und deinem Passwort an. |
| `grass` | Grass läuft als Browser-Erweiterung. CashPilot verfolgt es nur, mit dem Access Token aus dem Grass-Dashboard. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot verfolgt diese, aber es gibt keinen Container zum Bereitstellen. |
| `packetshare`, `peer2profit`, `speedshare` | Nicht mehr verfügbar. |

Jede andere App wird als **CashPilot has no such service** (CashPilot hat keinen solchen Dienst) aufgeführt.

## Was nie übernommen wird { #what-never-comes-over }

- **Gerätename.** CashPilot benennt jedes Gerät nach dem Worker, auf dem es läuft, damit
  zwei Worker nie denselben Namen melden. Deine alten Geräte bleiben im Dashboard jedes Anbieters
  als offline aufgeführt, bis du sie dort entfernst.
- **Proxys.** Füge jeden im Bereich **Proxies** (Proxys) der Seite **Fleet** (Flotte) hinzu und lass dann
  Kopien deiner Dienste darüber laufen; das Hinzufügen eines Proxys startet von sich aus nichts.
  Auch das Speichern eines Imports startet nichts. Eine Proxy-Kopie braucht zuerst denselben Dienst,
  bereitgestellt auf dem Worker, und dessen Bereitstellung lässt ihn über die eigene Verbindung des Workers laufen,
  daher sollte ein Dienst, der diese Verbindung nie verwenden darf, nicht angehakt
  bleiben. Siehe [Proxy-Kopien](../proxies.md).
- **Watchtower und Benachrichtigungen.** CashPilot aktualisiert seine eigenen Container.
- **Das Dashboard von money4band und seine Ports.**

## Verfolgung der Einnahmen { #earnings-tracking }

Bei Honeygain, IPRoyal Pawns und Bitping ist der Login des Containers auch der
Login des Kontos, daher füllt CashPilot auch ihre Zugangsdaten für die Einnahmen aus, außer du
hast sie bereits in **Settings** (Einstellungen) gesetzt. Bei jedem anderen Dienst fügst du den Login für die Einnahmen
unter **Settings > Earnings collection** (Einstellungen > Erfassung der Einnahmen) hinzu.

## Mysterium { #mysterium }

Der Import schaltet Mysterium ein, aber CashPilot startet einen neuen Node mit einer neuen
Identität. Der Keystore des alten Nodes und alle nicht abgerechneten Einnahmen bleiben im
Ordner `.data/mysterium-node` von money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Rechne sie zuerst ab oder folge der
[Mysterium-Anleitung](../guides/mysterium.md), um die Identität mitzunehmen.

Eine `.env` von 3.x kann nicht erkennen, ob du Mysterium betrieben hast: Ihre Vorlage führt immer
den Port des Dashboards auf. Aus einer 3.x-Datei wird Mysterium nicht importiert, füge es also
aus dem Katalog hinzu, wenn du es betrieben hast.

## Sicherheit { #safety }

- Nichts in der Datei wird ausgeführt oder erweitert, und keine Adresse darin wird abgerufen.
- Die Datei wird einmal gelesen und nicht behalten. Was du speicherst, wird verschlüsselt gespeichert, wie
  alle anderen Zugangsdaten in CashPilot.
- Geheimnisse werden auf der Seite nur als **set** (gesetzt) angezeigt.
- Gespeicherte Importe bleiben auf der Importseite, bis du **Forget** (Vergessen) drückst, damit du
  sie später auf weiteren Workern bereitstellen kannst.
