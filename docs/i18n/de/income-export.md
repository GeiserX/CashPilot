---
source_hash: 38029ca1a5d6
---
# Einnahmen-Export für die Steuer { #income-export-for-taxes }

Öffne **Payouts** (Auszahlungen), such **Income for taxes** (Einnahmen für die Steuer) und wähle einen Zeitraum und eine Währung. **This year** (Dieses Jahr) reicht bis heute, und **Last year** (Letztes Jahr) umfasst das vorige Kalenderjahr. Lass die Daten leer, um die verfügbare Historie bis heute zu exportieren. CashPilot verwendet UTC-Daten und schließt beide Enden des Zeitraums ein.

CashPilot löscht Einnahmen-Messwerte 400 Tage nach ihrer Aufzeichnung. Die CSV verwendet die verbleibende Historie, daher kann ein vergangenes Jahr nur einen Teil seiner verdienten oder aufgelaufenen Einnahmen enthalten.

## Wähle eine Buchungsgrundlage { #choose-an-accounting-basis }

- **Zuflussprinzip.** Verwende die Auszahlungszeilen. Sie erfassen Geld, das der Dienst ausgezahlt hat. CashPilot nimmt nur bestätigte Auszahlungen auf.
- **Periodenabgrenzung.** Verwende die verdienten und aufgelaufenen Zeilen. Verdiente Zeilen zeigen Guthaben, das du nach den Bedingungen des Dienstes auszahlen kannst. Aufgelaufene Zeilen zeigen unbezahltes Pool-Guthaben, das der Pool vielleicht nie zahlt.

Verwende für dieselben Einnahmen eine einzige Grundlage. Fügst du Auszahlungszeilen zu den verdienten und aufgelaufenen Zeilen hinzu, kann dasselbe Geld doppelt gezählt werden. Prüfe, welche Grundlage für deine Steuererklärung gilt.

## CSV-Spalten { #csv-columns }

| Spalte | Bedeutung |
|---|---|
| date | UTC-Tag des späteren Messwerts oder der Auszahlung. Eine Auszahlung verwendet das Datum, das du eingegeben hast, oder den Tag, an dem CashPilot sie erkannt hat. |
| period_start | UTC-Tag des vorherigen Messwerts für diesen Dienst und diese Quelle. Bei Auszahlungen leer. Eine Lücke zwischen Messwerten bedeutet, dass der Betrag den ganzen Zeitraum abdeckt. |
| kind | earned, accrued oder payout. |
| service | Dienst-ID in CashPilot. |
| coin | Währungs- oder Token-Code, wie CashPilot ihn aufgezeichnet hat. |
| amount | Betrag in dieser Währung oder diesem Token. |
| usd_rate | Anzahl US-Dollar pro Einheit von coin. |
| usd_value | Betrag, bewertet in US-Dollar. |
| local_currency | Fiat-Währung, die du für den Export gewählt hast. |
| local_rate | Einheiten deiner gewählten Währung pro US-Dollar. |
| local_value | Betrag, bewertet in deiner gewählten Währung. |
| method | Auszahlungsmethode, falls aufgezeichnet. |

Eine leere Bewertung bedeutet, dass der Kurs nicht verfügbar war. Der native Betrag ist trotzdem vorhanden. CashPilot überspringt interne Punkte wie Grass-Punkte in den Einnahmen-Messwerten. Der erste Messwert pro Quelle liefert einen Anfangsbestand. Spätere Zeilen erfassen Zuwächse, daher kann die CSV nach dem ältesten Messwert im gewählten Zeitraum beginnen.

Liest mehr als eine Quelle dasselbe Konto, kann die CSV diese Einnahmen mehr als einmal zählen.

Der USD-Kurs stammt aus dem späteren Messwert oder aus dem Auszahlungsdatensatz. Ergänzt CashPilot nachträglich den Preis eines Messwerts, verwendet es den Preis von CoinGecko um 00:00 UTC an diesem Tag. Um USD in deine gewählte Währung umzurechnen, verwendet CashPilot den jüngsten Referenzkurs der EZB am Tag der Zeile oder davor. Das deckt Wochenenden, Feiertage und Tage ab, an denen die EZB ihren Kurs noch nicht veröffentlicht hat. [Tageskurse von Frankfurter](https://frankfurter.dev/v1/)

Frankfurter führt diese Währungen für den Export. [Unterstützte Währungen](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR und ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD und ZAR.

Wähle USD, wenn deine Währung nicht in dieser Liste steht oder Frankfurter nicht verfügbar ist.

## In ein anderes Werkzeug importieren { #import-into-another-tool }

Wandle die CSV vor dem Import in das Format des Werkzeugs um. Wähle zuerst die Zeilen für deine Buchungsgrundlage. Lass Auszahlungszeilen für eine Wallet weg, die das Werkzeug bereits synchronisiert.

### rotki { #rotki }

Verwende Generic Events mit diesen Kopfzeilen.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Setze Type auf Income und Location auf external. rotki akzeptiert auch Deposit, Withdrawal, Loss, Spend und Staking, wenn diese Typen ein Ereignis beschreiben. Ordne coin dem Feld Currency zu, amount dem Feld Amount und service dem Feld Description. Verwende die Asset-Kennung von rotki, wo sie vom Coin-Code abweicht. Wandle date in einen UTC-Unix-Zeitstempel in Millisekunden um. Lass beide Gebührenfelder leer. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Verwende die Pflichtspalten der Universal-Vorlage.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Formatiere Date als YYYY-MM-DD HH:mm:ss in UTC. Setze Received Amount aus amount und Received Currency aus coin. Lass beide Sent-Felder leer. Bei bekannten Werten ordnest du local_value und local_currency den optionalen Feldern Net Worth Amount und Net Worth Currency zu. Verwende die Spalte Tag für mining oder reward, wo es passt. Description und TxHash sind optional. [Koinly-Universal-Vorlage](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Noch kein Koinly-Konto? Hier kannst du dich registrieren: https://koinly.io/?via=FFF185D5. Das ist ein Empfehlungslink, und er kostet dich nichts.

### CoinTracking { #cointracking }

Wandle Einnahmezeilen in das reguläre CSV-Format von CoinTracking um. Der Custom Importer verlangt Handelsfelder auf beiden Seiten, und eine Einnahmezeile hat nur eine Kaufseite. [Anforderungen des CoinTracking Custom Importer](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Setze Type je nach Fall auf Income oder Mining. Ordne amount dem Feld Buy Amount zu, coin dem Feld Buy Currency und service dem Feld Comment. Lass die Sell-Felder leer. Formatiere Date als DD.MM.YYYY HH:MM:SS. Der Export liefert den UTC-Tag, verwende also 00:00:00 als Uhrzeit. Verwende die Typbezeichnungen in der Sprache deines Kontos. [Reguläres CSV-Format von CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Noch kein CoinTracking-Konto? Dieser Registrierungslink gibt dir 10 % Rabatt auf jeden kostenpflichtigen Tarif: https://cointracking.info?ref=G962413. Das ist ein Empfehlungslink. CoinTracking zahlt dem CashPilot-Projekt 20 % von dem, was du zahlst, und es kostet dich nicht mehr.
