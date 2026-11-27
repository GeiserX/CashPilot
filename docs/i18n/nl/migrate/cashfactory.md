---
source_hash: 7f8476aeb8b6
---
# Overstappen van CashFactory { #moving-from-cashfactory }

CashPilot kan de `.env` van CashFactory lezen en je logins voor diensten overnemen, zodat
je ze niet opnieuw hoeft in te typen. Je controleert alles voordat CashPilot het opslaat.

## Voordat je begint { #before-you-start }

Je hebt het eigenaarsaccount van CashPilot nodig en minstens één CashPilot-worker.

Stop CashFactory op een machine voordat je daar dezelfde diensten vanuit
CashPilot uitrolt. Twee kopieën achter één verbinding verdienen als één, en hetzelfde apparaat-id van EarnApp
mag niet twee keer draaien. Voer `docker compose down` uit in de map van
CashFactory. Zijn
[compose-bestand](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
start ook drie containers die de Docker-socket mounten: Portainer (regel 31)
en twee Watchtower-containers (regels 141 en 264). Zorg dat die ook weg zijn: `docker ps` mag
geen van hen tonen.

## Welk bestand je gebruikt { #which-file-to-use }

Gebruik het `.env`-bestand in je CashFactory-map, het bestand dat je hebt ingevuld op basis van het
[voorbeeld](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose leest dat bestand, en het vult `$` in waarden in die niet tussen
enkele aanhalingstekens staan. Zo'n waarde is niet wat het bestand toont, dus CashPilot vraagt
je hem opnieuw in te typen in plaats van te gokken.

## Zo importeer je { #how-to-import }

1. Open **Settings** (Instellingen), daarna **Import from another tool** (Importeren uit een andere tool) (of ga naar `/import`).
2. Voeg het `.env`-bestand toe, of plak de tekst ervan. Laat de tool op **Tell from the files** (Afleiden uit de bestanden) staan, of kies CashFactory.
3. Controleer de tabel. Vink de diensten aan die je wilt en vul elke waarde in die als
   ontbrekend is gemarkeerd.
4. Druk op **Save the ticked services** (Aangevinkte diensten opslaan) en rol ze daarna vanaf dezelfde
   pagina uit naar je workers.

## Wat er meekomt { #what-comes-over }

| App in CashFactory | Gelezen sleutels | Dienst in CashPilot | Wat er meekomt |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | apparaat-id, zodat je gekoppelde apparaat blijft verdienen |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | e-mail, wachtwoord |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | e-mail, wachtwoord |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | e-mail, API-sleutel |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | gebruikers-id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID van het apparaat |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API-sleutel |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | niets: niet meer beschikbaar |

Een waarde die nog de plaatshouder van het voorbeeld toont (`<email>`, `sdk-node-<md5sum>`),
telt als niet ingesteld, en een dienst met niets anders dan plaatshouders wordt uit
de tabel weggelaten.

## Wat nooit meekomt { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot noemt elk apparaat naar de worker waarop het draait, zodat
  twee workers nooit dezelfde naam melden. Je oude apparaten blijven als
  offline vermeld in het dashboard van elke aanbieder tot je ze daar verwijdert.
- **Bitping.** CashFactory bewaart de login van Bitping in een Docker-volume, niet in
  `.env`, dus de import heeft niets te lezen en toont geen rij voor Bitping. Typ de
  login in het uitrolformulier van Bitping.
- **Portainer en Watchtower.** CashPilot beheert en werkt zijn eigen
  containers bij.

## Inkomsten volgen { #earnings-tracking }

Voor Honeygain en IPRoyal Pawns is de login van de container ook de login van het account,
dus CashPilot vult ook hun inloggegevens voor de inkomsten in, tenzij je die al in
**Settings** (Instellingen) hebt ingesteld. Voeg voor elke andere dienst de login voor de inkomsten toe in
**Settings > Earnings collection** (Instellingen > Inkomsten verzamelen).

## Veiligheid { #safety }

- Niets in het bestand wordt uitgevoerd of ingevuld, en geen enkel adres erin wordt opgehaald.
- Het bestand wordt één keer gelezen en niet bewaard. Wat je opslaat, wordt versleuteld bewaard, net als
  alle andere inloggegevens in CashPilot.
- Geheimen worden op de pagina alleen als **set** (ingesteld) getoond.
- Opgeslagen imports blijven op de importpagina staan tot je op **Forget** (Vergeten) drukt, zodat je
  ze later naar meer workers kunt uitrollen.
