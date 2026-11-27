---
source_hash: 1a93abea95d7
---
# Порівняння CashPilot з іншими { #how-cashpilot-compares }

Ця сторінка порівнює CashPilot з іншими відкритими проєктами, які запускають кілька застосунків пасивного доходу в Docker. Ми перевірили кожен проєкт 2026-11-04. Кожна клітинка про інший проєкт посилається на файл, з якого вона взята, на фіксованому коміті, тож ви можете перевірити це самі. Якщо клітинка неправильна або застаріла, будь ласка, [створіть issue](https://github.com/GeiserX/CashPilot/issues).

## Проєкти, які порівнюються { #projects-compared }

| Проєкт | Що ми перевірили | Зірки на 2026-11-04 | Ліцензія |
|---|---|---|---|
| [money4band][m4b-tree] | Випуск 5.0.0, коміт тегу `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` на `65e900d` (2026-10-20), а також твердження README про його бінарний файл 3.0.0-beta.9 | 238 | Пропрієтарна, [власна ліцензія v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` на `db9338a` (2026-11-03) | 257 | Файлу LICENSE немає. [README][ii-license] дозволяє копіювати оригінал і забороняє поширювати змінені копії |
| [CashFactory][cf-tree] | `main` на `0ff4bd0` (2025-04-08) | 410 | Файл [LICENSE][cf-license-file] — GPL-3.0, але [README][cf-license] забороняє поширювати змінені копії |
| [home-assistant-passive-income][ha-tree] (доповнення HA) | Випуск 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Випуск v1.64.0, `main` на `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band має дві лінії коду. Його типова гілка `main` (`3bfafb1`) досі містить код 4.x, і остання зміна коду там була 2026-03-03. Випуск 5.0.0 зібрано з окремої історії. Ми порівнюємо 5.0.0, бо саме його постачає найновіший випуск.

Вебінтерфейс IGM, керування парком і бінарний інсталятор мають закритий код і відсутні в його репозиторії. Там, де клітинка залежить від них, вона каже «твердження README» і посилається на рядок README. Усе інше в стовпці IGM взято зі скриптів оболонки та файлів compose у репозиторії.

Не включено: [earning-machine](https://github.com/jf-m/earning-machine) і [passiveMachine](https://github.com/Xpl0itU/passiveMachine) не мали комітів з 2024 року. Пошук на GitHub не знайшов нічого іншого, що підтримується і запускає більше одного застосунку, лише образи для одного застосунку.

## Коротко { #short-version }

- **InternetIncome, money4band, IGM і, починаючи з v1.69.0, CashPilot можуть заробляти на багатьох IP через проксі.** Перші три запускають кожен застосунок по разу на кожен проксі, і проксі — головна функція InternetIncome. CashPilot запускає додаткові копії сервісу, уже розгорнутого на воркері, кожну через проксі SOCKS5, HTTP CONNECT або exit node Tailscale ([копії через проксі](proxies.md)).
- **InternetIncome (23) запускає більше застосунків, ніж воркер CashPilot (<!-- n:docker -->21<!-- /n -->); IGM запускає 20.** Загалом CashPilot відстежує більше сервісів (<!-- n:live -->50<!-- /n -->), бо він також стежить за сервісами у вигляді розширень браузера, десктопних застосунків і GPU, яких він не запускає. Починаючи з v1.64.0 він також може запускати будь-який образ, який ви вкажете, як [власний сервіс](custom-services.md).
- **money4band і IGM отримують щоденні винагороди за вас і оновлюють образи застосунків за допомогою Watchtower.** CashPilot не робить ні того, ні іншого. Він знову завантажує образ лише тоді, коли ви розгортаєте або перерозгортаєте.
- **CashPilot — єдиний тут, хто читає баланси з ваших акаунтів у провайдерів і зберігає історію.** money4band 5.0.0 показує оцінки з власного каталогу, а не з ваших акаунтів. Інші посилаються на панель кожного провайдера.
- **CashPilot — єдиний тут проєкт із відкритим кодом з одним UI для багатьох серверів.** README IGM заявляє про керування парком, але цей код у його закритому бінарному файлі.
- **Починаючи з v1.70.0, CashPilot — єдиний тут, хто типово тримає контейнери застосунків для заробітку поза вашою LAN, з обмеженнями.** Це ввімкнено для нових інсталяцій і для оновлених інсталяцій, у яких немає застосунків для заробітку на типовому bridge Docker. Оновлена інсталяція, чиї застосунки для заробітку вже на цьому bridge, залишає їх там, доки ви не ввімкнете ізоляцію, а мережа, яку ви вказали в `CASHPILOT_CONTAINER_NETWORK`, не отримує бар'єра від CashPilot ([ізоляція](isolation.md#modes)). Починаючи з 2.0.7 Mysterium теж працює за бар'єром; вузол, розгорнутий до 2.0.6 включно, залишається в мережі хоста, без бар'єра, доки ви його не перерозгорнете ([Mysterium за бар'єром](mysterium-fence.md)).

## Поруч { #side-by-side }

Стовпець CashPilot описує v1.64.0, крім рядків про проксі, сокет Docker та ізоляцію LAN, які описують v1.71.1 (`0170dee`, 2026-11-06), і мережі Mysterium в рядках про параметри контейнера та ізоляцію LAN, які описують випуск після 2.0.6 (`01e7310`). Рядок про вихідні виклики включає виклики до експлорерів з [поточного посібника з ончейн-балансів](onchain.md). Інші стовпці описують коміти з таблиці вище.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Доповнення HA |
|---|---|---|---|---|---|---|
| Застосунки, які він може запускати (див. [як ми рахували](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> запускає воркер, плюс [власні образи](custom-services.md); <!-- n:live -->50<!-- /n --> відстежується загалом | 15 ([каталог][m4b-catalog]). README каже 35, що [включає][m4b-readme-35] застосунки спільноти та покинуті | 20 ([apps.json][igm-apps]) | 23 ([скрипт][ii-script]) | 11 ([файл compose][cf-compose]) | 10 ([теки доповнень][ha-tree]) |
| Як його встановити | Docker Compose: один UI плюс воркер на кожному сервері; воркер запускає застосунки для заробітку через Docker API ([парк](fleet.md)) | Python CLI або готовий бінарний файл, що записує файл compose ([випуск][m4b-tree]) | Інсталятор `curl \| sh` ([README][igm-install]), який завантажує закритий бінарний файл, що перевіряється лише за файлом SHA256SUMS з того самого випуску ([інсталятор][igm-installer-sums]) | Один bash-скрипт на 1 608 рядків, що викликає `sudo docker run` ([скрипт][ii-script]) | Статичний файл compose плюс `setup.sh`, що запускається через sudo ([налаштування][cf-setup]) | Репозиторій доповнень Home Assistant; потребує Home Assistant OS або Supervised |
| Багато серверів, один вигляд | Так ([парк](fleet.md)) | Ні, один стек на пристрій | README заявляє, що так, у закритому бінарному файлі ([README][igm-features]) | Ні | Ні | Ні |
| Багато проксі чи IP | Так, починаючи з v1.69.0: додаткові копії розгорнутого сервісу, кожна через проксі SOCKS5, HTTP CONNECT або exit node Tailscale. SOCKS5 і HTTP CONNECT передають лише TCP (тунель випускає лише TCP на порт проксі, тож UDP-релеї SOCKS5 відкидаються); exit node Tailscale передає і UDP. Застосунок для заробітку ділить простір імен мережі контейнера тунелю, брандмауер якого випускає лише loopback, тунель і власне з'єднання тунелю з проксі (TCP на його адресу й порт або позначені пакети tailscaled), тож мертвий проксі зупиняє його замість витоку ([копії через проксі](proxies.md#how-it-works), [код][cp-proxy-deploy], [брандмауер тунелю][cp-tunnel-fw]). Сервіси, яким потрібні мережа хоста, опубліковані порти, томи, пристрої або `NET_ADMIN`, `NET_RAW` чи `SYS_ADMIN`, не можуть працювати через проксі ([копії через проксі](proxies.md#what-cannot-run-through-a-proxy)) | Так ([README][m4b-features], [код][m4b-multiproxy]) | Так ([README][igm-features], [compose][igm-proxy]) | Так, його головна функція ([README][ii-readme-top]) | Ні | Ні |
| Заробіток | <!-- n:collectors -->20<!-- /n --> збирачів читають баланси з акаунтів у провайдерів і зберігають історію. Деяким потрібні cookie або токен, скопійовані з вашого браузера, і частина з них спливає (див. посібник кожного сервісу) | Оцінки з діапазонів каталогу, а не дані акаунта ([код][m4b-earnings]) | У скриптах не знайдено | Немає | Немає | Немає |
| Виплати | Пропонує виплату, коли баланс падає, і записує її, щойно ви підтвердите ([схема][cp-payouts]) | Немає | Немає | Немає | Немає | Немає |
| Отримання щоденних винагород | Ні | Так, sidecar-контейнери ([README][m4b-features]) | Так ([README][igm-features], [compose][igm-sidecars]) | Ні | Ні | Ні |
| Облікові дані на диску | Зашифровані (Fernet) у базі даних UI; файл ключа лежить у тому самому томі даних ([код][cp-fernet]). Облікові дані застосунків для заробітку надходять на кожен воркер як змінні середовища контейнера, тож у конфігурації Docker цього воркера вони у відкритому вигляді (`docker inspect`) | Зашифровані (Fernet); файл ключа лежить у каталозі даних ([код][m4b-crypto]) | Зашифровані (AES-256 за допомогою openssl); файл ключа лежить поруч зі сховищем ([код][igm-encryptor]) | Відкритим текстом у `properties.conf`; деякі паролі передаються як аргументи `docker run` ([скрипт][ii-password-arg]) | Відкритим текстом у `.env` ([файл][cf-env]) | Параметри доповнення, які Supervisor зберігає в `/data/options.json` ([документація HA][ha-options]) |
| Параметри контейнерів застосунків для заробітку | Усі можливості вимкнено, потім каталог повертає те, що потрібно сервісу; `no-new-privileges`; ліміт pids; привілейований режим відхиляється ([код][cp-hardening], [код][cp-privileged]). Mysterium працює у власному просторі імен мережі на bridge за бар'єром з `NET_ADMIN`, `SETUID` і `SETGID`, на образі, закріпленому за дайджестом ([каталог][cp-myst]) | `no-new-privileges` на кожному непривілейованому сервісі ([код][m4b-nnp]); контейнер проксі привілейований з `NET_ADMIN` ([шаблон][m4b-tun]) | Для сервісів застосунків нічого не задано; Mysterium отримує `NET_ADMIN` ([compose][igm-hosting-myst]); контейнер проксі отримує `NET_ADMIN`, з `no-new-privileges` і лімітом pids ([compose][igm-proxy]) | Ebesucher працює з `seccomp=unconfined` ([скрипт][ii-seccomp]); контейнери проксі та Mysterium отримують `NET_ADMIN` | Нічого не задано | Жодне доповнення не просить привілейованого режиму, мережі хоста чи доступу до Docker API ([приклад конфігурації][ha-config]) |
| Куди монтується сокет Docker | Починаючи з v1.71.0, у проксі сокета (sockguard 2.4.5, закріплений за дайджестом), лише для читання. Воркер отримує відфільтровану копію, яка відхиляє привілейовані контейнери, прив'язки `/` чи сокета, а також можливості й пристрої поза тими, що в каталозі ([compose][cp-sock], [подробиці](security-defaults.md)); ніколи в застосунок для заробітку ([код][cp-mounts]) | Watchtower ([шаблон][m4b-watchtower]) | Watchtower, лише для читання з `no-new-privileges` ([compose][igm-watchtower]) | П'ять допоміжних контейнерів для перезапуску ([скрипт][ii-sock-helper]) і Watchtower ([скрипт][ii-watchtower]) | Portainer, опублікований на портах 8000, 9000 і 9443 на всіх інтерфейсах ([compose][cf-portainer]), і два Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Немає |
| Теги образів | 9 з <!-- n:docker -->21<!-- /n --> образів застосунків для заробітку закріплено за версією чи дайджестом; решта рухомі | Усі 15 образів застосунків використовують `:latest` ([приклад][m4b-image]); контейнер проксі закріплено на v2.6.0, Watchtower — на `:1` | Без тегу, тож Docker використовує `latest` ([compose][igm-hosting]); тег задано лише для деяких збірок ARM | Здебільшого `:latest` ([приклад][ii-seccomp]); EarnApp `:lite`, Honeygain закріплено на 0.6.6 під час роботи через проксі на amd64 ([скрипт][ii-honeygain]), Traffmonetizer — теги для кожної архітектури на ARM; Watchtower `:nightly` | `:latest` або без тегу, крім EarnApp `:lite` ([compose][cf-compose]) | Одна версія на доповнення, яку піднімає щоденне завдання CI ([workflow][ha-bump], [приклад][ha-dockerfile]) |
| Оновлення образів застосунків | Завантажуються знову під час кожного розгортання чи перерозгортання; автоматичного оновлювача немає | Watchtower ([шаблон][m4b-watchtower]) | Watchtower кожні 4 години ([compose][igm-watchtower]) | Watchtower раз на день, якщо ви його ввімкнете ([скрипт][ii-watchtower]) | Два Watchtower, кожен обмежений одним застосунком, PacketStream ([compose][cf-watchtower-ps]) і EarnFM ([compose][cf-watchtower-efm]); інші 9 застосунків не оновлюються | Оновлення доповнень Home Assistant |
| Ізоляція LAN | Типово ввімкнена починаючи з v1.70.0 для нових інсталяцій і для оновлених інсталяцій, у яких немає застосунків для заробітку на типовому bridge Docker: воркер розміщує застосунки для заробітку на власному bridge і записує таблицю брандмауера, яка відкидає приватні діапазони, діапазон tailnet, хмарні метадані, під'єднані підмережі хоста, сам хост і, якщо ввімкнено визначення публічної IP, публічну IP дому ([ізоляція](isolation.md#lan-isolation-by-default), [код][cp-fence]). Оновлена інсталяція, чиї застосунки для заробітку вже на типовому bridge, залишається там, доки ви не натиснете **Turn on isolation** (Увімкнути ізоляцію); `CASHPILOT_ISOLATION=off` вимикає її; якщо задано `CASHPILOT_CONTAINER_NETWORK`, CashPilot не записує бар'єра для цієї мережі, і правила брандмауера — ваша справа ([ізоляція](isolation.md#modes), [код][cp-fence-mode]). Починаючи з 2.0.7 Mysterium теж за бар'єром; вузол, розгорнутий до 2.0.6 включно, залишається в мережі хоста, доки ви його не перерозгорнете ([Mysterium за бар'єром](mysterium-fence.md)). Перевірка показує, до чого мають доступ застосунки для заробітку ([перевірка](isolation-check.md)) | Власна підмережа bridge ([конфігурація][m4b-subnet]), яка не блокує LAN | Нічого не злито | Не знайдено | Не знайдено | Не знайдено |
| ARM | UI і воркер для arm64; перевіряє платформи кожного сервісу перед розгортанням ([ARM](arm.md)) | Бінарні файли для arm64 і armv7 ([випуск][m4b-release]) | README заявляє amd64 і arm64, arm32 з обмеженнями, і налаштовує QEMU ([README][igm-arch]) | Потребує емуляції binfmt для образів лише під amd64 ([README][ii-arm]) | README каже, що на Raspberry Pi не працює ([README][cf-raspberry]) | Залежно від доповнення; ProxyRack лише для amd64 ([конфігурація][ha-proxyrack]) |
| UI | Вебінтерфейс, а також клієнти Desktop, Android, MCP і Home Assistant | CLI, меню і локальна вебпанель, типово прив'язана до 127.0.0.1 ([код][m4b-bind]) | CLI, меню і, за README, вебінтерфейс на порту 4747, доступний у LAN ([README][igm-webui]) | Немає, це скрипт | Сторінка закладок на порту 80 плюс Portainer ([README][cf-ui]) | Панель доповнення Home Assistant |
| Коміти в типовій гілці, з 2026-08-06 по 2026-11-04 | 286 | 6, усі документація (5.0.0 в окремій історії) | 6 | 31 | 0 | 23 |
| Найновіший випуск | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Версійних випусків немає | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Вихідні виклики, крім застосунків | Випуски GitHub раз на день (`CASHPILOT_UPDATE_CHECK=off` це вимикає, [код][cp-update]); `api.ipify.org`, `ifconfig.me` або `icanhazip.com` раз на годину з кожного воркера, щоб дізнатися його публічну IP (`CASHPILOT_EGRESS_DETECT=off` це вимикає, [код][cp-egress]); CoinGecko і Frankfurter для курсів обміну ([код][cp-rates]); mempool.space, api.kaspa.org і публічні вузли RPC Ethereum, Polygon і Solana для [ончейн-балансів](onchain.md); кожен провайдер — для збирачів. Браузер завантажує Google Fonts ([шаблон][cp-cdn]) і Chart.js з jsDelivr ([шаблон][cp-chartjs]) | Випуски GitHub для перевірки оновлень ([код][m4b-updater]); Docker Hub і ghcr.io для перевірки тегів образів ([код][m4b-registry]); коли ви запускаєте перевірку IP, `api.ipify.org`, `ifconfig.me` або `icanhazip.com` для вашої публічної IP і `ip-api.com` через звичайний HTTP для оцінок IP ([код][m4b-ipscore]) | Випуски GitHub ([код][igm-version]); `api.ipify.org`, `ifconfig.me` або `icanhazip.com` для вашої публічної IP ([код][igm-ifconfig]); `ip-api.com` через звичайний HTTP для оцінок IP ([код][igm-ipscore]). Закритий бінарний файл не перевірявся | Не знайдено | Не знайдено | Не знайдено |

У коді, який ми прочитали, жоден із проєктів не надсилає телеметрію використання. Закритий бінарний файл IGM прочитати не вдалося.

Кожен проєкт тут передає облікові дані застосунків у контейнери як змінні середовища, а InternetIncome частину з них передає ще й як аргументи команд, тож на хості, де працюють застосунки, вони у відкритому вигляді в конфігурації контейнера Docker (`Env` і `Args` у `docker inspect`), і їх може прочитати будь-хто з доступом до Docker. Рядок «Облікові дані на диску» описує лише збережену копію.

## Як ми рахували { #how-we-counted }

- **CashPilot.** Сервіси в каталозі зі статусом active або beta і з образом Docker, без урахування обчислень на GPU і майнінгових пулів. Число на цій сторінці береться з `scripts/generate_readme_tables.py`, і CI падає, якщо воно розходиться.
- **money4band 5.0.0.** Один файл JSON на застосунок у `config/catalog/supported/`: 15. «35 apps» у README також враховує каталог спільноти, який типово вимкнено ([конфігурація][m4b-community]), застосунки без образу Docker і покинуті застосунки.
- **IGM.** Записи в `apps.json`: 20, усі ввімкнені. Контейнер проксі, Watchtower і sidecar-контейнери для отримання винагород не враховано.
- **InternetIncome.** Кожен блок коментаря `# Starting ... container` в `internetIncome.sh`, крім блоків проксі та Watchtower: 24. Блоки Chrome і Firefox для Ebesucher — це один застосунок, так само EarnFM і EarnFM Fleetshare, які використовують той самий акаунт EarnFM. Блок розширень Depin запускає Grass і Gradient ([скрипт][ii-depin]), два застосунки. Разом 23. Таблиця в README перелічує 27 застосунків, деякі лише з посиланням для реєстрації.
- **CashFactory.** Сервіси для заробітку в `docker-compose.yml`: 11. Portainer, вебсервер і два Watchtower не враховано. Один сервіс закоментовано.
- **Доповнення HA.** Теки доповнень із файлом конфігурації: 10.

Ми не перевіряли, чи кожен застосунок у кожному списку досі виплачує гроші.

## У чому CashPilot відстає { #where-cashpilot-is-behind }

- Сервіси, яким потрібні мережа хоста, опубліковані порти, томи, пристрої або додаткові мережеві можливості, не можуть працювати через проксі, тож 10 з <!-- n:docker -->21<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi і Kryptex Pool (Pearl)) заробляють лише з власної IP сервера ([копії через проксі](proxies.md#what-cannot-run-through-a-proxy)).
- Менше застосунків, які він запускає сам, ніж в InternetIncome.
- Немає отримання щоденних винагород і автоматичного оновлення образів.
- 12 з <!-- n:docker -->21<!-- /n --> образів застосунків для заробітку стежать за найновішим тегом свого видавця.
- Проксі сокета ще не є межею для root: скомпрометований воркер усе ще може створювати контейнери в межах своєї політики, а двокрокові втечі (приєднання до простору імен процесів іншого контейнера, символьне посилання в дозволеній теці) не відхиляються ([подробиці](security-defaults.md)).
- Ключ шифрування збережених облікових даних лежить у тому самому томі, що й дані, а на кожному воркері облікові дані застосунків для заробітку у відкритому вигляді в конфігурації контейнера Docker.
- Деяким збирачам потрібні cookie або токен, скопійовані з браузера, і частина з них спливає, тож відстеження заробітку для цих сервісів потребує догляду.
- UI завантажує шрифти та Chart.js зі сторонніх CDN.
- Ізоляція LAN залишається вимкненою на оновленій інсталяції, чиї застосунки для заробітку на типовому bridge Docker, доки ви її не ввімкнете, вона не дає бар'єра мережі, вказаній у `CASHPILOT_CONTAINER_NETWORK` ([ізоляція](isolation.md#modes)), а вузол Mysterium, розгорнутий до 2.0.6 включно, залишається в мережі хоста, без бар'єра, доки ви його не перерозгорнете ([Mysterium за бар'єром](mysterium-fence.md)).
- Набагато менша спільнота, ніж у money4band.
- Він часто випускає нові версії, іноді кілька разів на день.

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
