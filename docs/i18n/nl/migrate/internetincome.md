---
source_hash: ca9dd25d45ca
---
# Overstappen van InternetIncome { #moving-from-internetincome }

CashPilot kan de `properties.conf` van InternetIncome lezen, en de bestanden waarin het
je apparaat-id's van EarnApp en ProxyRack bewaart, en ze overnemen. Je controleert
alles voordat CashPilot het opslaat.

## Voordat je begint { #before-you-start }

Je hebt het eigenaarsaccount van CashPilot nodig en minstens één CashPilot-worker.

Stop InternetIncome op een machine voordat je daar dezelfde diensten vanuit
CashPilot uitrolt. Twee kopieën achter één verbinding verdienen als één, en hetzelfde apparaat-id
mag niet twee keer draaien. Voer in de map van InternetIncome uit:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` verwijdert de containers en houdt `earnapp.txt`, `proxyrack.txt` en
de datamap van Mysterium. `--deleteBackup` verwijdert die ook
([internetIncome.sh, regels 61 tot 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
en [regel 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
dus importeer eerst.

## Welke bestanden je gebruikt { #which-files-to-use }

Uit de map van InternetIncome:

- `properties.conf`, je instellingen.
- `earnapp.txt`, als je EarnApp draaide. Elke regel bevat een apparaatlink
  ([regels 1250 tot 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, als je ProxyRack draaide. Eén UUID van een apparaat per regel
  ([regels 817 tot 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot neemt het eerste apparaat in elk bestand: het apparaat dat je hoofdcontainer
gebruikte en dat je aan je account hebt gekoppeld. De andere regels hoorden bij proxy-kopieën,
en de pagina vertelt je hoeveel er zijn weggelaten.

InternetIncome haalt elke waarde door de shell
([regel 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Een waarde tussen enkele aanhalingstekens wordt genomen zoals ze geschreven is, zoals de opmerkingen in
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
aanraden. Een waarde buiten enkele aanhalingstekens die `$`, een backtick, een spatie of
een ander teken bevat dat de shell zou veranderen, is niet wat het bestand toont, dus
CashPilot vraagt je haar opnieuw in te typen in plaats van een shell te draaien om het uit te zoeken.

## Zo importeer je { #how-to-import }

1. Open **Settings** (Instellingen), daarna **Import from another tool** (Importeren uit een andere tool) (of ga naar `/import`).
2. Voeg `properties.conf` toe, plus `earnapp.txt` en `proxyrack.txt` als je
   die hebt. Laat de tool op **Tell from the files** (Afleiden uit de bestanden) staan, of kies InternetIncome.
3. Controleer de tabel. Vink de diensten aan die je wilt en vul elke waarde in die als
   ontbrekend is gemarkeerd. Repocket heeft het e-mailadres van je account nodig, waar InternetIncome nooit
   om vroeg.
4. Druk op **Save the ticked services** (Aangevinkte diensten opslaan) en rol ze daarna vanaf dezelfde
   pagina uit naar je workers.

## Wat er meekomt { #what-comes-over }

| App in InternetIncome | Gelezen sleutels | Dienst in CashPilot | Wat er meekomt |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API-sleutel (voeg je e-mail toe) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API-sleutel, UUID van het apparaat |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | e-mail, wachtwoord |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | e-mail, wachtwoord |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | gebruikers-id |
| `earnfm` | `EARN_FM_API` | Earn.fm | API-sleutel |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | apparaat-id |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | e-mail, wachtwoord |
| `mysterium` | `MYSTERIUM=true` | Mysterium | ingeschakeld; zie de opmerking over Mysterium hieronder |

Een lege waarde betekent dat de app uit stond, en dan wordt hij niet getoond.

Deze apps worden getoond maar niet overgenomen:

| App in InternetIncome | Waarom |
|---|---|
| `urnetwork` | InternetIncome gebruikt een sessietoken. CashPilot meldt URnetwork aan met je e-mail en wachtwoord. |
| `grass` | Grass draait als browserextensie. CashPilot volgt het alleen, met het toegangstoken uit het dashboard van Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot volgt deze, maar er is geen container om uit te rollen. |
| `peer2profit` | Niet meer beschikbaar. |

Instellingen voor apps die CashPilot niet heeft (antGain, Adnade en andere), worden
op naam getoond als niet gelezen.

## Wat nooit meekomt { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot noemt elk apparaat naar de worker waarop het draait, zodat
  twee workers nooit dezelfde naam melden. Je oude apparaten blijven als
  offline vermeld in het dashboard van elke aanbieder tot je ze daar verwijdert.
- **Proxy's** (`USE_PROXIES`, `proxies.txt`). Voeg ze een voor een toe in het onderdeel **Proxies** (Proxy's)
  van de pagina **Fleet** (Vloot), en draai daarna kopieën van je diensten erdoorheen; een
  proxy toevoegen start op zichzelf niets. Met `USE_PROXIES=true` draaide InternetIncome
  je diensten alleen via proxy's. Een import opslaan start ook niets. Een
  proxy-kopie heeft eerst dezelfde dienst nodig, uitgerold op de worker, en die
  uitrollen laat hem draaien op de eigen verbinding van de worker, dus een dienst die die verbinding
  nooit mag gebruiken, laat je beter zonder vinkje. Zie [Proxy-kopieën](../proxies.md).
- **`BROWSER_USERNAME` en `BROWSER_PASSWORD`**, de eigen browserlogin van
  InternetIncome.

## Inkomsten volgen { #earnings-tracking }

Voor Honeygain, IPRoyal Pawns en Bitping is de login van de container ook de
login van het account, dus CashPilot vult ook hun inloggegevens voor de inkomsten in, tenzij je
die al in **Settings** (Instellingen) hebt ingesteld. Voeg voor elke andere dienst de login voor de inkomsten toe
in **Settings > Earnings collection** (Instellingen > Inkomsten verzamelen).

## Mysterium { #mysterium }

Importeren zet Mysterium aan, maar CashPilot start een nieuwe node met een nieuwe
identiteit. De keystore van de oude node en eventuele niet-afgerekende inkomsten blijven in
de map `mysterium-data` van InternetIncome. Reken ze eerst af, of volg de
[handleiding van Mysterium](../guides/mysterium.md) om de identiteit mee te nemen.

## Veiligheid { #safety }

- Niets in de bestanden wordt uitgevoerd of ingevuld, en geen enkel adres erin wordt opgehaald.
- De bestanden worden één keer gelezen en niet bewaard. Wat je opslaat, wordt versleuteld bewaard, net als
  alle andere inloggegevens in CashPilot.
- Geheimen worden op de pagina alleen als **set** (ingesteld) getoond.
- Opgeslagen imports blijven op de importpagina staan tot je op **Forget** (Vergeten) drukt, zodat je
  ze later naar meer workers kunt uitrollen.
