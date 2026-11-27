---
source_hash: 38029ca1a5d6
---
# Eksport dochodów do celów podatkowych { #income-export-for-taxes }

Otwórz **Payouts** (Wypłaty), znajdź **Income for taxes** (Dochody do celów podatkowych) i wybierz zakres dat oraz walutę. **This year** (Ten rok) obejmuje okres do dzisiaj, a **Last year** (Zeszły rok) poprzedni rok kalendarzowy. Zostaw daty puste, aby wyeksportować dostępną historię do dzisiaj. CashPilot używa dat UTC i uwzględnia oba końce zakresu.

CashPilot usuwa odczyty zarobków 400 dni po ich zapisaniu. CSV korzysta z historii, która została, więc miniony rok może zawierać tylko część dochodu zarobionego lub naliczonego.

## Wybierz metodę ewidencji { #choose-an-accounting-basis }

- **Metoda kasowa.** Używaj wierszy wypłat. Zapisują pieniądze, które usługa wypłaciła. CashPilot uwzględnia tylko potwierdzone wypłaty.
- **Metoda memoriałowa.** Używaj wierszy zarobionych i naliczonych. Wiersze zarobione pokazują środki, które możesz wypłacić na warunkach usługi. Wiersze naliczone pokazują niewypłacone środki w puli, których pula może nigdy nie wypłacić.

Dla tego samego dochodu stosuj jedną metodę. Dodanie wierszy wypłat do wierszy zarobionych i naliczonych może policzyć te same pieniądze dwa razy. Sprawdź, która metoda dotyczy twojego zeznania.

## Kolumny CSV { #csv-columns }

| Kolumna | Znaczenie |
|---|---|
| date | Dzień UTC późniejszego odczytu lub wypłaty. Wypłata ma datę, którą wpisałeś, albo dzień, w którym CashPilot ją wykrył. |
| period_start | Dzień UTC poprzedniego odczytu dla tej usługi i źródła. Puste dla wypłat. Luka między odczytami oznacza, że kwota obejmuje cały ten okres. |
| kind | earned, accrued lub payout. |
| service | Identyfikator usługi w CashPilot. |
| coin | Kod waluty lub tokena zapisany przez CashPilot. |
| amount | Kwota w tej walucie lub tokenie. |
| usd_rate | Liczba dolarów amerykańskich za jednostkę coin. |
| usd_value | Kwota wyceniona w dolarach amerykańskich. |
| local_currency | Waluta fiat wybrana do eksportu. |
| local_rate | Liczba jednostek wybranej waluty za jednego dolara amerykańskiego. |
| local_value | Kwota wyceniona w wybranej walucie. |
| method | Metoda wypłaty, jeśli została zapisana. |

Pusta wycena oznacza, że kurs był niedostępny. Kwota w walucie natywnej nadal jest podana. CashPilot pomija w odczytach zarobków wewnętrzne punkty, takie jak punkty Grass. Pierwszy odczyt dla każdego źródła daje saldo otwarcia. Kolejne wiersze zapisują wzrosty, więc CSV może zaczynać się po najstarszym odczycie w wybranym zakresie.

Jeśli to samo konto odczytuje więcej niż jedno źródło, CSV może policzyć ten dochód więcej niż raz.

Kurs USD pochodzi z późniejszego odczytu lub z zapisu wypłaty. Gdy CashPilot uzupełnia cenę odczytu wstecz, używa ceny CoinGecko z godziny 00:00 UTC tego dnia. Do przeliczenia USD na wybraną walutę CashPilot używa najnowszego kursu referencyjnego EBC z dnia wiersza lub wcześniejszego. Obejmuje to weekendy, święta i dni, w których EBC jeszcze nie opublikował kursu. [Dzienne kursy Frankfurter](https://frankfurter.dev/v1/)

Frankfurter udostępnia do eksportu te waluty. [Obsługiwane waluty](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR i ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD i ZAR.

Wybierz USD, jeśli twojej waluty nie ma na tej liście albo Frankfurter jest niedostępny.

## Import do innego narzędzia { #import-into-another-tool }

Przed importem przekonwertuj CSV do formatu narzędzia. Najpierw wybierz wiersze dla swojej metody ewidencji. Pomiń wiersze wypłat dla portfela, który narzędzie już synchronizuje.

### rotki { #rotki }

Użyj Generic Events z tymi nagłówkami.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Ustaw Type na Income, a Location na external. rotki przyjmuje też Deposit, Withdrawal, Loss, Spend i Staking, gdy te typy opisują zdarzenie. Przypisz coin do Currency, amount do Amount, a service do Description. Używaj identyfikatora zasobu rotki tam, gdzie różni się od kodu coin. Przekonwertuj date na uniksowy znacznik czasu UTC w milisekundach. Oba pola opłat zostaw puste. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Użyj wymaganych kolumn szablonu Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Sformatuj Date jako YYYY-MM-DD HH:mm:ss w UTC. Ustaw Received Amount z amount, a Received Currency z coin. Oba pola Sent zostaw puste. Dla znanych wartości przypisz local_value i local_currency do opcjonalnych Net Worth Amount i Net Worth Currency. W kolumnie Tag użyj mining lub reward, gdy to pasuje. Description i TxHash są opcjonalne. [Szablon Universal w Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Nie masz jeszcze konta Koinly? Możesz zarejestrować się tutaj: https://koinly.io/?via=FFF185D5. To link polecający i nic cię nie kosztuje.

### CoinTracking { #cointracking }

Przekonwertuj wiersze dochodów do zwykłego formatu CSV CoinTracking. Custom Importer wymaga pól transakcji po obu stronach, a wiersz dochodu ma tylko stronę kupna. [Wymagania Custom Importer w CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Ustaw Type na Income lub Mining, zależnie od przypadku. Przypisz amount do Buy Amount, coin do Buy Currency, a service do Comment. Pola Sell zostaw puste. Sformatuj Date jako DD.MM.YYYY HH:MM:SS. Eksport podaje dzień UTC, więc jako godzinę użyj 00:00:00. Używaj etykiet typów w języku swojego konta. [Zwykły format CSV CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Nie masz jeszcze konta CoinTracking? Ten link rejestracyjny daje 10% zniżki na każdy płatny plan: https://cointracking.info?ref=G962413. To link polecający. CoinTracking płaci projektowi CashPilot 20% tego, co zapłacisz, a ciebie nie kosztuje to więcej.
