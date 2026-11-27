---
source_hash: ca9dd25d45ca
---
# Umstieg von InternetIncome { #moving-from-internetincome }

CashPilot kann die `properties.conf` von InternetIncome lesen, dazu die Dateien, in denen es
die Geräte-IDs von EarnApp und ProxyRack aufbewahrt, und sie übernehmen. Du prüfst
alles, bevor CashPilot es speichert.

## Bevor du anfängst { #before-you-start }

Du brauchst das Eigentümerkonto von CashPilot und mindestens einen CashPilot-Worker.

Stoppe InternetIncome auf einem Rechner, bevor du dort dieselben Dienste aus
CashPilot bereitstellst. Zwei Kopien hinter einer Verbindung verdienen wie eine, und dieselbe Geräte-ID
darf nicht zweimal laufen. Führe im Ordner von InternetIncome Folgendes aus:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` entfernt die Container und behält `earnapp.txt`, `proxyrack.txt` und
den Datenordner von Mysterium. `--deleteBackup` entfernt auch diese
([internetIncome.sh, Zeilen 61 bis 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
und [Zeile 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
importiere also zuerst.

## Welche Dateien du verwendest { #which-files-to-use }

Aus dem Ordner von InternetIncome:

- `properties.conf`, deine Einstellungen.
- `earnapp.txt`, wenn du EarnApp betrieben hast. Jede Zeile enthält einen Geräte-Link
  ([Zeilen 1250 bis 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, wenn du ProxyRack betrieben hast. Eine Geräte-UUID pro Zeile
  ([Zeilen 817 bis 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot nimmt das erste Gerät in jeder Datei: das, das dein Haupt-Container
verwendet hat, und das, das du mit deinem Konto verknüpft hast. Die anderen Zeilen gehörten zu Proxy-Kopien,
und die Seite sagt dir, wie viele sie weggelassen hat.

InternetIncome schickt jeden Wert durch die Shell
([Zeile 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Ein Wert in einfachen Anführungszeichen wird so genommen, wie er geschrieben ist, wie die Kommentare in
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
raten. Ein Wert außerhalb einfacher Anführungszeichen, der `$`, einen Backtick, ein Leerzeichen oder
ein anderes Zeichen enthält, das die Shell verändern würde, ist nicht das, was die Datei zeigt, daher
bittet CashPilot dich, ihn neu einzutippen, statt eine Shell laufen zu lassen, um es herauszufinden.

## So importierst du { #how-to-import }

1. Öffne **Settings** (Einstellungen), dann **Import from another tool** (Aus einem anderen Werkzeug importieren) (oder geh zu `/import`).
2. Füge `properties.conf` hinzu, dazu `earnapp.txt` und `proxyrack.txt`, wenn du
   sie hast. Lass das Werkzeug auf **Tell from the files** (Anhand der Dateien erkennen) stehen oder wähle InternetIncome.
3. Prüfe die Tabelle. Hake die Dienste an, die du willst, und fülle jeden Wert aus, der als
   fehlend markiert ist. Repocket braucht die E-Mail deines Kontos, nach der InternetIncome nie gefragt
   hat.
4. Drücke **Save the ticked services** (Angehakte Dienste speichern) und stelle sie dann von
   derselben Seite aus auf deinen Workern bereit.

## Was übernommen wird { #what-comes-over }

| App in InternetIncome | Gelesene Schlüssel | Dienst in CashPilot | Was übernommen wird |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API-Schlüssel (füge deine E-Mail hinzu) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | Token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API-Schlüssel, Geräte-UUID |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | E-Mail, Passwort |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | E-Mail, Passwort |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | Benutzer-ID |
| `earnfm` | `EARN_FM_API` | Earn.fm | API-Schlüssel |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | Geräte-ID |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | E-Mail, Passwort |
| `mysterium` | `MYSTERIUM=true` | Mysterium | eingeschaltet; siehe den Hinweis zu Mysterium unten |

Ein leerer Wert bedeutet, dass die App aus war, und sie wird nicht aufgeführt.

Diese Apps werden aufgeführt, aber nicht übernommen:

| App in InternetIncome | Warum |
|---|---|
| `urnetwork` | InternetIncome verwendet ein Sitzungs-Token. CashPilot meldet URnetwork mit deiner E-Mail und deinem Passwort an. |
| `grass` | Grass läuft als Browser-Erweiterung. CashPilot verfolgt es nur, mit dem Access Token aus dem Grass-Dashboard. |
| `titan`, `ebesucher`, `wipter` | CashPilot verfolgt diese, aber es gibt keinen Container zum Bereitstellen. |
| `peer2profit` | Nicht mehr verfügbar. |

Einstellungen für Apps, die CashPilot nicht hat (antGain, Adnade und andere), werden
mit Namen als nicht gelesen aufgeführt.

## Was nie übernommen wird { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot benennt jedes Gerät nach dem Worker, auf dem es läuft, damit
  zwei Worker nie denselben Namen melden. Deine alten Geräte bleiben im Dashboard jedes Anbieters
  als offline aufgeführt, bis du sie dort entfernst.
- **Proxys** (`USE_PROXIES`, `proxies.txt`). Füge jeden im Bereich **Proxies** (Proxys)
  der Seite **Fleet** (Flotte) hinzu und lass dann Kopien deiner Dienste darüber laufen; das Hinzufügen
  eines Proxys startet von sich aus nichts. Mit `USE_PROXIES=true` hat InternetIncome
  deine Dienste nur über Proxys betrieben. Auch das Speichern eines Imports startet nichts. Eine
  Proxy-Kopie braucht zuerst denselben Dienst, bereitgestellt auf dem Worker, und dessen
  Bereitstellung lässt ihn über die eigene Verbindung des Workers laufen, daher sollte ein Dienst, der
  diese Verbindung nie verwenden darf, nicht angehakt bleiben. Siehe [Proxy-Kopien](../proxies.md).
- **`BROWSER_USERNAME` und `BROWSER_PASSWORD`**, der eigene Browser-Login
  von InternetIncome.

## Verfolgung der Einnahmen { #earnings-tracking }

Bei Honeygain, IPRoyal Pawns und Bitping ist der Login des Containers auch der
Login des Kontos, daher füllt CashPilot auch ihre Zugangsdaten für die Einnahmen aus, außer du
hast sie bereits in **Settings** (Einstellungen) gesetzt. Bei jedem anderen Dienst fügst du den Login für die Einnahmen
unter **Settings > Earnings collection** (Einstellungen > Erfassung der Einnahmen) hinzu.

## Mysterium { #mysterium }

Der Import schaltet Mysterium ein, aber CashPilot startet einen neuen Node mit einer neuen
Identität. Der Keystore des alten Nodes und alle nicht abgerechneten Einnahmen bleiben im
Ordner `mysterium-data` von InternetIncome. Rechne sie zuerst ab oder folge der
[Mysterium-Anleitung](../guides/mysterium.md), um die Identität mitzunehmen.

## Sicherheit { #safety }

- Nichts in den Dateien wird ausgeführt oder erweitert, und keine Adresse darin wird abgerufen.
- Die Dateien werden einmal gelesen und nicht behalten. Was du speicherst, wird verschlüsselt gespeichert, wie
  alle anderen Zugangsdaten in CashPilot.
- Geheimnisse werden auf der Seite nur als **set** (gesetzt) angezeigt.
- Gespeicherte Importe bleiben auf der Importseite, bis du **Forget** (Vergessen) drückst, damit du
  sie später auf weiteren Workern bereitstellen kannst.
