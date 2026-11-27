---
source_hash: e99e2c0c80bb
---
# App stores { #app-stores }

Je kunt CashPilot installeren vanuit de app store van verschillende thuisserversystemen.
Elke vermelding installeert het dashboard (`drumsergio/cashpilot`) en de worker
(`drumsergio/cashpilot-worker`), die de dienstcontainers start en stopt.
Alleen de CasaOS- en Runtipi-pakketten in deze repository installeren ook
de Docker-socket-proxy uit `docker-compose.yml`, zodat hun worker
nooit de kale Docker-socket in handen heeft. De Unraid-templates, de TrueNAS-app en
het pakket in de openstaande pull request voor de CasaOS-app store mounten de Docker-socket
nog steeds rechtstreeks in de worker.

Welke store je ook gebruikt, houd het dashboard op je LAN of VPN. Het kan
de worker aansturen, en de worker bestuurt Docker op de host. Waar de worker
de socket zelf vasthoudt, is dat root op de host.

## Nu vermeld { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Zoek naar **CashPilot** in het tabblad Apps en installeer beide templates:
`cashpilot` (het dashboard) en `cashpilot-worker`. Stel op beide dezelfde
`CASHPILOT_API_KEY` in.

De templates komen van https://github.com/GeiserX/docker-templates en volgen
de image-tag `latest`, dus gebruikers van Community Applications krijgen elke release
zonder dat het template verandert.

### TrueNAS SCALE { #truenas-scale }

CashPilot staat in de **community**-train van TrueNAS. Open Apps, daarna Discover Apps,
en zoek naar **CashPilot**.

De app-definitie wordt bijgehouden op
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot en pint
een exacte image-digest. De eigen bots van TrueNAS zetten hem over naar nieuwe releases, dus hij kan
een paar releases achterlopen op de nieuwste CashPilot.

## Wacht op beoordeling { #waiting-for-review }

### CasaOS { #casaos }

Er staat een pull request open bij de CasaOS-app store:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Tot die is samengevoegd, installeer je het als eigen app: kies in CasaOS App Store,
daarna Custom Install, daarna Import, en plak de inhoud van
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Het vereist CasaOS 0.4.5 of nieuwer: vanaf die release is de appbeheerder gebouwd op
Docker Compose 2.23, dat het beleid van de socket-proxy uit het bestand leest.
Oudere versies laten het weg, en de worker kan Docker dan niet bereiken.

Dat bestand pint een exacte release. Zet vóór het importeren beide image-tags
(`drumsergio/cashpilot` en `drumsergio/cashpilot-worker`) op de nieuwste
release van https://github.com/GeiserX/CashPilot/releases. Het proxybeleid
in het bestand volgt `main`; meldt de statuspagina van de worker dat zijn beleid
verouderd is, importeer het bestand dan opnieuw.

## Voorbereid, nog niet ingediend { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Het pakket staat klaar in
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
maar nog niet in de Runtipi-app store. Wil je het nu gebruiken, voeg het dan toe aan een eigen app
store die jij beheert, volgens de documentatie van Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Niet aangeboden { #not-offered }

Umbrel vereist een ander workerontwerp, omdat Umbrel-apps Docker bereiken
via een Docker-in-Docker-container en niet via de socket van de host. Dat hebben we niet
getest, dus er is nog geen Umbrel-pakket.

Gebruik voor elk ander systeem `docker-compose.yml` uit de repository, zoals in
[Aan de slag](getting-started.md).
