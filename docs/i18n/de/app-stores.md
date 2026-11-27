---
source_hash: e99e2c0c80bb
---
# App-Stores { #app-stores }

Du kannst CashPilot aus dem App-Store mehrerer Heimserver-Systeme installieren.
Jeder Eintrag installiert das Dashboard (`drumsergio/cashpilot`) und den Worker
(`drumsergio/cashpilot-worker`), der die Container der Dienste startet und stoppt.
Nur die Pakete für CasaOS und Runtipi in diesem Repository installieren zusätzlich
den Docker-Socket-Proxy aus `docker-compose.yml`, sodass ihr Worker
nie den rohen Docker-Socket hält. Die Unraid-Vorlagen, die TrueNAS-App und
das Paket im offenen Pull Request für den CasaOS-App-Store binden den Docker-Socket
weiterhin direkt in den Worker ein.

Egal welchen Store du nutzt, halte das Dashboard in deinem LAN oder VPN. Es kann dem
Worker Befehle geben, und der Worker steuert Docker auf dem Host. Wo der Worker
den Socket selbst hält, ist das root auf dem Host.

## Heute gelistet { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Suche im Tab Apps nach **CashPilot** und installiere beide Vorlagen:
`cashpilot` (das Dashboard) und `cashpilot-worker`. Setze bei beiden denselben
`CASHPILOT_API_KEY`.

Die Vorlagen stammen aus https://github.com/GeiserX/docker-templates und folgen
dem Image-Tag `latest`, sodass Nutzer von Community Applications jedes Release
ohne Änderung an der Vorlage bekommen.

### TrueNAS SCALE { #truenas-scale }

CashPilot ist im **community**-Train von TrueNAS. Öffne Apps, dann Discover Apps,
und suche nach **CashPilot**.

Die App-Definition wird unter
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot gepflegt und legt
einen genauen Image-Digest fest. Die eigenen Bots von TrueNAS heben sie auf neue Releases, daher kann sie
ein paar Releases hinter dem neuesten CashPilot liegen.

## Warten auf Prüfung { #waiting-for-review }

### CasaOS { #casaos }

Ein Pull Request für den CasaOS-App-Store ist offen:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Bis er gemergt ist, installierst du es als eigene App: Wähle in CasaOS App Store,
dann Custom Install, dann Import, und füge den Inhalt von
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml
ein.

Es braucht CasaOS 0.4.5 oder neuer: Ab diesem Release baut sein App-Manager auf
Docker Compose 2.23 auf, das die Richtlinie des Socket-Proxys aus der Datei liest.
Ältere Versionen verwerfen sie, und der Worker kann Docker dann nicht erreichen.

Diese Datei legt ein genaues Release fest. Setze vor dem Import beide Image-Tags
(`drumsergio/cashpilot` und `drumsergio/cashpilot-worker`) auf das neueste
Release von https://github.com/GeiserX/CashPilot/releases. Die Proxy-Richtlinie
in der Datei folgt `main`; meldet die Statusseite des Workers, dass seine Richtlinie
veraltet ist, importiere die Datei erneut.

## Vorbereitet, noch nicht eingereicht { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Das Paket liegt fertig in
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
bereit, ist aber noch nicht im Runtipi-App-Store. Um es jetzt zu nutzen, füge es einem eigenen
App-Store hinzu, den du kontrollierst, nach der Runtipi-Dokumentation:
https://runtipi.io/docs/guides/create-your-own-app-store

## Nicht angeboten { #not-offered }

Umbrel braucht ein anderes Worker-Design, denn Umbrel-Apps erreichen Docker
über einen Docker-in-Docker-Container statt über den Socket des Hosts. Das haben wir nicht
getestet, daher gibt es noch kein Umbrel-Paket.

Für jedes andere System verwendest du `docker-compose.yml` aus dem Repository, wie unter
[Erste Schritte](getting-started.md).
