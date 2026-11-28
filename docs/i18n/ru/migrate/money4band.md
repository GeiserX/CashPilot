---
source_hash: 5a764f1d0f5a
---
# Переход с money4band { #moving-from-money4band }

CashPilot умеет читать конфигурацию money4band и переносить ваши логины к сервисам, чтобы
вам не пришлось вводить их снова. Вы проверяете всё, прежде чем CashPilot это сохранит.

## Перед началом { #before-you-start }

Вам нужны аккаунт владельца CashPilot и хотя бы один воркер CashPilot на
машине, где сейчас работает money4band, или на другой машине.

Остановите money4band на машине, прежде чем разворачивать там те же сервисы из
CashPilot. Две копии за одним подключением зарабатывают как одна, а один и тот же id устройства EarnApp
или ProxyRack нельзя запускать дважды. Используйте **Stop apps stack** в
меню money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
или выполните `docker compose down` в его папке. Если вы настраивали дополнительные
экземпляры прокси, остановите и каждый из них.

## Какой файл использовать { #which-file-to-use }

Используйте `config/user-config.json` в папке money4band. Как передать его в
CashPilot, зависит от вашей версии money4band.

В money4band 4.x money4band записывает этот файл, когда вы запускаете **Setup Apps**, и
в нём ровно то, что вы ввели. `.env` рядом с ним генерируется из этого файла и тоже
подходит, как и отредактированный вручную `.env` из money4band 3.x. Оба остаются только
на вашем диске: их перечисляет
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
money4band.

