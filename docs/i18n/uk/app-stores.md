---
source_hash: e99e2c0c80bb
---
# Магазини застосунків { #app-stores }

CashPilot можна встановити з магазину застосунків кількох систем для домашніх серверів.
Кожен такий пакет встановлює панель (`drumsergio/cashpilot`) і воркер
(`drumsergio/cashpilot-worker`), який запускає й зупиняє контейнери
сервісів. Лише пакети CasaOS і Runtipi в цьому репозиторії також
встановлюють проксі сокета Docker з `docker-compose.yml`, тому їхній воркер
ніколи не тримає «сирий» сокет Docker. Шаблони Unraid, застосунок TrueNAS і
пакет у відкритому pull request до магазину застосунків CasaOS досі монтують сокет Docker
безпосередньо у воркер.

Хоч яким магазином ви користуєтеся, тримайте панель у своїй LAN або VPN. Вона може віддавати команди
воркеру, а воркер керує Docker на хості. Там, де воркер сам тримає
сокет, це означає root на хості.

## Уже доступно { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Знайдіть **CashPilot** на вкладці Apps і встановіть обидва шаблони:
`cashpilot` (панель) і `cashpilot-worker`. Задайте однаковий
`CASHPILOT_API_KEY` в обох.

Шаблони беруться з https://github.com/GeiserX/docker-templates і стежать
за тегом образу `latest`, тож користувачі Community Applications отримують кожен випуск
без зміни шаблону.

### TrueNAS SCALE { #truenas-scale }

CashPilot є в train **community** TrueNAS. Відкрийте Apps, потім Discover Apps,
і знайдіть **CashPilot**.

Визначення застосунку підтримується за адресою
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot і закріплює
точний дайджест образу. Власні боти TrueNAS переводять його на нові випуски, тому він може
відставати на кілька випусків від найновішого CashPilot.

## Очікує на перевірку { #waiting-for-review }

### CasaOS { #casaos }

Pull request до магазину застосунків CasaOS відкрито:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Поки його не злито, встановіть застосунок як власний: у CasaOS виберіть App Store,
потім Custom Install, потім Import і вставте вміст
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Потрібна CasaOS 0.4.5 або новіша: починаючи з цього випуску її менеджер застосунків побудовано на
Docker Compose 2.23, який читає політику проксі сокета з файлу.
Старіші версії її відкидають, і тоді воркер не може дістатися до Docker.

Цей файл закріплює точний випуск. Перш ніж імпортувати його, задайте обидва теги образів
(`drumsergio/cashpilot` і `drumsergio/cashpilot-worker`) на найновіший
випуск з https://github.com/GeiserX/CashPilot/releases. Політика проксі
у файлі стежить за `main`; якщо сторінка статусу воркера каже, що його політика
застаріла, імпортуйте файл знову.

## Підготовлено, ще не подано { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Пакет готовий у
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
— але його ще немає в магазині застосунків Runtipi. Щоб користуватися ним уже зараз, додайте його до власного магазину
застосунків, яким ви керуєте, за документацією Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Не пропонується { #not-offered }

Umbrel потребує іншої архітектури воркера, бо застосунки Umbrel звертаються до Docker
через контейнер Docker-in-Docker, а не через сокет хоста. Ми цього не
тестували, тому пакета для Umbrel поки немає.

Для будь-якої іншої системи використовуйте `docker-compose.yml` з репозиторію, як описано в розділі
[Перші кроки](getting-started.md).
