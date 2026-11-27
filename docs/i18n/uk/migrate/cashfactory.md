---
source_hash: 7f8476aeb8b6
---
# Перехід з CashFactory { #moving-from-cashfactory }

CashPilot може прочитати `.env` CashFactory і перенести ваші облікові дані для входу в сервіси, тож
вам не доведеться вводити їх знову. Ви перевіряєте все, перш ніж CashPilot це збереже.

## Перш ніж почати { #before-you-start }

Вам потрібні акаунт власника CashPilot і щонайменше один воркер CashPilot.

Зупиніть CashFactory на машині, перш ніж розгортати там ті самі сервіси з
CashPilot. Дві копії за одним з'єднанням заробляють як одна, а той самий id пристрою EarnApp
не повинен працювати двічі. Виконайте `docker compose down` у теці
CashFactory. Її
[файл compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
також запускає три контейнери, які монтують сокет Docker: Portainer (рядок 31)
і два контейнери Watchtower (рядки 141 і 264). Переконайтеся, що їх теж немає: `docker ps` не повинен
показувати жодного з них.

## Який файл використовувати { #which-file-to-use }

Використовуйте файл `.env` у своїй теці CashFactory, той, який ви заповнили за
[зразком](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose читає цей файл і розгортає `$` у значеннях, які не взято в
одинарні лапки. Таке значення — це не те, що показує файл, тому CashPilot просить
вас ввести його ще раз, а не вгадує.

## Як імпортувати { #how-to-import }

1. Відкрийте **Settings** (Налаштування), потім **Import from another tool** (Імпорт з іншого інструмента) (або перейдіть на `/import`).
2. Додайте файл `.env` або вставте його текст. Залиште інструмент на **Tell from the
   files** (Визначити за файлами) або виберіть CashFactory.
3. Перевірте таблицю. Позначте сервіси, які вам потрібні, і заповніть усі значення, позначені
   як відсутні.
4. Натисніть **Save the ticked services** (Зберегти позначені сервіси), а потім розгорніть їх на своїх воркерах з
   тієї самої сторінки.

## Що переноситься { #what-comes-over }

| Застосунок CashFactory | Ключі, що читаються | Сервіс CashPilot | Що переноситься |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id пристрою, тож ваш прив'язаний пристрій продовжує заробляти |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, пароль |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, пароль |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | токен |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, API-ключ |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id користувача |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID пристрою |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API-ключ |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | нічого: більше не доступний |

Значення, яке досі містить заповнювач зі зразка (`<email>`, `sdk-node-<md5sum>`),
вважається незаданим, а сервіс, у якому немає нічого, крім заповнювачів, не потрапляє
до таблиці.

## Що ніколи не переноситься { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot називає кожен пристрій за воркером, на якому він працює, тож
  два воркери ніколи не повідомляють однакову назву. Ваші старі пристрої залишаються в списку як
  офлайн на панелі кожного провайдера, доки ви не видалите їх там.
- **Bitping.** CashFactory зберігає логін Bitping у томі Docker, а не в
  `.env`, тож імпорту нічого читати, і рядка Bitping він не показує. Введіть
  логін у формі розгортання Bitping.
- **Portainer і Watchtower.** CashPilot сам керує своїми контейнерами
  й оновлює їх.

## Відстеження заробітку { #earnings-tracking }

Для Honeygain і IPRoyal Pawns логін контейнера — це також логін акаунта,
тож CashPilot заповнює й облікові дані для збирання їхнього заробітку, якщо ви ще не задали
їх у **Settings** (Налаштування). Для кожного іншого сервісу додайте логін для заробітку в
**Settings > Earnings collection** (Налаштування > Збирання заробітку).

## Безпека { #safety }

- Ніщо у файлі не виконується і не розгортається, і жодна адреса в ньому не завантажується.
- Файл читається один раз і не зберігається. Те, що ви зберігаєте, зберігається зашифрованим, як
  і всі інші облікові дані в CashPilot.
- Секрети на сторінці показуються лише як **set** (задано).
- Збережені імпорти залишаються на сторінці імпорту, доки ви не натиснете **Forget** (Забути), тож ви можете
  пізніше розгорнути їх на інших воркерах.
