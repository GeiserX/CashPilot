---
source_hash: 38029ca1a5d6
---
# Експорт доходу для податків { #income-export-for-taxes }

Відкрийте **Payouts** (Виплати), знайдіть **Income for taxes** (Дохід для податків) і виберіть діапазон дат і валюту. **This year** (Цей рік) охоплює період до сьогодні включно, а **Last year** (Минулий рік) — попередній календарний рік. Залиште дати порожніми, щоб експортувати доступну історію до сьогодні. CashPilot використовує дати в UTC і включає обидва кінці діапазону.

CashPilot видаляє показники заробітку через 400 днів після запису. CSV використовує історію, що залишилася, тому минулий рік може містити лише частину заробленого чи нарахованого доходу.

## Виберіть метод обліку { #choose-an-accounting-basis }

- **Касовий метод.** Використовуйте рядки виплат. Вони фіксують гроші, які сервіс виплатив. CashPilot включає лише підтверджені виплати.
- **Метод нарахування.** Використовуйте зароблені та нараховані рядки. Зароблені рядки показують кредит, який ви можете вивести на умовах сервісу. Нараховані рядки показують невиплачений кредит пулу, який пул може так і не виплатити.

Для того самого доходу використовуйте один метод. Якщо додати рядки виплат до зароблених і нарахованих рядків, ті самі гроші можна порахувати двічі. Перевірте, який метод застосовується до вашої декларації.

## Стовпці CSV { #csv-columns }

| Стовпець | Значення |
|---|---|
| date | День за UTC пізнішого показника або виплати. Для виплати це дата, яку ви ввели, або день, коли CashPilot її виявив. |
| period_start | День за UTC попереднього показника для цього сервісу та джерела. Порожній для виплат. Проміжок між показниками означає, що сума охоплює весь інтервал. |
| kind | earned, accrued або payout. |
| service | ID сервісу в CashPilot. |
| coin | Код валюти чи токена, як його записав CashPilot. |
| amount | Сума в цій валюті чи токені. |
| usd_rate | Кількість доларів США за одиницю coin. |
| usd_value | Сума, оцінена в доларах США. |
| local_currency | Фіатна валюта, яку ви вибрали для експорту. |
| local_rate | Одиниць вибраної валюти за один долар США. |
| local_value | Сума, оцінена у вибраній вами валюті. |
| method | Спосіб виплати, якщо його записано. |

Порожня оцінка означає, що курс був недоступний. Сума в рідній валюті все одно присутня. CashPilot пропускає внутрішні бали, як-от бали Grass, у показниках заробітку. Перший показник для кожного джерела дає початковий баланс. Наступні рядки фіксують збільшення, тому CSV може починатися пізніше за найстаріший показник у вибраному діапазоні.

Якщо той самий акаунт читає більше ніж одне джерело, CSV може порахувати цей дохід більше одного разу.

Курс USD береться з пізнішого показника або із запису виплати. Коли CashPilot заднім числом заповнює ціну показника, він використовує ціну CoinGecko на 00:00 UTC того дня. Щоб перевести USD у вибрану вами валюту, CashPilot використовує найсвіжіший довідковий курс ЄЦБ на день рядка або раніше. Це охоплює вихідні, свята і дні, коли ЄЦБ ще не опублікував свій курс. [Щоденні курси Frankfurter](https://frankfurter.dev/v1/)

Frankfurter пропонує для експорту такі валюти. [Підтримувані валюти](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR і ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD і ZAR.

Виберіть USD, якщо вашої валюти немає в цьому списку або Frankfurter недоступний.

## Імпорт в інший інструмент { #import-into-another-tool }

Перед імпортом перетворіть CSV у формат інструмента. Спершу виберіть рядки для свого методу обліку. Пропустіть рядки виплат для гаманця, який інструмент уже синхронізує.

### rotki { #rotki }

Використовуйте Generic Events з такими заголовками.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Задайте Type як Income, а Location як external. rotki також приймає Deposit, Withdrawal, Loss, Spend і Staking, коли ці типи описують подію. Зіставте coin з Currency, amount з Amount, а service з Description. Використовуйте ідентифікатор активу rotki там, де він відрізняється від коду coin. Перетворіть date на часову позначку Unix в UTC у мілісекундах. Залиште обидва поля комісії порожніми. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Використовуйте обов'язкові стовпці шаблону Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Форматуйте Date як YYYY-MM-DD HH:mm:ss в UTC. Заповніть Received Amount з amount, а Received Currency з coin. Залиште обидва поля Sent порожніми. Для відомих значень зіставте local_value і local_currency з необов'язковими Net Worth Amount і Net Worth Currency. Використовуйте стовпець Tag для mining або reward, де це доречно. Description і TxHash необов'язкові. [Шаблон Koinly Universal](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Ще немає акаунта Koinly? Зареєструватися можна тут: https://koinly.io/?via=FFF185D5. Це реферальне посилання, і вам воно нічого не коштує.

### CoinTracking { #cointracking }

Перетворіть рядки доходу у звичайний формат CSV CoinTracking. Custom Importer вимагає полів угоди з обох сторін, а рядок доходу має лише сторону купівлі. [Вимоги CoinTracking Custom Importer](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Задайте Type як Income або Mining, залежно від ситуації. Зіставте amount з Buy Amount, coin з Buy Currency, а service з Comment. Залиште поля Sell порожніми. Форматуйте Date як DD.MM.YYYY HH:MM:SS. Експорт дає день за UTC, тому для часу використовуйте 00:00:00. Використовуйте назви типів мовою вашого акаунта. [Звичайний формат CSV CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Ще немає акаунта CoinTracking? Це посилання для реєстрації дає вам знижку 10% на кожен платний тариф: https://cointracking.info?ref=G962413. Це реферальне посилання. CoinTracking платить проєкту CashPilot 20% від того, що платите ви, і вам це не коштує більше.
