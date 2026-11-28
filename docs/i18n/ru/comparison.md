---
source_hash: 4b8d25fab777
---
# Сравнение CashPilot с другими проектами { #how-cashpilot-compares }

На этой странице CashPilot сравнивается с другими открытыми проектами, которые запускают несколько приложений пассивного дохода в Docker. Мы проверили каждый проект 2026-11-04, а CashPilot ещё раз 2026-11-28. Каждая ячейка о другом проекте ссылается на файл, из которого она взята, на фиксированном коммите, чтобы вы могли проверить сами. Если ячейка неверна или устарела, пожалуйста, [откройте issue](https://github.com/GeiserX/CashPilot/issues).

## Сравниваемые проекты { #projects-compared }

| Проект | Что мы проверили | Звёзды на 2026-11-04 | Лицензия |
|---|---|---|---|
| [money4band][m4b-tree] | Выпуск 5.0.0, коммит тега `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` на `65e900d` (2026-10-20), плюс утверждения README о его бинарнике 3.0.0-beta.9 | 238 | Проприетарная, [собственная лицензия v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` на `db9338a` (2026-11-03) | 257 | Файла LICENSE нет. [README][ii-license] разрешает копировать оригинал и запрещает распространять изменённые копии |
| [CashFactory][cf-tree] | `main` на `0ff4bd0` (2025-04-08) | 410 | Файл [LICENSE][cf-license-file] — GPL-3.0, но [README][cf-license] запрещает распространять изменённые копии |
| [home-assistant-passive-income][ha-tree] (дополнения HA) | Выпуск 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Выпуск v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

У money4band две линии кода. Его ветка по умолчанию `main` (`3bfafb1`) всё ещё содержит код 4.x, и последнее изменение кода там было 2026-03-03. Выпуск 5.0.0 собран из отдельной истории. Мы сравниваем 5.0.0, потому что именно его поставляет последний выпуск.

Веб-интерфейс IGM, управление парком и бинарник установщика закрыты и в его репозитории их нет. Где ячейка зависит от них, в ней написано «README утверждает», и она ссылается на строку README. Всё остальное в столбце IGM взято из shell-скриптов и файлов compose в репозитории.

Не включены: в [earning-machine](https://github.com/jf-m/earning-machine) и [passiveMachine](https://github.com/Xpl0itU/passiveMachine) не было коммитов с 2024 года. Поиск по GitHub не нашёл больше ничего поддерживаемого, что запускает больше одного приложения, только образы с одним приложением.

## Коротко { #short-version }

- **InternetIncome, money4band, IGM и, начиная с v1.69.0, CashPilot могут зарабатывать на многих IP через прокси.** Первые три запускают каждое приложение по одному разу на прокси, и прокси — главная функция InternetIncome. CashPilot запускает дополнительные копии сервиса, уже развёрнутого на воркере, каждую через прокси SOCKS5, HTTP CONNECT или выходной узел Tailscale ([копии через прокси](proxies.md)).
- **InternetIncome запускает 23 приложения, IGM 20, а воркер CashPilot <!-- n:docker -->21<!-- /n -->.** Всего CashPilot отслеживает больше сервисов (<!-- n:live -->50<!-- /n -->), потому что он следит и за сервисами в виде расширений браузера, десктопных приложений и GPU, которые он не запускает. Начиная с v1.64.0 он также может запускать любой образ, который вы назовёте, как [собственный сервис](custom-services.md).
- **money4band и IGM получают за вас ежедневные награды и обновляют образы приложений через Watchtower.** CashPilot не делает ни того, ни другого. Он скачивает образ заново, только когда вы разворачиваете или переразворачиваете сервис.
- **CashPilot — единственный здесь, кто читает балансы из ваших аккаунтов у провайдеров и хранит историю.** money4band 5.0.0 показывает оценки из собственного каталога, а не из ваших аккаунтов. Остальные дают ссылки на панель каждого провайдера.
- **CashPilot — единственный открытый проект здесь с одним интерфейсом для многих серверов.** README IGM утверждает, что у него есть управление парком, но этот код находится в его закрытом бинарнике.
- **Начиная с v1.70.0, CashPilot — единственный здесь, кто по умолчанию держит контейнеры приложений для заработка подальше от вашей LAN, с ограничениями.** Это включено для новых установок и для обновлённых установок, у которых нет приложений для заработка на мосте Docker по умолчанию. Обновлённая установка, чьи приложения для заработка уже стоят на этом мосте, держит их там, пока вы не включите изоляцию, а сеть, которую вы указали в `CASHPILOT_CONTAINER_NETWORK`, не получает барьера от CashPilot ([изоляция](isolation.md#modes)). Начиная с 2.0.7 Mysterium тоже работает за барьером; узел, развёрнутый до 2.0.6 включительно, остаётся в сети хоста без барьера, пока вы его не переразвернёте ([Mysterium за барьером](mysterium-fence.md)).

## Рядом { #side-by-side }

Столбец CashPilot описывает v3.0.1. Каждая его ячейка короткая, а подробности и ссылки на код собраны в [примечаниях под таблицей](#cashpilot-notes). Остальные столбцы описывают коммиты из таблицы выше.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Дополнения HA |
|---|---|---|---|---|---|---|
| Сколько приложений может запустить (см. [как мы считали](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> запускает воркер, плюс [собственные образы](custom-services.md); всего отслеживается <!-- n:live -->50<!-- /n --> | 15 ([каталог][m4b-catalog]). README говорит о 35, что [включает][m4b-readme-35] приложения сообщества и исключённые | 20 ([apps.json][igm-apps]) | 23 ([скрипт][ii-script]) | 11 ([файл compose][cf-compose]) | 10 ([папки дополнений][ha-tree]) |
| Как устанавливается | Docker Compose: один UI плюс воркер на каждом сервере ([парк](fleet.md)) | Python CLI или готовый бинарник, который пишет файл compose ([выпуск][m4b-tree]) | Установщик `curl \| sh` ([README][igm-install]), который скачивает закрытый бинарник, проверяемый только по файлу SHA256SUMS из того же выпуска ([установщик][igm-installer-sums]) | Один bash-скрипт на 1 608 строк, который вызывает `sudo docker run` ([скрипт][ii-script]) | Статический файл compose плюс `setup.sh`, запускаемый через sudo ([настройка][cf-setup]) | Репозиторий дополнений Home Assistant; нужен Home Assistant OS или Supervised |
| Много серверов, один вид | Да ([парк](fleet.md)) | Нет, один стек на устройство | README утверждает, что да, в закрытом бинарнике ([README][igm-features]) | Нет | Нет | Нет |
| Много прокси или IP | Да, через прокси SOCKS5, HTTP CONNECT или выходные узлы Tailscale ([копии через прокси](proxies.md), [примечания](#cashpilot-notes)) | Да ([README][m4b-features], [код][m4b-multiproxy]) | Да ([README][igm-features], [compose][igm-proxy]) | Да, это его главная функция ([README][ii-readme-top]) | Нет | Нет |
| Заработок | <!-- n:collectors -->20<!-- /n --> сборщиков читают балансы из ваших аккаунтов у провайдеров и хранят историю | Оценки из диапазонов каталога, а не данные аккаунта ([код][m4b-earnings]) | В скриптах ничего не найдено | Нет | Нет | Нет |
| Выплаты | Предлагает выплату, когда баланс падает, и записывает её, когда вы подтверждаете ([схема][cp-payouts]) | Нет | Нет | Нет | Нет | Нет |
| Получение ежедневных наград | Нет | Да, sidecar-контейнеры ([README][m4b-features]) | Да ([README][igm-features], [compose][igm-sidecars]) | Нет | Нет | Нет |
| Учётные данные при хранении | Зашифрованы (Fernet) в базе данных UI ([примечания](#cashpilot-notes)) | Зашифрованы (Fernet); файл ключа лежит в каталоге данных ([код][m4b-crypto]) | Зашифрованы (AES-256 через openssl); файл ключа лежит рядом с хранилищем ([код][igm-encryptor]) | Открытым текстом в `properties.conf`; некоторые пароли передаются как аргументы `docker run` ([скрипт][ii-password-arg]) | Открытым текстом в `.env` ([файл][cf-env]) | Параметры дополнения, которые Supervisor хранит в `/data/options.json` ([документация HA][ha-options]) |
| Настройки контейнеров приложений для заработка | Возможности отброшены, кроме тех, что выдаёт каталог; `no-new-privileges`, ограничение pids; привилегированный режим отклоняется ([примечания](#cashpilot-notes)) | `no-new-privileges` на каждом непривилегированном сервисе ([код][m4b-nnp]); контейнер прокси привилегированный с `NET_ADMIN` ([шаблон][m4b-tun]) | На сервисах приложений ничего не задано; Mysterium получает `NET_ADMIN` ([compose][igm-hosting-myst]); контейнер прокси получает `NET_ADMIN`, с `no-new-privileges` и ограничением pids ([compose][igm-proxy]) | Ebesucher работает с `seccomp=unconfined` ([скрипт][ii-seccomp]); контейнеры прокси и Mysterium получают `NET_ADMIN` | Ничего не задано | Ни одно дополнение не запрашивает привилегированный режим, сеть хоста или доступ к Docker API ([пример конфигурации][ha-config]) |
| Куда смонтирован сокет Docker | В прокси сокета, только для чтения, и в одноразовый контейнер миграции ([примечания](#cashpilot-notes)) | Watchtower ([шаблон][m4b-watchtower]) | Watchtower, только для чтения с `no-new-privileges` ([compose][igm-watchtower]) | Пять вспомогательных контейнеров для перезапуска ([скрипт][ii-sock-helper]) и Watchtower ([скрипт][ii-watchtower]) | Portainer, опубликованный на портах 8000, 9000 и 9443 на всех интерфейсах ([compose][cf-portainer]), и два Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Никуда |
| Теги образов | <!-- n:pinned -->9<!-- /n --> из <!-- n:docker -->21<!-- /n --> образов приложений для заработка закреплены на версии или digest; остальные плавающие | Все 15 образов приложений используют `:latest` ([пример][m4b-image]); контейнер прокси закреплён на v2.6.0, Watchtower на `:1` | Тега нет, поэтому Docker использует `latest` ([compose][igm-hosting]); тег задан только для некоторых сборок ARM | В основном `:latest` ([пример][ii-seccomp]); EarnApp `:lite`, Honeygain закреплён на 0.6.6 при работе через прокси на amd64 ([скрипт][ii-honeygain]), у Traffmonetizer теги по архитектурам на ARM; Watchtower `:nightly` | `:latest` или без тега, кроме EarnApp `:lite` ([compose][cf-compose]) | Одна версия на дополнение, повышается ежедневной задачей CI ([workflow][ha-bump], [пример][ha-dockerfile]) |
| Обновление образов приложений | Скачиваются заново при каждом развёртывании или переразвёртывании; автоматического обновления нет | Watchtower ([шаблон][m4b-watchtower]) | Watchtower каждые 4 часа ([compose][igm-watchtower]) | Watchtower раз в день, если вы его включите ([скрипт][ii-watchtower]) | Два Watchtower, каждый ограничен одним приложением, PacketStream ([compose][cf-watchtower-ps]) и EarnFM ([compose][cf-watchtower-efm]); остальные 9 приложений не обновляются | Обновления дополнений Home Assistant |
| Изоляция LAN | Включена по умолчанию для новых установок ([изоляция](isolation.md#lan-isolation-by-default), [примечания](#cashpilot-notes)) | Собственная подсеть моста ([конфигурация][m4b-subnet]), которая не блокирует LAN | Ничего не слито | Ничего не найдено | Ничего не найдено | Ничего не найдено |
| ARM | UI и воркер для arm64, с проверкой платформы перед каждым развёртыванием ([ARM](arm.md)) | Бинарники для arm64 и armv7 ([выпуск][m4b-release]) | README утверждает поддержку amd64 и arm64, arm32 с ограничениями, и настраивает QEMU ([README][igm-arch]) | Нужна эмуляция binfmt для образов только под amd64 ([README][ii-arm]) | README говорит, что на Raspberry Pi не работает ([README][cf-raspberry]) | Зависит от дополнения; ProxyRack только для amd64 ([конфигурация][ha-proxyrack]) |
| Интерфейс | Веб-интерфейс, плюс клиенты Desktop, Android, MCP и Home Assistant | CLI, меню и локальная веб-панель, по умолчанию привязанная к 127.0.0.1 ([код][m4b-bind]) | CLI, меню и, по словам README, веб-интерфейс на порту 4747, доступный из LAN ([README][igm-webui]) | Нет, это скрипт | Страница закладок на порту 80 плюс Portainer ([README][cf-ui]) | Панель дополнения Home Assistant |
| Последний выпуск | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Версионированных выпусков нет | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Исходящие вызовы помимо приложений | Проверка обновлений, определение публичного IP, курсы валют и ончейн-балансы; шрифты и Chart.js с CDN ([примечания](#cashpilot-notes)) | Выпуски GitHub для проверки обновлений ([код][m4b-updater]); Docker Hub и ghcr.io для проверки тегов образов ([код][m4b-registry]); при запуске проверки IP — `api.ipify.org`, `ifconfig.me` или `icanhazip.com` для вашего публичного IP и `ip-api.com` по простому HTTP для оценки IP ([код][m4b-ipscore]) | Выпуски GitHub ([код][igm-version]); `api.ipify.org`, `ifconfig.me` или `icanhazip.com` для вашего публичного IP ([код][igm-ifconfig]); `ip-api.com` по простому HTTP для оценки IP ([код][igm-ipscore]). Закрытый бинарник не проверялся | Ничего не найдено | Ничего не найдено | Ничего не найдено |

### Примечания к столбцу CashPilot { #cashpilot-notes }

- **Много прокси или IP.** Начиная с v1.69.0 CashPilot запускает дополнительные копии сервиса, уже развёрнутого на воркере, каждую через свой прокси. SOCKS5 и HTTP CONNECT передают только TCP: туннель выпускает только TCP на порт прокси, поэтому UDP-ретрансляция SOCKS5 отбрасывается. Выходной узел Tailscale передаёт и UDP. Приложение для заработка делит сетевое пространство имён с контейнером туннеля ([код][cp-proxy-deploy]). Это пространство имён выпускает только loopback, туннель и собственное соединение туннеля с прокси: TCP на его адрес и порт или помеченные пакеты tailscaled ([брандмауэр туннеля][cp-tunnel-fw]). Поэтому неработающий прокси останавливает приложение для заработка, а не допускает утечку его трафика ([как это работает](proxies.md#how-it-works)). Сервис не может работать через прокси, если ему нужны сеть хоста, опубликованные порты, тома, устройства, GPU или `NET_ADMIN`, `NET_RAW` или `SYS_ADMIN`, или если его условия запрещают прокси. Поэтому <!-- n:noproxy -->10<!-- /n --> из <!-- n:docker -->21<!-- /n --> приложения для заработка зарабатывают только с собственного IP сервера ([что не может](proxies.md#what-cannot-run-through-a-proxy)).
- **Заработок.** Некоторым сборщикам нужна cookie или токен, скопированные из браузера, и некоторые из них истекают. В руководстве каждого сервиса сказано, каким именно.
- **Учётные данные при хранении.** UI хранит файл ключа шифрования в том же томе данных, что и базу данных ([код][cp-fernet]). Учётные данные приложений для заработка доходят до каждого воркера как переменные окружения контейнера, поэтому в конфигурации Docker этого воркера они в открытом виде (`docker inspect`).
- **Настройки контейнеров приложений для заработка.** Воркер отбрасывает все возможности, а затем возвращает те, что каталог указывает для сервиса. Он задаёт `no-new-privileges` и ограничение pids и отклоняет привилегированные контейнеры ([код][cp-hardening], [код][cp-privileged], [настройки безопасности](security-defaults.md)). Mysterium работает в собственном сетевом пространстве имён на мосте за барьером с `NET_ADMIN`, `SETUID` и `SETGID`, на образе, закреплённом по digest ([каталог][cp-myst]). Необязательная среда выполнения gVisor может добавить ядро в пространстве пользователя ([среды выполнения](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Сокет Docker.** Начиная с v1.71.0 у воркера нет сокета. Его держит прокси сокета: sockguard 2.4.7, закреплён по digest, только для чтения ([compose][cp-sock]). Воркер получает отфильтрованную копию, которая отклоняет привилегированные контейнеры, привязки `/` или сокета, а также возможности или устройства вне каталога ([прокси сокета](security-defaults.md#docker-socket-proxy)). Одноразовый контейнер `cashpilot-migrate` тоже монтирует сокет. Он ставит метку владельца на тома и сеть барьера, которые создали старые выпуски, и пересоздаёт на них их контейнеры, чтобы изоляция по владельцу в прокси их охватывала. Он завершается до запуска прокси ([compose][cp-migrate]). Приложение для заработка никогда не получает сокет ([код][cp-mounts]). Прокси пока не является границей root. При заданном `CASHPILOT_COMPOSE_DIR` или `CASHPILOT_PROXY_BIND_MOUNTS` скомпрометированный воркер может одним контейнером подбросить символическую ссылку в разрешённую папку, а вторым добраться до `/` хоста ([подробности](security-defaults.md#docker-socket-proxy)). Листинги Unraid и TrueNAS по-прежнему монтируют в воркер сырой сокет ([магазины приложений](app-stores.md)).
- **Изоляция LAN.** Включена по умолчанию начиная с v1.70.0, для новых установок и для обновлённых установок без приложений для заработка на мосте Docker по умолчанию. Воркер ставит приложения для заработка на собственный мост и пишет для него таблицу брандмауэра ([код][cp-fence]). Таблица отбрасывает частные диапазоны, диапазон tailnet, облачные метаданные, подключённые подсети хоста и сам хост. При включённом определении публичного IP она также отбрасывает публичный IP дома ([изоляция](isolation.md#lan-isolation-by-default)). Обновлённая установка, чьи приложения для заработка уже стоят на мосте по умолчанию, остаётся там, пока вы не нажмёте **Turn on isolation** (Включить изоляцию). `CASHPILOT_ISOLATION=off` выключает её. При заданном `CASHPILOT_CONTAINER_NETWORK` CashPilot не пишет барьер для этой сети, и правила брандмауэра на вас. В Podman барьера нет, и страница парка об этом сообщает ([режимы](isolation.md#modes), [код][cp-fence-mode]). Начиная с 2.0.7 Mysterium тоже за барьером. Узел, развёрнутый до 2.0.6 включительно, остаётся в сети хоста, пока вы его не переразвернёте ([Mysterium за барьером](mysterium-fence.md)). Проверка показывает, до чего могут достучаться приложения для заработка ([проверка](isolation-check.md)).
- **Исходящие вызовы.** Помимо самих приложений, CashPilot обращается к:
    - выпускам GitHub раз в день для проверки обновлений (`CASHPILOT_UPDATE_CHECK=off` это отключает, [код][cp-update]).
    - `api.ipify.org`, `ifconfig.me` или `icanhazip.com` раз в час с каждого воркера, чтобы узнать его публичный IP (`CASHPILOT_EGRESS_DETECT=off` это отключает, [код][cp-egress]).
    - CoinGecko и Frankfurter для курсов валют ([код][cp-rates]).
    - mempool.space, api.kaspa.org и публичным RPC-узлам Ethereum, Ethereum Classic, Polygon и Solana для [ончейн-балансов](onchain.md).
    - iptoasn.com за таблицей имён сетей CashPilot, не чаще раза в неделю и только пока на воркере включена [активность](activity.md#network-names-and-countries) ([код][cp-ipgeo]).
    - каждому провайдеру, для сборщиков.

    Браузер загружает Google Fonts ([шаблон][cp-cdn]) и Chart.js с jsDelivr ([шаблон][cp-chartjs]).

Ни один из проектов не отправляет телеметрию использования в коде, который мы прочитали. Закрытый бинарник IGM прочитать было невозможно.

Каждый проект здесь передаёт учётные данные приложений в контейнеры как переменные окружения, а InternetIncome некоторые передаёт ещё и как аргументы команды, поэтому на хосте, где работают приложения, они лежат открытым текстом в конфигурации контейнера Docker (`Env` и `Args` в `docker inspect`) и доступны всем, у кого есть доступ к Docker. Строка «Учётные данные при хранении» описывает только сохранённую копию.

## Как мы считали { #how-we-counted }

- **CashPilot.** Сервисы в каталоге со статусом active или beta и образом Docker, без учёта вычислений на GPU и майнинг-пулов. Число на этой странице берётся из `scripts/generate_readme_tables.py`, и CI падает, если оно расходится.
- **money4band 5.0.0.** По одному файлу JSON на приложение в `config/catalog/supported/`: 15. «35 apps» в README учитывает также каталог сообщества, который по умолчанию выключен ([конфигурация][m4b-community]), приложения без образа Docker и исключённые приложения.
- **IGM.** Записи в `apps.json`: 20, все включены. Контейнер прокси, Watchtower и sidecar-контейнеры для получения наград не учитываются.
- **InternetIncome.** Каждый блок с комментарием `# Starting ... container` в `internetIncome.sh`, кроме блоков прокси и Watchtower: 24. Блоки Chrome и Firefox для Ebesucher — одно приложение, как и EarnFM с EarnFM Fleetshare, которые используют один аккаунт EarnFM. Блок расширений Depin запускает Grass и Gradient ([скрипт][ii-depin]), два приложения. Итого 23. Таблица в README перечисляет 27 приложений, у некоторых из них есть только ссылка для регистрации.
- **CashFactory.** Сервисы заработка в `docker-compose.yml`: 11. Portainer, веб-сервер и два Watchtower не учитываются. Один сервис закомментирован.
- **Дополнения HA.** Папки дополнений с файлом конфигурации: 10.

Мы не проверяли, платит ли до сих пор каждое приложение из каждого списка.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
