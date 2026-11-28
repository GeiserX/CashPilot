---
source_hash: 1a7f6b462b56
---
# Overstappen van money4band { #moving-from-money4band }

CashPilot kan de configuratie van money4band lezen en je logins voor diensten overnemen, zodat
je ze niet opnieuw hoeft in te typen. Je controleert alles voordat CashPilot het opslaat.

## Voordat je begint { #before-you-start }

Je hebt het eigenaarsaccount van CashPilot nodig en minstens één CashPilot-worker op de
machine waar money4band nu draait, of op een andere machine.

Stop money4band op een machine voordat je daar dezelfde diensten vanuit
CashPilot uitrolt. Twee kopieën achter één verbinding verdienen als één, en hetzelfde apparaat-id van EarnApp
of ProxyRack mag niet twee keer draaien. Gebruik **Stop apps stack** in
het menu van money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
of voer `docker compose down` uit in zijn map. Heb je extra proxy-instanties
ingesteld, stop die dan ook allemaal.

## Welk bestand je gebruikt { #which-file-to-use }

Gebruik `config/user-config.json` in je money4band-map. Hoe je het naar
CashPilot brengt, hangt af van je versie van money4band.

In money4band 4.x schrijft money4band het bestand wanneer je **Setup Apps** uitvoert, en
het bevat precies wat je hebt ingetypt. De `.env`
ernaast wordt uit dat bestand gemaakt en werkt ook, net als de met de hand bewerkte
`.env` van money4band 3.x. Beide blijven alleen op je schijf: de
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
van money4band noemt ze.

