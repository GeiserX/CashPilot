---
source_hash: b48a8fc19aa4
---
# Jak CashPilot wypada w porównaniu { #how-cashpilot-compares }

Ta strona porównuje CashPilot z innymi otwartymi projektami, które uruchamiają w Dockerze kilka aplikacji dochodu pasywnego. Każdy projekt sprawdziliśmy 2026-11-04, a CashPilot ponownie 2026-11-28. Każda komórka o innym projekcie prowadzi do pliku, z którego pochodzi, przy ustalonym commicie, więc możesz to sam sprawdzić. Jeśli komórka jest błędna lub nieaktualna, [zgłoś problem](https://github.com/GeiserX/CashPilot/issues).

## Porównywane projekty { #projects-compared }

| Projekt | Co sprawdziliśmy | Gwiazdki 2026-11-04 | Licencja |
|---|---|---|---|
| [money4band][m4b-tree] | Wydanie 5.0.0, commit tagu `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` w `65e900d` (2026-10-20) oraz twierdzenia README o jego binarce 3.0.0-beta.9 | 238 | Własnościowa, [własna licencja v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` w `db9338a` (2026-11-03) | 257 | Brak pliku LICENSE. [README][ii-license] pozwala kopiować oryginał i zabrania rozpowszechniania zmienionych kopii |
| [CashFactory][cf-tree] | `main` w `0ff4bd0` (2025-04-08) | 410 | Plik [LICENSE][cf-license-file] to GPL-3.0, ale [README][cf-license] zabrania rozpowszechniania zmienionych kopii |
| [home-assistant-passive-income][ha-tree] (dodatki HA) | Wydanie 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Wydanie v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band ma dwie linie kodu. Jego domyślna gałąź `main` (`3bfafb1`) nadal zawiera kod 4.x, a ostatnia zmiana kodu była tam 2026-03-03. Wydanie 5.0.0 jest zbudowane z osobnej historii. Porównujemy 5.0.0, bo to właśnie dostarcza jego najnowsze wydanie.

Interfejs webowy IGM, zarządzanie flotą i binarka instalatora mają zamknięty kod i nie ma ich w repozytorium. Tam, gdzie komórka od nich zależy, mówi „README twierdzi” i prowadzi do linii README. Wszystko inne w kolumnie IGM pochodzi ze skryptów powłoki i plików compose w repozytorium.

Pominięte: [earning-machine](https://github.com/jf-m/earning-machine) i [passiveMachine](https://github.com/Xpl0itU/passiveMachine) nie mają commitów od 2024. Wyszukiwanie na GitHubie nie znalazło nic innego utrzymywanego, co uruchamia więcej niż jedną aplikację, tylko obrazy z jedną aplikacją.

## W skrócie { #short-version }

- **InternetIncome, money4band, IGM i, od v1.69.0, CashPilot mogą zarabiać na wielu IP przez proxy.** Pierwsze trzy uruchamiają każdą aplikację raz na proxy, a proxy to główna funkcja InternetIncome. CashPilot uruchamia dodatkowe kopie usługi już wdrożonej na workerze, każdą przez proxy SOCKS5, HTTP CONNECT lub węzeł wyjściowy Tailscale ([kopie przez proxy](proxies.md)).
- **InternetIncome uruchamia 23 aplikacje, IGM 20, a worker CashPilot <!-- n:docker -->21<!-- /n -->.** CashPilot śledzi łącznie więcej usług (<!-- n:live -->50<!-- /n -->), bo śledzi też usługi w postaci rozszerzeń przeglądarki, aplikacji desktopowych i usług GPU, których nie uruchamia. Od v1.64.0 może też uruchomić dowolny wskazany przez ciebie obraz jako [własną usługę](custom-services.md).
- **money4band i IGM odbierają za ciebie codzienne nagrody i aktualizują obrazy aplikacji przez Watchtower.** CashPilot nie robi żadnej z tych rzeczy. Pobiera obraz ponownie tylko przy wdrożeniu lub ponownym wdrożeniu.
- **CashPilot jako jedyny z nich odczytuje salda z twoich kont u dostawców i przechowuje historię.** money4band 5.0.0 pokazuje szacunki z własnego katalogu, a nie z twoich kont. Pozostałe prowadzą do paneli poszczególnych dostawców.
- **CashPilot jako jedyny z otwartym kodem ma jeden UI dla wielu serwerów.** README IGM twierdzi, że ma zarządzanie flotą, ale ten kod jest w jego zamkniętej binarce.
- **Od v1.70.0 CashPilot jako jedyny z nich domyślnie trzyma kontenery aplikacji zarobkowych z dala od twojego LAN-u, z ograniczeniami.** Jest to włączone w nowych instalacjach i w zaktualizowanych instalacjach bez aplikacji zarobkowej na domyślnym bridge'u Dockera. Zaktualizowana instalacja, której aplikacje zarobkowe już są na tym bridge'u, trzyma je tam, dopóki nie włączysz izolacji, a sieć wskazana w `CASHPILOT_CONTAINER_NETWORK` nie dostaje od CashPilot żadnej bariery ([izolacja](isolation.md#modes)). Od 2.0.7 Mysterium też działa za barierą; węzeł wdrożony w wersji do 2.0.6 włącznie zostaje w sieci hosta, bez bariery, dopóki nie wdrożysz go ponownie ([Mysterium za barierą](mysterium-fence.md)).

## Obok siebie { #side-by-side }

Kolumna CashPilot opisuje v3.0.1. Każda jej komórka jest krótka, a szczegóły i linki do kodu są w [uwagach pod tabelą](#cashpilot-notes). Pozostałe kolumny opisują commity z tabeli powyżej.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Dodatki HA |
|---|---|---|---|---|---|---|
| Aplikacje, które potrafi uruchomić (zobacz [jak liczyliśmy](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> uruchamiane przez workera, plus [własne obrazy](custom-services.md); <!-- n:live -->50<!-- /n --> śledzonych łącznie | 15 ([katalog][m4b-catalog]). README mówi 35, co [obejmuje][m4b-readme-35] aplikacje społeczności i porzucone | 20 ([apps.json][igm-apps]) | 23 ([skrypt][ii-script]) | 11 ([plik compose][cf-compose]) | 10 ([foldery dodatków][ha-tree]) |
| Jak się go instaluje | Docker Compose: jeden UI plus worker na każdym serwerze ([flota](fleet.md)) | CLI w Pythonie lub gotowa binarka, która zapisuje plik compose ([wydanie][m4b-tree]) | Instalator `curl \| sh` ([README][igm-install]), który pobiera zamkniętą binarkę, sprawdzaną tylko względem pliku SHA256SUMS z tego samego wydania ([instalator][igm-installer-sums]) | Jeden skrypt bash z 1608 liniami, który wywołuje `sudo docker run` ([skrypt][ii-script]) | Statyczny plik compose plus `setup.sh` uruchamiany przez sudo ([setup][cf-setup]) | Repozytorium dodatków Home Assistant; wymaga Home Assistant OS lub Supervised |
| Wiele serwerów, jeden widok | Tak ([flota](fleet.md)) | Nie, jeden stos na urządzenie | README twierdzi, że tak, w zamkniętej binarce ([README][igm-features]) | Nie | Nie | Nie |
| Wiele proxy lub IP | Tak, przez proxy SOCKS5, HTTP CONNECT lub węzły wyjściowe Tailscale ([kopie przez proxy](proxies.md), [uwagi](#cashpilot-notes)) | Tak ([README][m4b-features], [kod][m4b-multiproxy]) | Tak ([README][igm-features], [compose][igm-proxy]) | Tak, to jego główna funkcja ([README][ii-readme-top]) | Nie | Nie |
| Zarobki | <!-- n:collectors -->20<!-- /n --> kolektorów odczytuje salda z twoich kont u dostawców i przechowuje historię | Szacunki z zakresów w katalogu, nie dane z konta ([kod][m4b-earnings]) | Nic nie znaleziono w skryptach | Brak | Brak | Brak |
| Wypłaty | Proponuje wypłatę, gdy saldo spada, i zapisuje ją po twoim potwierdzeniu ([schemat][cp-payouts]) | Brak | Brak | Brak | Brak | Brak |
| Odbieranie codziennych nagród | Nie | Tak, kontenery pomocnicze ([README][m4b-features]) | Tak ([README][igm-features], [compose][igm-sidecars]) | Nie | Nie | Nie |
| Dane logowania w spoczynku | Zaszyfrowane (Fernet) w bazie danych UI ([uwagi](#cashpilot-notes)) | Zaszyfrowane (Fernet); plik klucza leży w katalogu danych ([kod][m4b-crypto]) | Zaszyfrowane (AES-256 przez openssl); plik klucza leży obok sejfu ([kod][igm-encryptor]) | Jawny tekst w `properties.conf`; niektóre hasła są przekazywane jako argumenty `docker run` ([skrypt][ii-password-arg]) | Jawny tekst w `.env` ([plik][cf-env]) | Opcje dodatku, zapisywane przez Supervisor w `/data/options.json` ([dokumentacja HA][ha-options]) |
| Ustawienia kontenerów aplikacji zarobkowych | Odebrane wszystkie uprawnienia (capabilities), `no-new-privileges`, limit pids; kontenery uprzywilejowane odrzucane ([uwagi](#cashpilot-notes)) | `no-new-privileges` na każdej nieuprzywilejowanej usłudze ([kod][m4b-nnp]); kontener proxy jest uprzywilejowany z `NET_ADMIN` ([szablon][m4b-tun]) | Nic nie ustawiono dla usług aplikacji; Mysterium dostaje `NET_ADMIN` ([compose][igm-hosting-myst]); kontener proxy dostaje `NET_ADMIN`, z `no-new-privileges` i limitem pids ([compose][igm-proxy]) | Ebesucher działa z `seccomp=unconfined` ([skrypt][ii-seccomp]); kontenery proxy i Mysterium dostają `NET_ADMIN` | Nic nie ustawiono | Żaden dodatek nie prosi o tryb uprzywilejowany, sieć hosta ani dostęp do API Dockera ([przykładowa konfiguracja][ha-config]) |
| Gniazdo Dockera zamontowane w | Socket proxy, tylko do odczytu, oraz jednorazowy kontener migracji ([uwagi](#cashpilot-notes)) | Watchtower ([szablon][m4b-watchtower]) | Watchtower, tylko do odczytu, z `no-new-privileges` ([compose][igm-watchtower]) | Pięć pomocniczych kontenerów do restartów ([skrypt][ii-sock-helper]) i Watchtower ([skrypt][ii-watchtower]) | Portainer, publikowany na portach 8000, 9000 i 9443 na wszystkich interfejsach ([compose][cf-portainer]), oraz dwa Watchtowery ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Brak |
| Tagi obrazów | <!-- n:pinned -->9<!-- /n --> z <!-- n:docker -->21<!-- /n --> obrazów aplikacji zarobkowych przypiętych do wersji lub digestu; reszta jest ruchoma | Wszystkie 15 obrazów aplikacji używa `:latest` ([przykład][m4b-image]); kontener proxy przypięty do v2.6.0, Watchtower do `:1` | Bez tagu, więc Docker używa `latest` ([compose][igm-hosting]); tag jest ustawiony tylko dla niektórych buildów ARM | Głównie `:latest` ([przykład][ii-seccomp]); EarnApp `:lite`, Honeygain przypięty do 0.6.6 przy pracy przez proxy na amd64 ([skrypt][ii-honeygain]), Traffmonetizer z tagami per architektura na ARM; Watchtower `:nightly` | `:latest` lub bez tagu, z wyjątkiem EarnApp `:lite` ([compose][cf-compose]) | Jedna wersja na dodatek, podbijana przez codzienne zadanie CI ([workflow][ha-bump], [przykład][ha-dockerfile]) |
| Aktualizacje obrazów aplikacji | Pobierane ponownie przy każdym wdrożeniu lub ponownym wdrożeniu; brak automatycznego aktualizatora | Watchtower ([szablon][m4b-watchtower]) | Watchtower co 4 godziny ([compose][igm-watchtower]) | Watchtower raz dziennie, jeśli go włączysz ([skrypt][ii-watchtower]) | Dwa Watchtowery, każdy ograniczony do jednej aplikacji, PacketStream ([compose][cf-watchtower-ps]) i EarnFM ([compose][cf-watchtower-efm]); pozostałe 9 aplikacji nie jest aktualizowanych | Aktualizacje dodatków Home Assistant |
| Izolacja LAN | Domyślnie włączona w nowych instalacjach ([izolacja](isolation.md#lan-isolation-by-default), [uwagi](#cashpilot-notes)) | Własna podsieć bridge'a ([konfiguracja][m4b-subnet]), która nie blokuje LAN-u | Nic nie scalono | Nic nie znaleziono | Nic nie znaleziono | Nic nie znaleziono |
| ARM | UI i worker dla arm64, ze sprawdzeniem platformy przed każdym wdrożeniem ([ARM](arm.md)) | Binarki arm64 i armv7 ([wydanie][m4b-release]) | README twierdzi, że amd64 i arm64, arm32 z ograniczeniami, i konfiguruje QEMU ([README][igm-arch]) | Wymaga emulacji binfmt dla obrazów tylko amd64 ([README][ii-arm]) | README mówi, że nie działa na Raspberry Pi ([README][cf-raspberry]) | Zależnie od dodatku; ProxyRack tylko amd64 ([konfiguracja][ha-proxyrack]) |
| UI | Interfejs webowy oraz klienty Desktop, Android, MCP i Home Assistant | CLI, menu i lokalny panel webowy domyślnie powiązany z 127.0.0.1 ([kod][m4b-bind]) | CLI, menu i według README interfejs webowy na porcie 4747 dostępny w LAN-ie ([README][igm-webui]) | Brak, to skrypt | Strona z zakładkami na porcie 80 plus Portainer ([README][cf-ui]) | Panel dodatku Home Assistant |
| Najnowsze wydanie | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Brak wersjonowanych wydań | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Połączenia wychodzące poza aplikacjami | Sprawdzanie aktualizacji, wykrywanie publicznego IP, kursy wymiany i salda on-chain; czcionki i Chart.js z CDN ([uwagi](#cashpilot-notes)) | Wydania na GitHubie, do sprawdzania aktualizacji ([kod][m4b-updater]); Docker Hub i ghcr.io, do sprawdzania tagów obrazów ([kod][m4b-registry]); gdy uruchomisz sprawdzenie IP, `api.ipify.org`, `ifconfig.me` lub `icanhazip.com` po twój publiczny IP i `ip-api.com` przez zwykłe HTTP po oceny IP ([kod][m4b-ipscore]) | Wydania na GitHubie ([kod][igm-version]); `api.ipify.org`, `ifconfig.me` lub `icanhazip.com` po twój publiczny IP ([kod][igm-ifconfig]); `ip-api.com` przez zwykłe HTTP po oceny IP ([kod][igm-ipscore]). Zamkniętej binarki nie sprawdzono | Nic nie znaleziono | Nic nie znaleziono | Nic nie znaleziono |

### Uwagi do kolumny CashPilot { #cashpilot-notes }

- **Wiele proxy lub IP.** Od v1.69.0 CashPilot uruchamia dodatkowe kopie usługi już wdrożonej na workerze, każdą przez własne proxy. SOCKS5 i HTTP CONNECT przenoszą tylko TCP: tunel wypuszcza tylko TCP do portu proxy, więc przekaźniki UDP SOCKS5 są odrzucane. Węzeł wyjściowy Tailscale przenosi też UDP. Aplikacja zarobkowa dzieli przestrzeń nazw sieci z kontenerem tunelu ([kod][cp-proxy-deploy]). Ta przestrzeń nazw wypuszcza tylko loopback, tunel i własne połączenie tunelu z proxy: TCP do jego adresu i portu albo oznaczone pakiety tailscaled ([zapora tunelu][cp-tunnel-fw]). Dlatego martwe proxy zatrzymuje aplikację zarobkową, zamiast dopuścić do wycieku jej ruchu ([jak to działa](proxies.md#how-it-works)). Usługa nie może działać przez proxy, gdy potrzebuje sieci hosta, publikowanych portów, wolumenów, urządzeń, GPU albo `NET_ADMIN`, `NET_RAW` lub `SYS_ADMIN`, albo gdy jej regulamin zabrania proxy. Dlatego <!-- n:noproxy -->10<!-- /n --> z <!-- n:docker -->21<!-- /n --> zarabia tylko z własnego IP serwera ([co nie może](proxies.md#what-cannot-run-through-a-proxy)).
- **Zarobki.** Niektóre kolektory potrzebują ciasteczka lub tokena skopiowanego z przeglądarki, a część z nich wygasa. Przewodnik każdej usługi mówi, które.
- **Dane logowania w spoczynku.** UI trzyma plik klucza szyfrowania w tym samym wolumenie danych co bazę danych ([kod][cp-fernet]). Dane logowania aplikacji zarobkowych trafiają do każdego workera jako zmienne środowiskowe kontenera, więc są jawnym tekstem w konfiguracji Dockera tego workera (`docker inspect`).
- **Ustawienia kontenerów aplikacji zarobkowych.** Worker odbiera wszystkie uprawnienia (capabilities), a potem przywraca te, które katalog wymienia dla usługi. Ustawia `no-new-privileges` i limit pids oraz odrzuca kontenery uprzywilejowane ([kod][cp-hardening], [kod][cp-privileged], [domyślne zabezpieczenia](security-defaults.md)). Mysterium działa we własnej przestrzeni nazw sieci na bridge'u za barierą z `NET_ADMIN`, `SETUID` i `SETGID`, na obrazie przypiętym przez digest ([katalog][cp-myst]). Opcjonalne środowisko uruchomieniowe gVisor może dodać jądro w przestrzeni użytkownika ([środowiska uruchomieniowe](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Gniazdo Dockera.** Od v1.71.0 gniazdo montuje tylko socket proxy: sockguard 2.4.7, przypięty przez digest, tylko do odczytu ([compose][cp-sock]). Worker dostaje przefiltrowaną kopię, która odrzuca kontenery uprzywilejowane, montowanie `/` lub gniazda oraz uprawnienia (capabilities) i urządzenia spoza katalogu ([socket proxy](security-defaults.md#docker-socket-proxy)). Jednorazowy kontener `cashpilot-migrate` też montuje gniazdo: oznacza etykietami to, co utworzyły starsze wydania, na potrzeby izolacji właściciela w proxy, i kończy działanie, zanim proxy wystartuje ([compose][cp-migrate]). Aplikacja zarobkowa nigdy nie dostaje gniazda ([kod][cp-mounts]). Proxy nie jest jeszcze granicą uprawnień roota: przy ustawionym `CASHPILOT_COMPOSE_DIR` lub `CASHPILOT_PROXY_BIND_MOUNTS` dowiązanie symboliczne podłożone w dozwolonym folderze sięga `/` hosta w dwóch wdrożeniach ([szczegóły](security-defaults.md#docker-socket-proxy)). Listingi Unraid i TrueNAS nadal montują w workerze surowe gniazdo ([sklepy z aplikacjami](app-stores.md)).
- **Izolacja LAN.** Domyślnie włączona od v1.70.0, w nowych instalacjach i w zaktualizowanych instalacjach bez aplikacji zarobkowej na domyślnym bridge'u Dockera. Worker umieszcza aplikacje zarobkowe na własnym bridge'u i zapisuje dla niego tabelę zapory ([kod][cp-fence]). Tabela odrzuca zakresy prywatne, zakres tailnetu, metadane chmury, podsieci podłączone do hosta i sam host. Przy włączonym wykrywaniu publicznego IP odrzuca też publiczny IP domu ([izolacja](isolation.md#lan-isolation-by-default)). Zaktualizowana instalacja, której aplikacje zarobkowe już są na domyślnym bridge'u, zostaje tam, dopóki nie naciśniesz **Turn on isolation** (Włącz izolację). `CASHPILOT_ISOLATION=off` ją wyłącza. Przy ustawionym `CASHPILOT_CONTAINER_NETWORK` CashPilot nie zapisuje bariery dla tej sieci, a reguły zapory należą do ciebie. Na Podmanie nie ma bariery, a strona floty to pokazuje ([tryby](isolation.md#modes), [kod][cp-fence-mode]). Od 2.0.7 Mysterium też jest za barierą. Węzeł wdrożony w wersji do 2.0.6 włącznie zostaje w sieci hosta, dopóki nie wdrożysz go ponownie ([Mysterium za barierą](mysterium-fence.md)). Test pokazuje, do czego aplikacje zarobkowe mają dostęp ([test](isolation-check.md)).
- **Połączenia wychodzące.** Poza samymi aplikacjami CashPilot łączy się z:
    - wydaniami na GitHubie, raz dziennie, żeby sprawdzić aktualizacje (`CASHPILOT_UPDATE_CHECK=off` to wyłącza, [kod][cp-update]).
    - `api.ipify.org`, `ifconfig.me` lub `icanhazip.com` raz na godzinę z każdego workera, po jego publiczny IP (`CASHPILOT_EGRESS_DETECT=off` to wyłącza, [kod][cp-egress]).
    - CoinGecko i Frankfurter, po kursy wymiany ([kod][cp-rates]).
    - mempool.space, api.kaspa.org i publicznymi węzłami RPC Ethereum, Ethereum Classic, Polygon i Solany, po [salda on-chain](onchain.md).
    - iptoasn.com, po tabelę nazw sieci, najwyżej raz w tygodniu i tylko wtedy, gdy worker ma włączoną [aktywność](activity.md#network-names-and-countries) ([kod][cp-ipgeo]).
    - każdym dostawcą, dla kolektorów.

    Przeglądarka ładuje Google Fonts ([szablon][cp-cdn]) i Chart.js z jsDelivr ([szablon][cp-chartjs]).

W kodzie, który przeczytaliśmy, żaden z projektów nie wysyła telemetrii użytkowania. Zamkniętej binarki IGM nie dało się przeczytać.

Każdy z tych projektów przekazuje kontenerom dane logowania aplikacji jako zmienne środowiskowe, a InternetIncome część z nich także jako argumenty polecenia, więc na hoście, który uruchamia aplikacje, są one jawnym tekstem w konfiguracji kontenera Dockera (`Env` i `Args` w `docker inspect`), czytelnym dla każdego z dostępem do Dockera. Wiersz „Dane logowania w spoczynku” opisuje tylko zapisaną kopię.

## Jak liczyliśmy { #how-we-counted }

- **CashPilot.** Usługi w katalogu ze statusem active lub beta i obrazem Dockera, bez mocy obliczeniowej GPU i pul wydobywczych. Liczba na tej stronie pochodzi z `scripts/generate_readme_tables.py`, a CI kończy się błędem, jeśli się rozjedzie.
- **money4band 5.0.0.** Jeden plik JSON na aplikację w `config/catalog/supported/`: 15. „35 apps” z README liczy też katalog społeczności, który jest domyślnie wyłączony ([konfiguracja][m4b-community]), aplikacje bez obrazu Dockera i aplikacje porzucone.
- **IGM.** Wpisy w `apps.json`: 20, wszystkie włączone. Kontener proxy, Watchtower i kontenery pomocnicze do odbierania nagród nie są liczone.
- **InternetIncome.** Każdy blok komentarza `# Starting ... container` w `internetIncome.sh`, poza blokami proxy i Watchtower: 24. Bloki Chrome i Firefox Ebesuchera to jedna aplikacja, podobnie EarnFM i EarnFM Fleetshare, które używają tego samego konta EarnFM. Blok rozszerzeń Depin uruchamia Grass i Gradient ([skrypt][ii-depin]), czyli dwie aplikacje. Łącznie 23. Tabela w README wymienia 27 aplikacji, niektóre tylko z linkiem do rejestracji.
- **CashFactory.** Usługi zarobkowe w `docker-compose.yml`: 11. Portainer, serwer WWW i dwa Watchtowery nie są liczone. Jedna usługa jest zakomentowana.
- **Dodatki HA.** Foldery dodatków z plikiem konfiguracyjnym: 10.

Nie sprawdzaliśmy, czy każda aplikacja z każdej listy nadal wypłaca.

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
