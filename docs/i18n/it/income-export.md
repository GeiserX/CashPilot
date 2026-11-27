---
source_hash: 38029ca1a5d6
---
# Esportazione dei redditi per le tasse { #income-export-for-taxes }

Apri **Payouts** (Pagamenti), trova **Income for taxes** (Redditi per le tasse) e scegli un intervallo di date e una valuta. **This year** (Quest'anno) arriva fino a oggi, e **Last year** (Anno scorso) copre l'anno solare precedente. Lascia vuote le date per esportare lo storico disponibile fino a oggi. CashPilot usa date UTC e include entrambi gli estremi dell'intervallo.

CashPilot elimina le letture dei guadagni 400 giorni dopo averle registrate. Il CSV usa lo storico che resta, quindi un anno passato può contenere solo una parte dei suoi redditi guadagnati o maturati.

## Scegli un criterio contabile { #choose-an-accounting-basis }

- **Criterio di cassa.** Usa le righe dei pagamenti. Registrano i soldi che il servizio ha pagato. CashPilot include solo i pagamenti confermati.
- **Criterio di competenza.** Usa le righe guadagnate e maturate. Le righe guadagnate mostrano il credito che puoi prelevare secondo i termini del servizio. Le righe maturate mostrano il credito non pagato del pool, che il pool potrebbe non pagare mai.

Usa un solo criterio per lo stesso reddito. Aggiungere le righe dei pagamenti alle righe guadagnate e maturate può contare due volte gli stessi soldi. Verifica quale criterio vale per la tua dichiarazione.

## Colonne del CSV { #csv-columns }

| Colonna | Significato |
|---|---|
| date | Giorno UTC della lettura successiva o del pagamento. Un pagamento usa la data che hai inserito o il giorno in cui CashPilot l'ha rilevato. |
| period_start | Giorno UTC della lettura precedente per questo servizio e questa fonte. Vuoto per i pagamenti. Uno spazio tra due letture significa che l'importo copre l'intero intervallo. |
| kind | earned (guadagnato), accrued (maturato) o payout (pagamento). |
| service | ID del servizio in CashPilot. |
| coin | Codice della valuta o del token come registrato da CashPilot. |
| amount | Importo in quella valuta o in quel token. |
| usd_rate | Numero di dollari USA per unità di coin. |
| usd_value | Importo valutato in dollari USA. |
| local_currency | Valuta fiat che hai scelto per l'esportazione. |
| local_rate | Unità della valuta scelta per ogni dollaro USA. |
| local_value | Importo valutato nella valuta scelta. |
| method | Metodo di pagamento, se registrato. |

Una valutazione vuota significa che il tasso non era disponibile. L'importo nativo è comunque presente. CashPilot salta i punti interni, come i punti di Grass, nelle letture dei guadagni. La prima lettura di ogni fonte fornisce un saldo di apertura. Le righe successive registrano gli aumenti, quindi il CSV può iniziare dopo la lettura più vecchia dell'intervallo scelto.

Se più di una fonte legge lo stesso account, il CSV può contare quel reddito più di una volta.

Il tasso in USD viene dalla lettura successiva o dalla registrazione del pagamento. Quando CashPilot ricostruisce a posteriori il prezzo di una lettura, usa il prezzo di CoinGecko alle 00:00 UTC di quel giorno. Per convertire gli USD nella valuta scelta, CashPilot usa il tasso di riferimento BCE più recente pari o precedente al giorno della riga. Questo copre i fine settimana, i festivi e i giorni in cui la BCE non ha ancora pubblicato il suo tasso. [Tassi giornalieri di Frankfurter](https://frankfurter.dev/v1/)

Frankfurter elenca queste valute per l'esportazione. [Valute supportate](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR e ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD e ZAR.

Scegli USD se la tua valuta non è in quell'elenco o se Frankfurter non è disponibile.

## Importare in un altro strumento { #import-into-another-tool }

Converti il CSV nel formato dello strumento prima di importarlo. Prima scegli le righe del tuo criterio contabile. Salta le righe dei pagamenti per un wallet che lo strumento sincronizza già.

### rotki { #rotki }

Usa Generic Events con queste intestazioni.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Imposta Type su Income e Location su external. rotki accetta anche Deposit, Withdrawal, Loss, Spend e Staking quando quei tipi descrivono un evento. Associa coin a Currency, amount ad Amount e service a Description. Usa l'identificatore dell'asset di rotki dove è diverso dal codice di coin. Converti date in un timestamp Unix UTC in millisecondi. Lascia vuoti entrambi i campi della commissione. [Generic Events di rotki](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Usa le colonne obbligatorie del Universal template.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Formatta Date come YYYY-MM-DD HH:mm:ss in UTC. Imposta Received Amount da amount e Received Currency da coin. Lascia vuoti entrambi i campi Sent. Per i valori noti, associa local_value e local_currency ai campi facoltativi Net Worth Amount e Net Worth Currency. Usa la colonna Tag per mining o reward dove opportuno. Description e TxHash sono facoltativi. [Universal template di Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Non hai ancora un account Koinly? Puoi registrarti qui: https://koinly.io/?via=FFF185D5. È un link referral e non ti costa nulla.

### CoinTracking { #cointracking }

Converti le righe dei redditi nel formato CSV normale di CoinTracking. Il Custom Importer richiede i campi della transazione su entrambi i lati, e una riga di reddito ha solo il lato di acquisto. [Requisiti del Custom Importer di CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Imposta Type su Income o Mining secondo il caso. Associa amount a Buy Amount, coin a Buy Currency e service a Comment. Lascia vuoti i campi Sell. Formatta Date come DD.MM.YYYY HH:MM:SS. L'esportazione fornisce il giorno UTC, quindi usa 00:00:00 come ora. Usa le etichette dei tipi nella lingua del tuo account. [Formato CSV normale di CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Non hai ancora un account CoinTracking? Questo link di registrazione ti dà il 10% di sconto su ogni piano a pagamento: https://cointracking.info?ref=G962413. È un link referral. CoinTracking paga al progetto CashPilot il 20% di quello che paghi tu, e a te non costa di più.
