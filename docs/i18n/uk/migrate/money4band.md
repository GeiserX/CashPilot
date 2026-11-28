---
source_hash: 1a7f6b462b56
---
# Перехід з money4band { #moving-from-money4band }

CashPilot може прочитати конфігурацію money4band і перенести ваші облікові дані для входу в сервіси, тож
вам не доведеться вводити їх знову. Ви перевіряєте все, перш ніж CashPilot це збереже.

## Перш ніж почати { #before-you-start }

Вам потрібні акаунт власника CashPilot і щонайменше один воркер CashPilot на
машині, де зараз працює money4band, або на іншій машині.

Зупиніть money4band на машині, перш ніж розгортати там ті самі сервіси з
CashPilot. Дві копії за одним з'єднанням заробляють як одна, а той самий id пристрою EarnApp
чи ProxyRack не повинен працювати двічі. Скористайтеся **Stop apps stack** у
меню money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
або виконайте `docker compose down` у його теці. Якщо ви налаштували додаткові екземпляри
проксі, зупиніть і кожен із них.

## Який файл використовувати { #which-file-to-use }

Використовуйте `config/user-config.json` у своїй теці money4band. Як передати його в
CashPilot, залежить від вашої версії money4band.

У money4band 4.x money4band записує цей файл, коли ви запускаєте **Setup Apps**, і він
містить саме те, що ви ввели. `.env` поруч із ним генерується з цього файлу і теж працює,
як і відредагований вручну `.env` з money4band 3.x. Обидва залишаються лише на вашому
диску:
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
money4band їх перелічує.

money4band 5.0 шифрує `config/user-config.json` на диску
([нотатки з безпеки](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption))
і видаляє свій `.env` після кожного запуску
([збирач env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot не може прочитати зашифрований файл. Запустіть `m4b config edit` у своїй теці
money4band: ця команда відкриває розшифрований файл у вашому редакторі
([довідка CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Скопіюйте весь його текст, вставте його на сторінці імпорту, потім закрийте редактор.

Надавайте перевагу файлу JSON. У `.env` Docker Compose розгортає `$` у значеннях без лапок,
тож пароль із `$` — це не те, що показує файл. CashPilot не
вгадує: він просить вас ввести це значення ще раз.

## Як імпортувати { #how-to-import }

1. Відкрийте **Settings** (Налаштування), потім **Import from another tool** (Імпорт з іншого інструмента) (або перейдіть на `/import`).
2. Додайте `user-config.json` або вставте його текст. Залиште інструмент на **Tell from the
   files** (Визначити за файлами) або виберіть money4band.
3. Перевірте таблицю. Позначте сервіси, які вам потрібні, і заповніть усі значення, позначені
   як відсутні.
4. Натисніть **Save the ticked services** (Зберегти позначені сервіси), а потім розгорніть їх на своїх воркерах з
   тієї самої сторінки.

## Що переноситься { #what-comes-over }

Назви полів беруться з
[шаблону user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
money4band, а назви `.env` — з тих, які записує його
[генератор](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, наприклад `REPOCKET_APIKEY`). money4band 5.0 зберігає ті самі назви
полів у своєму
[каталозі застосунків](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| Застосунок money4band | Сервіс CashPilot | Що переноситься |
|---|---|---|
| `earnapp` | EarnApp | id пристрою (`uuid`), тож ваш прив'язаний пристрій продовжує заробляти |
| `honeygain` | Honeygain | email, пароль |
| `iproyalpawns` | IPRoyal Pawns | email, пароль |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | токен |
| `repocket` | Repocket | email, API-ключ |
| `earnfm` | Earn.fm | API-ключ |
| `proxyrack` | ProxyRack | API-ключ, UUID пристрою |
| `proxylite` | ProxyLite | id користувача |
| `bitping` | Bitping | email, пароль |
| `mystnode` | Mysterium | вмикається; див. примітку про Mysterium нижче |

Застосунок, який ви вимкнули в money4band, з'являється непозначеним. Застосунок, який вимкнено і
який не містить нічого, крім заповнювачів шаблону (`yourHONEYGAINMail`) і списків
портів, пропускається, тож незмінений `user-config.json` дає порожню таблицю.

Ці застосунки перелічено, але не перенесено:

| Застосунок money4band | Чому |
|---|---|
| `proxybase` | money4band запускає старий клієнт ProxyBase з id користувача. CashPilot запускає поточний, якому потрібен Access Token з proxybase.org. |
| `urnetwork` | money4band зберігає токен сеансу. CashPilot входить в URnetwork з вашими email і паролем. |
| `grass` | Grass працює як розширення браузера. CashPilot лише відстежує його за допомогою токена доступу з панелі Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot відстежує їх, але контейнера для розгортання немає. |
| `packetshare`, `peer2profit`, `speedshare` | Більше не доступні. |

Будь-який інший застосунок позначено як **CashPilot has no such service** (У CashPilot немає такого сервісу).

## Що ніколи не переноситься { #what-never-comes-over }

- **Назва пристрою.** CashPilot називає кожен пристрій за воркером, на якому він працює, тож
  два воркери ніколи не повідомляють однакову назву. Ваші старі пристрої залишаються в списку як
  офлайн на панелі кожного провайдера, доки ви не видалите їх там.
- **Проксі.** Додайте кожен у розділі **Proxies** (Проксі) сторінки **Fleet** (Парк), а потім запустіть
  через нього копії своїх сервісів; додавання проксі саме по собі нічого не запускає.
  Збереження імпорту теж нічого не запускає. Копія через проксі потребує, щоб той самий сервіс
  спершу був розгорнутий на воркері, а його розгортання запускає його через власне
  з'єднання воркера, тож сервіс, який ніколи не повинен використовувати це з'єднання, слід залишити
  непозначеним. Див. [Копії через проксі](../proxies.md).
- **Watchtower і сповіщення.** CashPilot сам оновлює свої контейнери.
- **Панель money4band та її порти.**

## Відстеження заробітку { #earnings-tracking }

Для Honeygain, IPRoyal Pawns і Bitping логін контейнера — це також логін
акаунта, тож CashPilot заповнює й облікові дані для збирання їхнього заробітку, якщо ви
ще не задали їх у **Settings** (Налаштування). Для кожного іншого сервісу додайте логін для заробітку
в **Settings > Earnings collection** (Налаштування > Збирання заробітку).

## Mysterium { #mysterium }

Імпорт вмикає Mysterium, але CashPilot запускає новий вузол із новим
ідентифікатором. Сховище ключів старого вузла та будь-який нерозрахований заробіток залишаються в
теці `.data/mysterium-node` money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Спершу розрахуйте їх або скористайтеся
[посібником із Mysterium](../guides/mysterium.md), щоб перенести ідентифікатор.

`.env` версії 3.x не може сказати, чи ви запускали Mysterium: його шаблон завжди
містить порт панелі. З файлу 3.x Mysterium не імпортується, тож додайте
його з каталогу, якщо ви його запускали.

## Безпека { #safety }

- Ніщо у файлі не виконується і не розгортається, і жодна адреса в ньому не завантажується.
- Файл читається один раз і не зберігається. Те, що ви зберігаєте, зберігається зашифрованим, як
  і всі інші облікові дані в CashPilot.
- Секрети на сторінці показуються лише як **set** (задано).
- Збережені імпорти залишаються на сторінці імпорту, доки ви не натиснете **Forget** (Забути), тож ви можете
  пізніше розгорнути їх на інших воркерах.
