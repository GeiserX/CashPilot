# Income export for taxes

Open **Payouts**, find **Income for taxes**, and select a date range and currency. **This year** runs through today, and **Last year** covers the previous calendar year. Leave the dates blank to export the available history through today. CashPilot uses UTC dates and includes both ends of the range.

CashPilot deletes earnings readings 400 days after recording them. The CSV uses the history that remains, so a past year can contain only part of its earned or accrued income.

## Choose an accounting basis

- **Cash basis.** Use payout rows. They record money that the service paid out. CashPilot includes only confirmed payouts.
- **Accrual basis.** Use earned and accrued rows. Earned rows show credit that you can withdraw on the service's terms. Accrued rows show unpaid pool credit that the pool may never pay.

Use one basis for the same income. Adding payout rows to the earned and accrued rows can count the same money twice. Check which basis applies to your filing.

## CSV columns

| Column | Meaning |
|---|---|
| date | UTC day of the later reading or the payout. A payout uses the date you entered or the day CashPilot detected it. |
| period_start | UTC day of the previous reading for this service and source. Blank for payouts. A gap between readings means the amount covers the whole interval. |
| kind | earned, accrued or payout. |
| service | CashPilot service ID. |
| coin | Currency or token code as recorded by CashPilot. |
| amount | Amount in that currency or token. |
| usd_rate | Number of US dollars per unit of coin. |
| usd_value | Amount valued in US dollars. |
| local_currency | Fiat currency you selected for the export. |
| local_rate | Units of your selected currency per US dollar. |
| local_value | Amount valued in your selected currency. |
| method | Payout method, if recorded. |

A blank valuation means the rate was unavailable. The native amount is still present. CashPilot skips internal points such as Grass points in earnings readings. The first reading per source provides an opening balance. Later rows record increases, so the CSV can begin after the oldest reading in the selected range.

If more than one source reads the same account, the CSV can count that income more than once.

The USD rate comes from the later reading or from the payout record. When CashPilot backfills a reading's price, it uses CoinGecko's price at 00:00 UTC for that day. CashPilot uses the most recent ECB reference rate on or before the row's day to convert USD to your selected currency. This covers weekends, holidays and days when the ECB has yet to publish its rate. [Frankfurter daily rates](https://frankfurter.dev/v1/)

Frankfurter lists these currencies for the export. [Supported currencies](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR and ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD and ZAR.

Choose USD if your currency is outside that list or Frankfurter is unavailable.

## Import into another tool

Convert the CSV to the tool's format before importing. Choose the rows for your accounting basis first. Skip payout rows for a wallet the tool already syncs.

### rotki

Use Generic Events with these headers.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Set Type to Income and Location to external. rotki also accepts Deposit, Withdrawal, Loss, Spend and Staking when those types describe an event. Map coin to Currency, amount to Amount and service to Description. Use rotki's asset identifier where it differs from the coin code. Convert date to a UTC Unix timestamp in milliseconds. Leave both fee fields blank. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly

Use the Universal template's required columns.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Format Date as YYYY-MM-DD HH:mm:ss in UTC. Set Received Amount from amount and Received Currency from coin. Leave both Sent fields blank. For known values, map local_value and local_currency to the optional Net Worth Amount and Net Worth Currency. Use the Tag column for mining or reward where appropriate. Description and TxHash are optional. [Koinly Universal template](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

No Koinly account yet? You can sign up here: https://koinly.io/?via=FFF185D5. It is a referral link, and it costs you nothing.

### CoinTracking

Convert income rows to CoinTracking's regular CSV format. The Custom Importer requires trade fields on both sides, and an income row has only a buy side. [CoinTracking Custom Importer requirements](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Set Type to Income or Mining as appropriate. Map amount to Buy Amount, coin to Buy Currency and service to Comment. Leave the Sell fields blank. Format Date as DD.MM.YYYY HH:MM:SS. The export provides the UTC day, so use 00:00:00 for the time. Use the type labels for your account language. [CoinTracking regular CSV format](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

No CoinTracking account yet? This signup link gives you 10% off every paid plan: https://cointracking.info?ref=G962413. It is a referral link. CoinTracking pays the CashPilot project 20% of what you pay, and it does not cost you more.
