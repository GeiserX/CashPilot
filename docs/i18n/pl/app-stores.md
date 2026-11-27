---
source_hash: e99e2c0c80bb
---
# Sklepy z aplikacjami { #app-stores }

CashPilot możesz zainstalować ze sklepu z aplikacjami kilku systemów dla serwerów domowych.
Każdy wpis instaluje panel (`drumsergio/cashpilot`) i workera
(`drumsergio/cashpilot-worker`), który uruchamia i zatrzymuje kontenery
usług. Tylko pakiety CasaOS i Runtipi w tym repozytorium instalują też
socket proxy Dockera z `docker-compose.yml`, więc ich worker
nigdy nie trzyma surowego gniazda Dockera. Szablony Unraid, aplikacja TrueNAS i
pakiet w otwartym pull requeście do sklepu CasaOS nadal montują gniazdo
Dockera bezpośrednio w workerze.

Niezależnie od sklepu, trzymaj panel w swojej sieci LAN lub VPN. Panel może wydawać polecenia
workerowi, a worker steruje Dockerem na hoście. Tam, gdzie worker sam trzyma
gniazdo, oznacza to uprawnienia roota na hoście.

## Dostępne już dziś { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Wyszukaj **CashPilot** w zakładce Apps i zainstaluj oba szablony:
`cashpilot` (panel) i `cashpilot-worker`. Ustaw ten sam
`CASHPILOT_API_KEY` w obu.

Szablony pochodzą z https://github.com/GeiserX/docker-templates i śledzą
tag obrazu `latest`, więc użytkownicy Community Applications dostają każde wydanie
bez zmiany szablonu.

### TrueNAS SCALE { #truenas-scale }

CashPilot jest w pociągu **community** TrueNAS. Otwórz Apps, potem Discover Apps,
i wyszukaj **CashPilot**.

Definicja aplikacji jest utrzymywana w
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot i przypina
dokładny digest obrazu. Własne boty TrueNAS przenoszą ją na nowe wydania, więc może
być kilka wydań za najnowszym CashPilot.

## Czeka na przegląd { #waiting-for-review }

### CasaOS { #casaos }

Pull request do sklepu z aplikacjami CasaOS jest otwarty:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Dopóki nie zostanie scalony, zainstaluj CashPilot jako własną aplikację: w CasaOS wybierz App Store,
potem Custom Install, potem Import, i wklej zawartość
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Wymaga to CasaOS 0.4.5 lub nowszego: od tego wydania jego menedżer aplikacji opiera się na
Docker Compose 2.23, który czyta z pliku politykę socket proxy.
Starsze wersje ją pomijają i worker nie może wtedy połączyć się z Dockerem.

Ten plik przypina dokładne wydanie. Zanim go zaimportujesz, ustaw oba tagi obrazów
(`drumsergio/cashpilot` i `drumsergio/cashpilot-worker`) na najnowsze
wydanie z https://github.com/GeiserX/CashPilot/releases. Polityka proxy
w pliku śledzi `main`; jeśli strona stanu workera mówi, że jego polityka jest
nieaktualna, zaimportuj plik ponownie.

## Przygotowane, jeszcze niezgłoszone { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Pakiet jest gotowy w
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
ale jeszcze nie ma go w sklepie z aplikacjami Runtipi. Aby użyć go już teraz, dodaj go do własnego sklepu
z aplikacjami, który kontrolujesz, zgodnie z dokumentacją Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Niedostępne { #not-offered }

Umbrel wymaga innej konstrukcji workera, ponieważ aplikacje Umbrel łączą się z Dockerem
przez kontener Docker-in-Docker, a nie przez gniazdo hosta. Nie testowaliśmy
tego, więc pakietu dla Umbrel jeszcze nie ma.

W każdym innym systemie użyj `docker-compose.yml` z repozytorium, jak w
[Pierwszych krokach](getting-started.md).
