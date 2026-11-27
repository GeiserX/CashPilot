---
source_hash: ca9dd25d45ca
---
# Перехід з InternetIncome { #moving-from-internetincome }

CashPilot може прочитати `properties.conf` InternetIncome і файли, у яких
він зберігає id ваших пристроїв EarnApp і ProxyRack, і перенести їх. Ви перевіряєте
все, перш ніж CashPilot це збереже.

## Перш ніж почати { #before-you-start }

Вам потрібні акаунт власника CashPilot і щонайменше один воркер CashPilot.

Зупиніть InternetIncome на машині, перш ніж розгортати там ті самі сервіси з
CashPilot. Дві копії за одним з'єднанням заробляють як одна, а той самий id пристрою
не повинен працювати двічі. У теці InternetIncome виконайте:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` видаляє контейнери і залишає `earnapp.txt`, `proxyrack.txt` і
теку даних Mysterium. `--deleteBackup` видаляє і їх
([internetIncome.sh, рядки 61–64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
і [рядок 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
тож спершу імпортуйте.

## Які файли використовувати { #which-files-to-use }

З теки InternetIncome:

- `properties.conf`, ваші налаштування.
- `earnapp.txt`, якщо ви запускали EarnApp. Кожен рядок містить посилання на пристрій
  ([рядки 1250–1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, якщо ви запускали ProxyRack. Один UUID пристрою на рядок
  ([рядки 817–827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot бере перший пристрій у кожному файлі: той, який використовував ваш основний контейнер,
і той, який ви прив'язали до свого акаунта. Інші рядки належали копіям через
проксі, і сторінка повідомляє, скільки рядків вона пропустила.

InternetIncome пропускає кожне значення через оболонку
([рядок 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Значення в одинарних лапках береться як написано, як радять коментарі в
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Значення поза одинарними лапками, яке містить `$`, зворотний апостроф, пробіл або
інший символ, що його змінила б оболонка, — це не те, що показує файл, тому
CashPilot просить вас ввести його ще раз, а не запускає оболонку, щоб це з'ясувати.

## Як імпортувати { #how-to-import }

1. Відкрийте **Settings** (Налаштування), потім **Import from another tool** (Імпорт з іншого інструмента) (або перейдіть на `/import`).
2. Додайте `properties.conf`, а також `earnapp.txt` і `proxyrack.txt`, якщо вони
   у вас є. Залиште інструмент на **Tell from the files** (Визначити за файлами) або виберіть InternetIncome.
3. Перевірте таблицю. Позначте сервіси, які вам потрібні, і заповніть усі значення, позначені
   як відсутні. Repocket потребує email вашого акаунта, якого InternetIncome ніколи не
   запитував.
4. Натисніть **Save the ticked services** (Зберегти позначені сервіси), а потім розгорніть їх на своїх воркерах з
   тієї самої сторінки.

## Що переноситься { #what-comes-over }

| Застосунок InternetIncome | Ключі, що читаються | Сервіс CashPilot | Що переноситься |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API-ключ (додайте свій email) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | токен |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API-ключ, UUID пристрою |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, пароль |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, пароль |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id користувача |
| `earnfm` | `EARN_FM_API` | Earn.fm | API-ключ |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id пристрою |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, пароль |
| `mysterium` | `MYSTERIUM=true` | Mysterium | вмикається; див. примітку про Mysterium нижче |

Порожнє значення означає, що застосунок був вимкнений, і його не перелічено.

Ці застосунки перелічено, але не перенесено:

| Застосунок InternetIncome | Чому |
|---|---|
| `urnetwork` | InternetIncome використовує токен сеансу. CashPilot входить в URnetwork з вашими email і паролем. |
| `grass` | Grass працює як розширення браузера. CashPilot лише відстежує його за допомогою токена доступу з панелі Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot відстежує їх, але контейнера для розгортання немає. |
| `peer2profit` | Більше не доступний. |

Налаштування застосунків, яких немає в CashPilot (antGain, Adnade та інші),
перелічено за назвою як непрочитані.

## Що ніколи не переноситься { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot називає кожен пристрій за воркером, на якому він працює, тож
  два воркери ніколи не повідомляють однакову назву. Ваші старі пристрої залишаються в списку як
  офлайн на панелі кожного провайдера, доки ви не видалите їх там.
- **Проксі** (`USE_PROXIES`, `proxies.txt`). Додайте кожен у розділі **Proxies** (Проксі)
  сторінки **Fleet** (Парк), а потім запустіть через нього копії своїх сервісів; додавання
  проксі саме по собі нічого не запускає. З `USE_PROXIES=true` InternetIncome запускав
  ваші сервіси лише через проксі. Збереження імпорту теж нічого не запускає.
  Копія через проксі потребує, щоб той самий сервіс спершу був розгорнутий на воркері, а
  його розгортання запускає його через власне з'єднання воркера, тож сервіс, який
  ніколи не повинен використовувати це з'єднання, слід залишити непозначеним. Див. [Копії
  через проксі](../proxies.md).
- **`BROWSER_USERNAME` і `BROWSER_PASSWORD`**, власний логін браузера
  InternetIncome.

## Відстеження заробітку { #earnings-tracking }

Для Honeygain, IPRoyal Pawns і Bitping логін контейнера — це також логін
акаунта, тож CashPilot заповнює й облікові дані для збирання їхнього заробітку, якщо ви
ще не задали їх у **Settings** (Налаштування). Для кожного іншого сервісу додайте логін для заробітку
в **Settings > Earnings collection** (Налаштування > Збирання заробітку).

## Mysterium { #mysterium }

Імпорт вмикає Mysterium, але CashPilot запускає новий вузол із новим
ідентифікатором. Сховище ключів старого вузла та будь-який нерозрахований заробіток залишаються в
теці `mysterium-data` InternetIncome. Спершу розрахуйте їх або скористайтеся
[посібником із Mysterium](../guides/mysterium.md), щоб перенести ідентифікатор.

## Безпека { #safety }

- Ніщо у файлах не виконується і не розгортається, і жодна адреса в них не завантажується.
- Файли читаються один раз і не зберігаються. Те, що ви зберігаєте, зберігається зашифрованим, як
  і всі інші облікові дані в CashPilot.
- Секрети на сторінці показуються лише як **set** (задано).
- Збережені імпорти залишаються на сторінці імпорту, доки ви не натиснете **Forget** (Забути), тож ви можете
  пізніше розгорнути їх на інших воркерах.
