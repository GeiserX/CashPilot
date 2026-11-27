---
source_hash: e99e2c0c80bb
---
# Магазины приложений { #app-stores }

CashPilot можно установить из магазина приложений нескольких систем для домашних серверов.
Каждая публикация устанавливает панель (`drumsergio/cashpilot`) и воркер
(`drumsergio/cashpilot-worker`), который запускает и останавливает контейнеры
сервисов. Только пакеты CasaOS и Runtipi из этого репозитория также
устанавливают прокси сокета Docker из `docker-compose.yml`, поэтому их воркер
никогда не держит сам сокет Docker. Шаблоны Unraid, приложение TrueNAS и
пакет в открытом pull request в магазин приложений CasaOS по-прежнему монтируют сокет
Docker прямо в воркер.

Каким бы магазином вы ни пользовались, держите панель в своей LAN или VPN. Она может отдавать команды
воркеру, а воркер управляет Docker на хосте. Там, где воркер сам держит
сокет, это root на хосте.

## Уже опубликовано { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Найдите **CashPilot** на вкладке Apps и установите оба шаблона:
`cashpilot` (панель) и `cashpilot-worker`. Задайте одинаковый
`CASHPILOT_API_KEY` в обоих.

Шаблоны берутся из https://github.com/GeiserX/docker-templates и следуют за
тегом образа `latest`, поэтому пользователи Community Applications получают каждый выпуск
без изменения шаблона.

### TrueNAS SCALE { #truenas-scale }

CashPilot есть в train **community** TrueNAS. Откройте Apps, затем Discover Apps,
и найдите **CashPilot**.

Определение приложения поддерживается в
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot и закрепляет
точный digest образа. Собственные боты TrueNAS переводят его на новые выпуски, поэтому оно может
отставать от новейшего CashPilot на несколько выпусков.

## Ожидает проверки { #waiting-for-review }

### CasaOS { #casaos }

Pull request в магазин приложений CasaOS открыт:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Пока его не слили, устанавливайте как собственное приложение: в CasaOS выберите App Store,
затем Custom Install, затем Import, и вставьте содержимое
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Нужна CasaOS 0.4.5 или новее: начиная с этого выпуска её менеджер приложений построен на
Docker Compose 2.23, который читает политику прокси сокета из файла.
Более старые версии отбрасывают её, и тогда воркер не может достучаться до Docker.

Этот файл закрепляет точный выпуск. Перед импортом задайте оба тега образов
(`drumsergio/cashpilot` и `drumsergio/cashpilot-worker`) равными новейшему
выпуску с https://github.com/GeiserX/CashPilot/releases. Политика прокси
в файле следует за `main`; если страница статуса воркера сообщает, что его политика
устарела, импортируйте файл снова.

## Подготовлено, но ещё не отправлено { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Пакет готов в
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
но его ещё нет в магазине приложений Runtipi. Чтобы пользоваться им уже сейчас, добавьте его в собственный магазин
приложений, которым вы управляете, по документации Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Не предлагается { #not-offered }

Umbrel требует другого устройства воркера, потому что приложения Umbrel обращаются к Docker
через контейнер Docker-in-Docker, а не через сокет хоста. Мы это не
тестировали, поэтому пакета для Umbrel пока нет.

Для любой другой системы используйте `docker-compose.yml` из репозитория, как описано в
[Начале работы](getting-started.md).
