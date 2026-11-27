---
source_hash: 38029ca1a5d6
---
# Export van inkomsten voor de belasting { #income-export-for-taxes }

Open **Payouts** (Uitbetalingen), zoek **Income for taxes** (Inkomsten voor de belasting) en kies een periode en een valuta. **This year** (Dit jaar) loopt tot en met vandaag, en **Last year** (Vorig jaar) beslaat het vorige kalenderjaar. Laat de data leeg om de beschikbare geschiedenis tot en met vandaag te exporteren. CashPilot gebruikt UTC-data en neemt beide uiteinden van de periode mee.

CashPilot verwijdert metingen van inkomsten 400 dagen nadat ze zijn vastgelegd. De CSV gebruikt de geschiedenis die overblijft, dus een voorbij jaar kan maar een deel van zijn verdiende of opgebouwde inkomsten bevatten.

## Kies een boekhoudgrondslag { #choose-an-accounting-basis }

- **Kasstelsel.** Gebruik de rijen met uitbetalingen. Die leggen geld vast dat de dienst heeft uitbetaald. CashPilot neemt alleen bevestigde uitbetalingen mee.
- **Baten-en-lastenstelsel.** Gebruik de rijen met verdiende en opgebouwde inkomsten. Verdiende rijen tonen tegoed dat je volgens de voorwaarden van de dienst kunt opnemen. Opgebouwde rijen tonen onbetaald pooltegoed dat de pool misschien nooit uitbetaalt.

Gebruik voor dezelfde inkomsten één grondslag. Tel je de rijen met uitbetalingen op bij de verdiende en opgebouwde rijen, dan kun je hetzelfde geld twee keer tellen. Controleer welke grondslag voor jouw aangifte geldt.

## CSV-kolommen { #csv-columns }

| Kolom | Betekenis |
|---|---|
| date | UTC-dag van de latere meting of van de uitbetaling. Een uitbetaling gebruikt de datum die je invoerde of de dag waarop CashPilot hem ontdekte. |
| period_start | UTC-dag van de vorige meting voor deze dienst en bron. Leeg bij uitbetalingen. Een gat tussen metingen betekent dat het bedrag de hele tussenperiode dekt. |
| kind | earned, accrued of payout. |
| service | Dienst-ID in CashPilot. |
| coin | Valuta- of tokencode zoals CashPilot die vastlegde. |
| amount | Bedrag in die valuta of dat token. |
| usd_rate | Aantal Amerikaanse dollars per eenheid van coin. |
| usd_value | Bedrag gewaardeerd in Amerikaanse dollars. |
| local_currency | Fiatvaluta die je voor de export koos. |
| local_rate | Eenheden van je gekozen valuta per Amerikaanse dollar. |
| local_value | Bedrag gewaardeerd in je gekozen valuta. |
| method | Uitbetalingsmethode, als die is vastgelegd. |

Een lege waardering betekent dat de koers niet beschikbaar was. Het bedrag in de eigen valuta staat er nog. CashPilot slaat interne punten over, zoals Grass-punten in metingen van inkomsten. De eerste meting per bron geeft een beginsaldo. Latere rijen leggen stijgingen vast, dus de CSV kan beginnen na de oudste meting in de gekozen periode.

Leest meer dan één bron hetzelfde account, dan kan de CSV die inkomsten meer dan één keer tellen.

De USD-koers komt van de latere meting of van het uitbetalingsrecord. Vult CashPilot de prijs van een meting achteraf in, dan gebruikt het de prijs van CoinGecko om 00:00 UTC op die dag. CashPilot gebruikt de recentste referentiekoers van de ECB op of vóór de dag van de rij om USD om te rekenen naar je gekozen valuta. Dat dekt weekenden, feestdagen en dagen waarop de ECB haar koers nog niet heeft gepubliceerd. [Dagkoersen van Frankfurter](https://frankfurter.dev/v1/)

Frankfurter vermeldt deze valuta voor de export. [Ondersteunde valuta](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR en ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD en ZAR.

Kies USD als je valuta niet in die lijst staat of Frankfurter niet beschikbaar is.

## Importeren in een andere tool { #import-into-another-tool }

Zet de CSV vóór het importeren om naar het formaat van de tool. Kies eerst de rijen voor je boekhoudgrondslag. Sla rijen met uitbetalingen over voor een wallet die de tool al synchroniseert.

### rotki { #rotki }

Gebruik Generic Events met deze kopteksten.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Zet Type op Income en Location op external. rotki accepteert ook Deposit, Withdrawal, Loss, Spend en Staking als die typen een gebeurtenis beschrijven. Koppel coin aan Currency, amount aan Amount en service aan Description. Gebruik de asset-identifier van rotki waar die afwijkt van de coincode. Zet date om naar een UTC-Unix-tijdstempel in milliseconden. Laat beide fee-velden leeg. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Gebruik de verplichte kolommen van het Universal-template.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Noteer Date als YYYY-MM-DD HH:mm:ss in UTC. Vul Received Amount met amount en Received Currency met coin. Laat beide Sent-velden leeg. Koppel bij bekende waarden local_value en local_currency aan de optionele Net Worth Amount en Net Worth Currency. Gebruik de kolom Tag voor mining of reward waar dat past. Description en TxHash zijn optioneel. [Universal-template van Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Nog geen Koinly-account? Je kunt je hier aanmelden: https://koinly.io/?via=FFF185D5. Het is een doorverwijzingslink, en het kost je niets.

### CoinTracking { #cointracking }

Zet rijen met inkomsten om naar het gewone CSV-formaat van CoinTracking. De Custom Importer vereist handelsvelden aan beide kanten, en een rij met inkomsten heeft alleen een koopkant. [Vereisten van de Custom Importer van CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Zet Type op Income of Mining, wat van toepassing is. Koppel amount aan Buy Amount, coin aan Buy Currency en service aan Comment. Laat de Sell-velden leeg. Noteer Date als DD.MM.YYYY HH:MM:SS. De export geeft de UTC-dag, dus gebruik 00:00:00 voor de tijd. Gebruik de typelabels voor de taal van je account. [Gewoon CSV-formaat van CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Nog geen CoinTracking-account? Deze aanmeldlink geeft je 10% korting op elk betaald abonnement: https://cointracking.info?ref=G962413. Het is een doorverwijzingslink. CoinTracking betaalt het CashPilot-project 20% van wat jij betaalt, en het kost jou niet meer.