money4band 5.0 шифрует `config/user-config.json` на диске
([заметки о безопасности](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption))
и удаляет свой `.env` после каждого запуска
([сборщик env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot не может прочитать зашифрованный файл. В папке money4band запустите
его команду `config edit`. Для бинарного файла из релиза возьмите файл для своей системы, например `./Money4Band-linux-amd64 config edit` или `.\Money4Band-windows-amd64.exe config edit` в Windows.
При запуске из исходников выполните `python run.py config edit`.
Она запускает money4band через uv, а если uv нет, через окружение pip ([run.py](https://github.com/MRColorR/money4band/blob/eebbdd410131e4b0fd4c9f9d49f84dc60e6a0e3d/run.py#L48-L69)).
Команда `config edit` открывает расшифрованный файл в вашем редакторе ([справка по CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Скопируйте весь его текст, вставьте его на странице **Import from another tool** (Импорт из другого инструмента), затем закройте редактор.

Лучше используйте файл JSON. В `.env` Docker Compose раскрывает `$` в значениях без кавычек,
поэтому пароль с `$` — это не то, что показывает файл. CashPilot
не гадает: он просит вас ввести это значение заново.

## Как импортировать { #how-to-import }

1. Откройте **Settings** (Настройки), затем **Import from another tool** (Импорт из другого инструмента) (или перейдите на `/import`).
2. Добавьте `user-config.json` или вставьте его текст. Оставьте для инструмента вариант «Tell from the
   files» («Определить по файлам») или выберите money4band.
3. Проверьте таблицу. Отметьте нужные сервисы и заполните все значения, отмеченные как
   отсутствующие.
4. Нажмите **Save the ticked services** (Сохранить отмеченные сервисы), затем разверните их на своих воркерах с
   той же страницы.

## Что переносится { #what-comes-over }

Имена полей взяты из
[шаблона user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
money4band и из имён `.env`, которые записывает его
[генератор](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, например `REPOCKET_APIKEY`). money4band 5.0 сохраняет те же имена
полей в своём
[каталоге приложений](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| Приложение money4band | Сервис CashPilot | Что переносится |
|---|---|---|
| `earnapp` | EarnApp | id устройства (`uuid`), чтобы привязанное устройство продолжало зарабатывать |
| `honeygain` | Honeygain | email, пароль |
| `iproyalpawns` | IPRoyal Pawns | email, пароль |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | токен |
| `repocket` | Repocket | email, API-ключ |
| `earnfm` | Earn.fm | API-ключ |
| `proxyrack` | ProxyRack | API-ключ, UUID устройства |
| `proxylite` | ProxyLite | id пользователя |
| `bitping` | Bitping | email, пароль |
| `mystnode` | Mysterium | включается; см. примечание о Mysterium ниже |

Приложение, которое вы выключили в money4band, появляется неотмеченным. Приложение, которое выключено и
не содержит ничего, кроме заглушек шаблона (`yourHONEYGAINMail`) и списков
портов, не показывается, поэтому нетронутый `user-config.json` даёт пустую таблицу.

Эти приложения перечисляются, но не переносятся:

| Приложение money4band | Почему |
|---|---|
| `proxybase` | money4band запускает старый клиент ProxyBase с id пользователя. CashPilot запускает текущий, которому нужен Access Token с proxybase.org. |
| `urnetwork` | money4band хранит токен сессии. CashPilot входит в URnetwork по вашему email и паролю. |
| `grass` | Grass работает как расширение браузера. CashPilot только отслеживает его, с токеном доступа из панели Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot отслеживает их, но контейнера для развёртывания нет. |
| `packetshare`, `peer2profit`, `speedshare` | Больше недоступны. |

Любое другое приложение помечается как «CashPilot has no such service» («В CashPilot нет такого сервиса»).

## Что не переносится никогда { #what-never-comes-over }

- **Имя устройства.** CashPilot называет каждое устройство по воркеру, на котором оно работает, поэтому
  два воркера никогда не сообщают одно и то же имя. Ваши старые устройства остаются в списке как
  офлайн в панели каждого провайдера, пока вы не удалите их там.
- **Прокси.** Добавьте каждый в разделе **Proxies** (Прокси) на странице **Fleet** (Парк), затем запускайте через него
  копии своих сервисов; само добавление прокси ничего не запускает.
  Сохранение импорта тоже ничего не запускает. Копии через прокси нужно, чтобы тот же сервис
  сначала был развёрнут на воркере, а его развёртывание запускает его на собственном подключении воркера, поэтому сервис, который никогда не должен использовать это подключение, стоит оставить
  неотмеченным. См. [Копии через прокси](../proxies.md).
- **Watchtower и уведомления.** CashPilot сам обновляет свои контейнеры.
- **Панель money4band и её порты.**

## Отслеживание заработка { #earnings-tracking }

Для Honeygain, IPRoyal Pawns и Bitping логин контейнера совпадает с логином
аккаунта, поэтому CashPilot заполняет и их учётные данные для сбора заработка, если только вы
уже не задали их в настройках. Для всех остальных сервисов добавьте логин для сбора заработка
в **Settings > Earnings collection** (Настройки > Сбор заработка).

## Mysterium { #mysterium }

Импорт включает Mysterium, но CashPilot запускает новый узел с новым
идентификатором. Хранилище ключей старого узла и все неурегулированные начисления остаются в
папке `.data/mysterium-node` money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Сначала урегулируйте их или следуйте
[руководству по Mysterium](../guides/mysterium.md), чтобы перенести идентификатор.

`.env` версии 3.x не позволяет понять, запускали ли вы Mysterium: его шаблон всегда
содержит порт панели. Из файла 3.x Mysterium не импортируется, поэтому добавьте
его из каталога, если вы его запускали.

## Безопасность { #safety }

- Ничто в файле не выполняется и не раскрывается, и ни один адрес из него не запрашивается.
- Файл читается один раз и не хранится. То, что вы сохраняете, хранится в зашифрованном виде, как
  и все остальные учётные данные в CashPilot.
- Секреты на странице показываются только как «set» («задано»).
- Сохранённые импорты остаются на странице импорта, пока вы не нажмёте **Forget** (Забыть), чтобы вы могли
  позже развернуть их на других воркерах.
