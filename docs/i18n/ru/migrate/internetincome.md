---
source_hash: ca9dd25d45ca
---
# Переход с InternetIncome { #moving-from-internetincome }

CashPilot умеет читать `properties.conf` InternetIncome и файлы, в которых он
хранит id ваших устройств EarnApp и ProxyRack, и переносить их. Вы проверяете
всё, прежде чем CashPilot это сохранит.

## Перед началом { #before-you-start }

Вам нужны аккаунт владельца CashPilot и хотя бы один воркер CashPilot.

Остановите InternetIncome на машине, прежде чем разворачивать там те же сервисы из
CashPilot. Две копии за одним подключением зарабатывают как одна, а один и тот же id устройства
нельзя запускать дважды. В папке InternetIncome выполните:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` удаляет контейнеры и сохраняет `earnapp.txt`, `proxyrack.txt` и
папку данных Mysterium. `--deleteBackup` удаляет и их
([internetIncome.sh, строки 61–64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
и [строка 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
поэтому сначала выполните импорт.

## Какие файлы использовать { #which-files-to-use }

Из папки InternetIncome:

- `properties.conf`, ваши настройки.
- `earnapp.txt`, если вы запускали EarnApp. Каждая строка содержит ссылку устройства
  ([строки 1250–1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, если вы запускали ProxyRack. По одному UUID устройства в строке
  ([строки 817–827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot берёт первое устройство из каждого файла: то, которое использовал ваш основной контейнер,
и то, которое вы привязали к своему аккаунту. Остальные строки принадлежали копиям через
прокси, и страница сообщает, сколько строк она пропустила.

InternetIncome пропускает каждое значение через оболочку
([строка 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Значение в одинарных кавычках берётся как написано, как и советуют комментарии в
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Значение вне одинарных кавычек, которое содержит `$`, обратную кавычку, пробел или
другой символ, который оболочка изменила бы, — не то, что показывает файл, поэтому
CashPilot просит вас ввести его заново, а не запускает оболочку, чтобы это выяснить.

## Как импортировать { #how-to-import }

1. Откройте **Settings** (Настройки), затем **Import from another tool** (Импорт из другого инструмента) (или перейдите на `/import`).
2. Добавьте `properties.conf`, а также `earnapp.txt` и `proxyrack.txt`, если они у вас
   есть. Оставьте для инструмента вариант «Tell from the files» («Определить по файлам») или выберите InternetIncome.
3. Проверьте таблицу. Отметьте нужные сервисы и заполните все значения, отмеченные как
   отсутствующие. Repocket нужен email вашего аккаунта, который InternetIncome никогда не
   запрашивал.
4. Нажмите **Save the ticked services** (Сохранить отмеченные сервисы), затем разверните их на своих воркерах с
   той же страницы.

## Что переносится { #what-comes-over }

| Приложение InternetIncome | Читаемые ключи | Сервис CashPilot | Что переносится |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API-ключ (добавьте свой email) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | токен |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API-ключ, UUID устройства |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, пароль |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, пароль |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id пользователя |
| `earnfm` | `EARN_FM_API` | Earn.fm | API-ключ |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id устройства |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, пароль |
| `mysterium` | `MYSTERIUM=true` | Mysterium | включается; см. примечание о Mysterium ниже |

Пустое значение означает, что приложение было выключено, и оно не показывается.

Эти приложения перечисляются, но не переносятся:

| Приложение InternetIncome | Почему |
|---|---|
| `urnetwork` | InternetIncome использует токен сессии. CashPilot входит в URnetwork по вашему email и паролю. |
| `grass` | Grass работает как расширение браузера. CashPilot только отслеживает его, с токеном доступа из панели Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot отслеживает их, но контейнера для развёртывания нет. |
| `peer2profit` | Больше недоступен. |

Настройки приложений, которых нет в CashPilot (antGain, Adnade и другие),
перечисляются по имени как непрочитанные.

## Что не переносится никогда { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot называет каждое устройство по воркеру, на котором оно работает, поэтому
  два воркера никогда не сообщают одно и то же имя. Ваши старые устройства остаются в списке как
  офлайн в панели каждого провайдера, пока вы не удалите их там.
- **Прокси** (`USE_PROXIES`, `proxies.txt`). Добавьте каждый в разделе **Proxies** (Прокси)
  на странице **Fleet** (Парк), затем запускайте через него копии своих сервисов; само добавление
  прокси ничего не запускает. С `USE_PROXIES=true` InternetIncome запускал
  ваши сервисы только через прокси. Сохранение импорта тоже ничего не запускает.
  Копии через прокси нужно, чтобы тот же сервис сначала был развёрнут на воркере, а его
  развёртывание запускает его на собственном подключении воркера, поэтому сервис, который
  никогда не должен использовать это подключение, стоит оставить неотмеченным. См. [Копии
  через прокси](../proxies.md).
- **`BROWSER_USERNAME` и `BROWSER_PASSWORD`**, собственный логин браузера
  InternetIncome.

## Отслеживание заработка { #earnings-tracking }

Для Honeygain, IPRoyal Pawns и Bitping логин контейнера совпадает с логином
аккаунта, поэтому CashPilot заполняет и их учётные данные для сбора заработка, если только вы
уже не задали их в настройках. Для всех остальных сервисов добавьте логин для сбора заработка
в **Settings > Earnings collection** (Настройки > Сбор заработка).

## Mysterium { #mysterium }

Импорт включает Mysterium, но CashPilot запускает новый узел с новым
идентификатором. Хранилище ключей старого узла и все неурегулированные начисления остаются в
папке `mysterium-data` InternetIncome. Сначала урегулируйте их или следуйте
[руководству по Mysterium](../guides/mysterium.md), чтобы перенести идентификатор.

## Безопасность { #safety }

- Ничто в файлах не выполняется и не раскрывается, и ни один адрес из них не запрашивается.
- Файлы читаются один раз и не хранятся. То, что вы сохраняете, хранится в зашифрованном виде, как
  и все остальные учётные данные в CashPilot.
- Секреты на странице показываются только как «set» («задано»).
- Сохранённые импорты остаются на странице импорта, пока вы не нажмёте **Forget** (Забыть), чтобы вы могли
  позже развернуть их на других воркерах.
