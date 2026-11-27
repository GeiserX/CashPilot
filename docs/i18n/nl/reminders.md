---
source_hash: b4ae1a3ae496
---
# Geld dat wacht: herinneringen voordat je inkomsten verliest { #money-waiting-reminders-before-you-lose-earnings }

Sommige aanbieders nemen geld terug dat te lang blijft staan. Een saldo kan verlopen na
maanden zonder activiteit. Een claimperiode kan sluiten. Een aanbieder kan een
account blokkeren, stoppen met betalen of ophouden te bestaan terwijl je saldo er nog staat.
CashPilot leest het meeste wat het nodig heeft om dit te zien aankomen al. Het
paneel **Money waiting** (Geld dat wacht) op het dashboard toont wat je moet doen en wanneer, en
je meldingskanalen krijgen vóór elke deadline een pushbericht.

CashPilot claimt of neemt nooit iets voor je op. Elke herinnering linkt naar
de eigen pagina van de aanbieder, en daar onderneem je actie.

## Waarvoor het je herinnert { #what-it-reminds-you-about }

**Regels uit de eigen voorwaarden van de aanbieder.** Elke regel verwijst naar de voorwaarden
of de helppagina van de aanbieder, en naar de datum waarop iemand die het laatst las. De link **Source** (Bron) in het
menu **More** (Meer) van de rij opent die.

| Dienst | Herinnering | Wanneer |
|---|---|---|
| Grass | Claim je USDC van Stage 2 | Uiterlijk 22 jan 2027. Grass houdt wat niet is geclaimd. |
| MystNodes | Claim de beloningen van vorige maand | Binnen 30 dagen na elke maandelijkse verdeling |
| Honeygain | Neem je saldo op | 24 maanden nadat het voor het eerst $20 bereikte |
| Honeygain | Houd een apparaat aan het delen, of laat een uitbetaling doen | 6 maanden na de laatste activiteit of uitbetaling |
| Repocket | Houd een apparaat aan het delen, of neem op | 12 maanden na de laatste activiteit of uitbetaling |
| Bitping | Neem je saldo op | 12 maanden na de laatste opname |
| Salad | Verdien wat Reward Points, of besteed je saldo | 12 maanden nadat het saldo voor het laatst groeide. Een deel ervan uitgeven zet dit niet terug. |

**Cash-out.** CashPilot meldt je wanneer een saldo de minimale uitbetaling van de aanbieder
bereikt. Dit geldt voor elke dienst waarvan het verzamelt, behalve diensten die
vanzelf uitbetalen. Een saldo moet ook minstens $5 waard zijn, zodat een aanbieder
met een minimum van 5 cent niet bij de eerste cent zeurt. Ligt het minimum van de
aanbieder hoger, dan geldt het minimum van de aanbieder. Kan CashPilot het minimum of het saldo niet
omrekenen, dan toont het niets. Het gokt nooit dat
je kunt opnemen.

**Verlopen van inloggegevens.** Je krijgt een pushbericht voordat een opgeslagen token of cookie verloopt.
CashPilot gebruikt de vervaldatum die het inloggegeven zelf vermeldt. Vermeldt het
er geen, dan gebruikt CashPilot de gebruikelijke levensduur van dat soort inloggegevens, gerekend
vanaf de dag waarop je het opsloeg. Eigenaren zien het al onder **Needs attention** (Aandacht nodig),
met een knop **Renew** (Vernieuwen), dus het paneel herhaalt het niet. Alleen eigenaren krijgen
herinneringen over inloggegevens van de API, net als bij de gezondheidscontrole van inloggegevens.
Een inloggegeven dat de aanbieder heeft geweigerd, staat al bij de bel en is al gepusht,
dus het wordt niet opnieuw gepusht.

## Welke diensten het dekt { #which-services-it-covers }

Een herinnering geldt voor een dienst die je gebruikt: een die is uitgerold, een die je
als extern hebt ingesteld in **Settings** (Instellingen), of een app die een telefoon meldt. Een dienst die je verwijderde,
telt nog mee zolang hij een saldo heeft, omdat de klokken voor inactiviteit beginnen
wanneer hij stopt. Eigen diensten en stopgezette diensten krijgen geen herinneringen.

## Data en "of eerder" { #dates-and-or-earlier }

De klokken voor activiteit tellen vanaf wat CashPilot vastlegde:

- de laatste keer dat het saldo groeide,
- de laatste uitbetaling,
- of de eerste meting op of boven het minimum.

Soms begon de klok vóór de eerste meting van CashPilot. Dan kan de echte
deadline eerder liggen dan CashPilot kan zien, en zegt de rij
"uiterlijk 3 okt 2027 of eerder".