money4band 5.0 versleutelt `config/user-config.json` op de schijf
([beveiligingsnotities](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
en het verwijdert zijn `.env` na elke start
([env-builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot kan het versleutelde bestand niet lezen. Voer `m4b config edit` uit in je
money4band-map: dat opent het ontsleutelde bestand in je editor
([CLI-referentie](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Kopieer al de tekst ervan, plak die op de importpagina en sluit daarna de editor.

Kies bij voorkeur het JSON-bestand. In een `.env` vult Docker Compose `$` in waarden zonder aanhalingstekens in,
dus een wachtwoord met `$` erin is niet wat het bestand toont. CashPilot gokt
niet: het vraagt je die waarde opnieuw in te typen.

## Zo importeer je { #how-to-import }

1. Open **Settings** (Instellingen), daarna **Import from another tool** (Importeren uit een andere tool) (of ga naar `/import`).
2. Voeg `user-config.json` toe, of plak de tekst ervan. Laat de tool op **Tell from the files** (Afleiden uit de bestanden) staan, of kies money4band.
3. Controleer de tabel. Vink de diensten aan die je wilt en vul elke waarde in die als
   ontbrekend is gemarkeerd.
4. Druk op **Save the ticked services** (Aangevinkte diensten opslaan) en rol ze daarna vanaf dezelfde
   pagina uit naar je workers.

## Wat er meekomt { #what-comes-over }

De veldnamen komen uit het
[user-config-template](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
van money4band en uit de `.env`-namen die zijn
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
schrijft (`<APP>_<FLAG>`, bijvoorbeeld `REPOCKET_APIKEY`). money4band 5.0 houdt
dezelfde veldnamen aan in zijn
[app-catalogus](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| App in money4band | Dienst in CashPilot | Wat er meekomt |
|---|---|---|
| `earnapp` | EarnApp | apparaat-id (`uuid`), zodat je gekoppelde apparaat blijft verdienen |
| `honeygain` | Honeygain | e-mail, wachtwoord |
| `iproyalpawns` | IPRoyal Pawns | e-mail, wachtwoord |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | e-mail, API-sleutel |
| `earnfm` | Earn.fm | API-sleutel |
| `proxyrack` | ProxyRack | API-sleutel, UUID van het apparaat |
| `proxylite` | ProxyLite | gebruikers-id |
| `bitping` | Bitping | e-mail, wachtwoord |
| `mystnode` | Mysterium | ingeschakeld; zie de opmerking over Mysterium hieronder |

Een app die je in money4band hebt uitgezet, verschijnt zonder vinkje. Een app die uit staat en
niets bevat behalve de plaatshouders van het template (`yourHONEYGAINMail`) en poortlijsten,
wordt weggelaten, dus een onaangeroerde `user-config.json` geeft een lege tabel.

Deze apps worden getoond maar niet overgenomen:

| App in money4band | Waarom |
|---|---|
| `proxybase` | money4band draait de oude client van ProxyBase met een gebruikers-id. CashPilot draait de huidige, die het Access Token van proxybase.org nodig heeft. |
| `urnetwork` | money4band bewaart een sessietoken. CashPilot meldt URnetwork aan met je e-mail en wachtwoord. |
| `grass` | Grass draait als browserextensie. CashPilot volgt het alleen, met het toegangstoken uit het dashboard van Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot volgt deze, maar er is geen container om uit te rollen. |
| `packetshare`, `peer2profit`, `speedshare` | Niet meer beschikbaar. |

Elke andere app wordt getoond als **CashPilot has no such service** (CashPilot heeft zo'n dienst niet).

## Wat nooit meekomt { #what-never-comes-over }

- **Apparaatnaam.** CashPilot noemt elk apparaat naar de worker waarop het draait, zodat
  twee workers nooit dezelfde naam melden. Je oude apparaten blijven als
  offline vermeld in het dashboard van elke aanbieder tot je ze daar verwijdert.
- **Proxy's.** Voeg ze een voor een toe in het onderdeel **Proxies** (Proxy's) van de pagina **Fleet** (Vloot), en draai daarna
  kopieën van je diensten erdoorheen; een proxy toevoegen start op zichzelf niets.
  Een import opslaan start ook niets. Een proxy-kopie heeft eerst dezelfde dienst
  nodig, uitgerold op de worker, en die uitrollen laat hem draaien op de eigen verbinding van de worker,
  dus een dienst die die verbinding nooit mag gebruiken, laat je beter zonder vinkje.
  Zie [Proxy-kopieën](../proxies.md).
- **Watchtower en meldingen.** CashPilot werkt zijn eigen containers bij.
- **Het dashboard van money4band en zijn poorten.**

## Inkomsten volgen { #earnings-tracking }

Voor Honeygain, IPRoyal Pawns en Bitping is de login van de container ook de
login van het account, dus CashPilot vult ook hun inloggegevens voor de inkomsten in, tenzij je
die al in **Settings** (Instellingen) hebt ingesteld. Voeg voor elke andere dienst de login voor de inkomsten toe
in **Settings > Earnings collection** (Instellingen > Inkomsten verzamelen).

## Mysterium { #mysterium }

Importeren zet Mysterium aan, maar CashPilot start een nieuwe node met een nieuwe
identiteit. De keystore van de oude node en eventuele niet-afgerekende inkomsten blijven in
de map `.data/mysterium-node` van money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Reken ze eerst af, of volg de
[handleiding van Mysterium](../guides/mysterium.md) om de identiteit mee te nemen.

Een `.env` van 3.x kan niet zeggen of je Mysterium draaide: zijn template vermeldt
altijd de dashboardpoort. Uit een bestand van 3.x wordt Mysterium niet geïmporteerd, dus voeg
het toe vanuit de catalogus als je het draaide.

## Veiligheid { #safety }

- Niets in het bestand wordt uitgevoerd of ingevuld, en geen enkel adres erin wordt opgehaald.
- Het bestand wordt één keer gelezen en niet bewaard. Wat je opslaat, wordt versleuteld bewaard, net als
  alle andere inloggegevens in CashPilot.
- Geheimen worden op de pagina alleen als **set** (ingesteld) getoond.
- Opgeslagen imports blijven op de importpagina staan tot je op **Forget** (Vergeten) drukt, zodat je
  ze later naar meer workers kunt uitrollen.