CashPilot verwijdert de geschiedenis van inkomsten na 400 dagen, en de klok van Honeygain
loopt 730 dagen. Daarom slaat CashPilot elk beginpunt van een klok op de eerste keer dat het er
een ziet, en houdt het vast nadat de geschiedenis erachter weg is. Een uitbetaling zet
de klok terug, behalve waar de aanbieder alleen verdienen meetelt. Salad is er zo een: een
uitbetaling die een saldo laat staan, zet de 12 maanden niet terug.

Een vaste datum verdwijnt de dag nadat hij verstreken is, omdat het geld dan weg is.
Een klok die over tijd is, blijft staan en meldt dat de aanbieder het geld misschien al heeft
afgeschreven. Hij blijft staan tot je hem als klaar markeert of dempt, of tot een uitbetaling
hem terugzet.

## Wat je met een herinnering kunt doen { #what-you-can-do-with-a-reminder }

Eigenaren en bewerkers zien de knoppen. Kijkers zien alleen de herinneringen. Alleen eigenaren
kunnen iets doen met een herinnering over inloggegevens.

- **Done** (Klaar), of **Requested** (Aangevraagd) bij een opname, verbergt deze herinnering. Een maandelijkse
  periode komt volgende maand terug. Een opname komt na 14 dagen één keer terug als
  het saldo er nog staat, en vraagt of de uitbetaling is aangekomen. Dat valt
  binnen de bezwaartermijn van 60 dagen die de meeste aanbieders geven.
- **Snooze** (Uitstellen) verbergt hem een dag of een week en houdt zijn pushberichten tegen. Uitstellen loopt nooit
  voorbij de laatste waarschuwing vóór een deadline.
- **Not for me** (Niet voor mij), in het menu **More** (Meer), dempt één herinnering, of elke herinnering
  van een dienst. Een voorbeeld: Honeygain in de JumpTask-modus, waar een gelijkblijvend saldo
  normaal is. Gedempte herinneringen staan onderaan het paneel, met
  **Unmute** (Dempen opheffen).

Het huishouden deelt deze keuzes. Markeert één persoon een herinnering als klaar, dan is ze
voor iedereen klaar. Elke keuze wordt in het auditlogboek vastgelegd met de naam van
de persoon die haar maakte.

## Pushberichten { #pushes }

Herinneringen gaan naar de kanalen die je voor meldingen instelde: ntfy, een webhook of Telegram
([configuratie](configuration.md)). Is er geen kanaal ingesteld, dan is het paneel de enige
plek waar ze verschijnen.

- Eén pushbericht per waarschuwing. Grass pusht bijvoorbeeld 60, 30, 7 en 1 dag vóór
  zijn datum. Een herinnering die voor het eerst 5 dagen vóór zijn datum verschijnt, pusht één keer, met nog 5
  dagen te gaan.
- Pushberichten gaan alleen tussen 09:00 en 21:00 de deur uit. CashPilot gebruikt de tijdzone van de eerste eigenaar
  uit **Settings** (Instellingen), daarna de `TZ` van de container, daarna UTC. Een waarschuwing
  die 's nachts wordt bereikt, gaat uit bij de eerste controle na 09:00.
- Zijn er meer dan 3 pushberichten tegelijk aan de beurt, dan krijg je in plaats daarvan één samenvatting. Dit
  gebeurt op de dag dat je bijwerkt, wanneer elk saldo boven zijn minimum
  tegelijk verschijnt.
- Een pushbericht bevat de dienst, wat je moet doen, wat je zou verliezen, de datum en de
  link van de aanbieder. Het bevat nooit een saldo, een adres, een apparaat-id of een
  workernaam. Onderwerpen (topics) van ntfy kunnen openbaar zijn.
- Webhook-payloads bevatten `kind: "obligation"`, zodat Home Assistant en vergelijkbare
  tools ze kunnen doorsturen.

## Voor bijdragers aan de catalogus { #for-catalog-contributors }

Regels staan in het YAML-bestand van elke dienst, onder `obligations:`.
`services/_schema.yml` beschrijft de velden. Voeg alleen een regel toe als de
eigen voorwaarden of documentatie van de aanbieder hem vermelden, en als CashPilot het signaal kan zien
waarvan hij afhangt. De link van een regel moet op het eigen domein van de dienst staan, omdat er nep-
claimsites bestaan voor juist deze diensten. CI faalt op een ongeldige regel, en
op een regel met een datum die meer dan 30 dagen verstreken is.
