---
source_hash: 915470497dbc
---
# FAQ { #faq }

**Czy udostępnianie przepustowości jest bezpieczne?**

Usługi udostępniania przepustowości zwykle przesyłają przez twoje łącze legalny ruch (badania rynku, weryfikację reklam, porównywanie cen, dostarczanie treści). Mimo to udostępniasz swój adres IP, więc przed rejestracją uważnie przeczytaj regulamin i politykę prywatności każdej usługi. W przypadku niektórych usług można je uruchamiać na VPS zamiast na IP domowym. **To nie jest porada prawna -- skontaktuj się z usługami, z których zamierzasz korzystać, a w razie potrzeby zasięgnij niezależnej porady prawnej dotyczącej twojej jurysdykcji.**

**Ile mogę zarobić?**

Zarobki bardzo się różnią w zależności od lokalizacji, dostawcy internetu, liczby urządzeń i uruchomionych usług. Panel śledzi twoje rzeczywiste zarobki w czasie, więc możesz optymalizować konfigurację. Orientacyjnie, i bez żadnej obietnicy: jeden serwer domowy z 10 do 15 usługami zarabia około $30 do $100 miesięcznie, a może zarabiać mniej, aż do zera. Więcej serwerów albo moc obliczeniowa GPU to zwiększają.

**Czy mogę uruchomić to na VPS albo serwerze w chmurze?**

Niektóre usługi wymagają IP domowego i nie płacą za IP z VPS/centrum danych (albo je blokują). Katalog podaje „residential IP” wśród ich wymagań. Usługi, które działają na VPS, to dobry sposób na skalowanie bez dodatkowego sprzętu w domu.

**Jak przechowywane są dane logowania?**

Wszystkie dane logowania do usług są szyfrowane w spoczynku w bazie SQLite kluczem Fernet zapisanym w `/data/.fernet_key`, który jest generowany automatycznie przy pierwszym uruchomieniu. Plik bazy danych leży w zamontowanym wolumenie Dockera (`cashpilot_data:/data`). Dane logowania nigdy nie są nigdzie wysyłane, poza samymi kontenerami usług.

Zwróć uwagę, że to inny klucz niż `CASHPILOT_SECRET_KEY`, który tylko podpisuje sesje logowania.

### Kopia zapasowa klucza szyfrowania { #backing-up-the-encryption-key }

Twoje dane logowania da się odzyskać tylko wtedy, gdy masz `/data/.fernet_key`. Jeśli stracisz ten plik, będziesz musiał wpisać ponownie wszystkie dane logowania, bo bez niego nie da się odszyfrować zapisanych wartości.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Plik zawsze ma pierwszeństwo przed zmienną środowiskową, więc ustawienie `CASHPILOT_ENCRYPTION_KEY` na instancji, która ma już klucz, niczego nie zmienia i jest bezpieczne. Zmienna jest przyjmowana tylko wtedy, gdy nie ma pliku klucza, czyli dokładnie przy przywracaniu.

Jeśli CashPilot w ogóle nie może zapisać klucza na dysku, bo `/data` nie jest zapisywalny albo nie jest zamontowany, odmawia startu, zamiast szyfrować twoje dane logowania kluczem, który zniknie przy następnym restarcie. Ustaw `CASHPILOT_ALLOW_EPHEMERAL_KEY=true`, jeśli naprawdę tego chcesz.

<a id="forgot-password"></a>

### Zapomniane hasło lub nazwa użytkownika { #forgot-password-or-username }

CashPilot nie ma resetu przez e-mail. Hasło resetuje osoba, która prowadzi serwer, z konsoli kontenera CashPilot UI. Nie dotyczy to twoich usług, zarobków ani zapisanych danych logowania: są zaszyfrowane kluczem `/data/.fernet_key`, a nie twoim hasłem.

Polecenie `python -m app.users` wymaga CashPilot 2.3 lub nowszego. W wersji 2.2 i starszych kończy się błędem `No module named app.users`. Najpierw zaktualizuj: w Docker Compose zmień tagi `drumsergio/cashpilot` i `drumsergio/cashpilot-worker` na `2.3` lub nowszy (przypięcie takie jak `2.2` lub `2.2.9` zostaje na tym wydaniu), potem uruchom `docker compose up -d` ([Aktualizacja CashPilot](getting-started.md#updating-cashpilot)). W Unraid zaktualizuj kontener.

1. Wylistuj konta. Pokaże to też zapomnianą nazwę użytkownika. W nazwach użytkowników wielkość liter ma znaczenie.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Ustaw dla konta nowe losowe hasło. Zastąp `alice` nazwą użytkownika z kroku 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Gdy jest dokładnie jeden właściciel, możesz pominąć nazwę użytkownika, a polecenie zresetuje hasło tego właściciela. Jeśli nazwa użytkownika zaczyna się od `-`, poprzedź ją `--`: `reset-password -- -alice`.

    Polecenie wypisuje nowe hasło jeden raz.

3. Jeśli ktoś inny mógł mieć dostęp do konta, zrestartuj teraz kontener UI (`docker restart cashpilot-ui`). Przeglądarki, które nadal były zalogowane jako ten użytkownik, zostaną wylogowane dopiero po restarcie. Jeśli tylko zapomniałeś hasła, restart jest opcjonalny.
4. Zaloguj się nowym hasłem, a potem zmień je z menu awatara (prawy górny róg), **Change password** (Zmień hasło).

Nazwa kontenera zależy od sposobu instalacji CashPilot:

| Instalacja | Kontener UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | nazwa wygenerowana; pokazuje ją `docker ps` |

Portainer, Unraid i CasaOS mają też przycisk konsoli kontenera. Polecenie nie potrzebuje danych wpisywanych w terminalu, więc działa również tam.

Aby zmienić nazwę użytkownika:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Nowa nazwa podlega tej samej zasadzie co przy rejestracji: od 3 do 32 liter, cyfr, `_` lub `-`. Wyloguj się i zaloguj ponownie, aby ją zobaczyć.

**Po podejrzeniu włamania**, na przykład po utracie kopii zapasowej zawierającej `/data/.secret_key`, sam reset hasła nie wystarczy. Kto ma ten klucz, może podpisać ważne ciasteczko logowania, a reset tego nie powstrzyma. Wymień klucz, potem zrestartuj kontener UI. `&&` restartuje go tylko wtedy, gdy nowy klucz jest już na miejscu; jeśli polecenie wypisze błąd, najpierw go napraw:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Po restarcie każda przeglądarka zostaje wylogowana i wszyscy logują się ponownie swoim hasłem. Nie dotyczy to zapisanych danych logowania. Jeśli sam ustawiłeś `CASHPILOT_SECRET_KEY`, polecenie odmówi: zamiast tego wpisz do tej zmiennej nową losową wartość i utwórz kontener od nowa. `docker run` z obrazu nie widzi tej zmiennej i nie może odmówić, więc użyj `docker exec` na kontenerze UI.

Nowy klucz unieważnia podrobione ciasteczka, ale nie cofa tego, co atakujący zrobił, gdy miał dostęp. Są jeszcze dwa kroki:

1. Uruchom `docker exec cashpilot-ui python -m app.users list`. Usuń z panelu każde konto, którego nie rozpoznajesz.
2. Jeśli utracona kopia zawierała cały `/data`, zmień hasła do swoich kont u dostawców. `.fernet_key` i `cashpilot.db` razem odszyfrowują wszystkie zapisane dane logowania.

Jeśli później przywrócisz kopię zapasową wykonaną przed wymianą klucza, pomiń jej `.secret_key` ([Kopia zapasowa i przywracanie](backup-restore.md#restore)) albo ponownie wymień klucz i zrestartuj. W przeciwnym razie stary klucz wróci. Przywrócona baza danych przywraca też konta i hasła, które zawierała, więc powtórz sprawdzenie kont i ewentualny reset haseł.

**Jeśli kontener UI nie startuje**, uruchom polecenie z tego samego obrazu na tych samych danych. Najpierw znajdź folder hosta, w którym leży `/data` UI. Działa to dla zatrzymanego kontenera, a także dla nazwanego wolumenu i dla montowania katalogu (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Potem zamontuj ten folder i użyj tagu obrazu, którego używasz:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Sprawdź, czy lista pokazuje twoje konta, a potem uruchom tę samą linię z `reset-password alice` zamiast `list`.

Ścieżka bez bazy danych daje błąd „no database”, a polecenie niczego tam nie tworzy ani nie zmienia. Docker może jednak zostawić pusty folder lub wolumen o tej nazwie; usuń go.

**Nie** usuwaj wolumenu danych: to kasuje `/data/.fernet_key`, a razem z nim wszystkie zapisane dane logowania. **Nie** usuwaj też wierszy z tabeli `users`.

**Jak całkowicie usunąć CashPilot?**

`docker compose down -v` usuwa tylko własne kontenery CashPilot. Usługi, które wdrożył, dalej działają, a ich dane, sieć za barierą i tabela zapory zostają. [Całkowite usuwanie CashPilot](uninstall.md) usuwa to wszystko, mówi, co przepada na zawsze, i pokazuje, jak sprawdzić, że nic nie zostało.

**A co z bezpieczeństwem?**

Każda usługa wdrożona przez CashPilot działa we własnym kontenerze z odebranymi wszystkimi uprawnieniami (capabilities) Linuksa (kilka usług przywraca tylko te, które deklaruje) i z ustawionym `--security-opt no-new-privileges`, więc proces wewnątrz nie może zdobyć uprawnień. Kontenery nie widzą systemu plików hosta poza wolumenami, które deklaruje usługa. W nowej instalacji worker dodatkowo odgradza je barierą od twojego LAN-u, hosta, tailnetu i metadanych chmury, więc docierają do internetu i do niczego lokalnego ([Izolacja sieci](isolation.md)). W Podmanie bariera nie jest dostępna: aplikacje zarobkowe działają w domyślnej sieci Podmana, która ma dostęp do twojego LAN-u, i strona **Fleet** (Flota) to mówi ([Izolacja sieci](isolation.md) wymienia możliwości). Instalacja zaktualizowana z wydania sprzed 1.70 trzyma swoje aplikacje zarobkowe na domyślnym bridge'u Dockera, który ma dostęp do twojego LAN-u, dopóki nie klikniesz **Turn on isolation** (Włącz izolację) na stronie **Fleet** (Flota). Od 2.0.7 Mysterium także działa za barierą; węzeł wdrożony w wersji do 2.0.6 włącznie zostaje w sieci hosta, dopóki nie wdrożysz go ponownie ([Przenoszenie węzła Mysterium za barierę](mysterium-fence.md)). [Ochrona sieci domowej](home-network-security.md) opisuje, jak zamiast tego objąć zaporą własny bridge. Dane logowania do usług są szyfrowane w spoczynku symetrycznym szyfrowaniem Fernet. UI nie ma dostępu do Dockera. Z dostarczanymi plikami compose worker nigdy nie dostaje surowego gniazda Dockera: łączy się z Dockerem przez `cashpilot-socket-proxy`, który odrzuca kontenery uprzywilejowane i montowanie `/` lub gniazda (chyba że wpiszesz jedno z nich albo folder nad gniazdem w `CASHPILOT_PROXY_BIND_MOUNTS` lub `CASHPILOT_COMPOSE_DIR`: proxy przyjmuje je bez dyskusji) i ogranicza workera do kontenerów, wolumenów i sieci z jego etykietą właściciela ([domyślne ustawienia bezpieczeństwa](security-defaults.md)). Szablony Unraid i aplikacja TrueNAS nadal montują w workerze surowe gniazdo, co oznacza uprawnienia roota na hoście ([sklepy z aplikacjami](app-stores.md)).

Mimo to żadna konfiguracja nie jest niezawodna. Nadal uruchamiasz oprogramowanie firm trzecich, które przesyła zewnętrzny ruch przez twoją sieć. Izolacja Dockera znacząco zmniejsza powierzchnię ataku w porównaniu z uruchamianiem tych usług bezpośrednio na hoście, ale nie usuwa całego ryzyka. Zalecamy uruchamianie CashPilot na dedykowanej maszynie lub w osobnym VLAN-ie, aktualizowanie Dockera i systemu hosta oraz przejrzenie otwartego kodu każdej usługi przed jej wdrożeniem.

**Co się dzieje, gdy kontener usługi ulegnie awarii?**

CashPilot stale monitoruje kondycję kontenerów. Jeśli kontener usługi nieoczekiwanie się zakończy, jest automatycznie restartowany. Panel pokazuje czas działania i stan kondycji każdej uruchomionej usługi.

**Mój węzeł Mysterium nie startuje po ponownym wdrożeniu. Dlaczego?**

Najczęstsza przyczyna to port z jego zakresu UDP, który zajmuje już inny program na hoście. Docker musi zarezerwować każdy port z zakresu, więc jeden zajęty port blokuje start. [Wybór zakresu portów UDP](mysterium-fence.md#choosing-the-udp-port-range) wyjaśnia, jak wybrać zakres, który pozostanie wolny.

**Moja kopia przez proxy działa, ale nic nie zarabia. Dlaczego?**

Proxy może odmawiać połączeń z serwerami tej aplikacji zarobkowej albo przepuszczać tylko porty 80 i 443. **Test** (Test) w CashPilot sprawdza tylko, czy proxy łączy się z internetem. [Sprawdź serwery aplikacji zarobkowej przez proxy](proxies.md#probe-an-earners-servers-through-the-proxy) pokazuje, jak sprawdzić własny host i port aplikacji zarobkowej.

**Które usługi są ciężkie i gdzie powinny działać?**

Najwięcej zużywają węzły przestrzeni dyskowej, przekaźniki i wyjścia VPN oraz praca na GPU. [Planowanie zasobów małej maszyny](fleet.md#budgeting-a-small-box) wymienia je i pokazuje, jak zmierzyć każdy kontener, zanim podejmiesz decyzję.

<a id="worker-lost-docker"></a>

### Worker stracił Dockera po aktualizacji Dockera { #the-worker-lost-docker-after-a-docker-update }

**Co widzisz.** Worker pozostaje online na stronie **Fleet** (Flota), ale CashPilot nie może uruchamiać, zatrzymywać ani aktualizować jego kontenerów. Strona **Fleet** (Flota) pokazuje przy workerze **Docker unreachable** (Docker nieosiągalny). Po 10 minutach kontrola kondycji workera zawodzi (`docker ps` pokazuje workera jako `unhealthy`). Po 30 minutach dzwonek i twoje powiadomienia mówią, że worker nie może połączyć się z Dockerem. `docker logs cashpilot-socket-proxy` pokazuje `upstream Docker socket unreachable`, a przy aktualnym pliku compose `docker ps` pokazuje proxy jako `unhealthy` w ciągu około 3 minut. Twoje aplikacje zarobkowe dalej działają.

**Przyczyna.** Dostarczane pliki compose montują plik gniazda `/var/run/docker.sock` w `cashpilot-socket-proxy`. Montowanie pliku trzyma ten jeden plik. Aktualizacja Dockera (na przykład `unattended-upgrades` instalujące nowy `docker-ce`) restartuje Dockera, a Docker tworzy nowy plik gniazda pod tą samą ścieżką. Przy włączonym live-restore Dockera proxy działa dalej przez ten restart i trzyma stary plik. Na starym pliku nic nie odpowiada.

**Szybka naprawa.** Na tej maszynie zrestartuj proxy:

```bash
docker restart cashpilot-socket-proxy
```

Restart montuje nowe gniazdo, a worker znajduje Dockera ponownie przy następnym sygnale życia. Nie musisz restartować workera. W Unraid i TrueNAS worker sam trzyma gniazdo, więc zrestartuj workera.

**Trwała naprawa.** Montuj folder gniazda, a nie plik gniazda. Zamontowany folder od razu pokazuje wymienione gniazdo. W usłudze `cashpilot-socket-proxy` swojego pliku compose zastąp linię `- /var/run/docker.sock:/var/run/docker.sock:ro` poniższym montowaniem i dodaj linię `SOCKGUARD_UPSTREAM_SOCKET` do jej `environment`:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Potem uruchom `docker compose up -d`. Ta sama zmiana działa w `docker-compose.worker.yml` i `docker-compose.fleet.yml`. Compose czyta te pliki tylko wtedy, gdy je wskażesz, więc uruchom `docker compose -f docker-compose.worker.yml up -d` lub `docker compose -f docker-compose.fleet.yml up -d`, chyba że `COMPOSE_FILE` już wskazuje ten plik.

- `recursive: disabled` jest konieczne. `/var/run` zawiera inne punkty montowania, na przykład przestrzenie nazw sieci Dockera w `/run/docker/netns` i `/run/user/...`. Rekurencyjne montowanie wnosi je wszystkie do proxy. Montowanie nierekurencyjne pokazuje tylko sam folder.
- `SOCKGUARD_UPSTREAM_SOCKET` kieruje proxy na nową ścieżkę. Blok polityki i jego odcisk zostają bez zmian, ponieważ zmienna środowiskowa nadpisuje `upstream.socket` w polityce. Bez tej zmiennej proxy nie startuje (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` może zachować montowanie pliku. Uruchamia się ponownie przy każdym `docker compose up`, więc zawsze dostaje aktualne gniazdo. Jeśli dasz mu to samo montowanie folderu, dodaj `DOCKER_HOST=unix:///host-run/docker.sock` do jego `environment`. Worker 2.8.4 i nowsze czytają tę zmienną. Nigdy nie kieruj go na gniazdo proxy: migrator potrzebuje własnego gniazda hosta.
- Montowanie folderu daje proxy każde gniazdo w `/var/run`, nie tylko gniazdo Dockera. Na typowym serwerze obejmuje to własne gniazdo systemd, D-Bus i gniazda narzędzi takich jak Tailscale czy snapd. `read_only` nie powstrzymuje programu przed połączeniem się z gniazdem, a proxy działa jako root. Dostęp do gniazda Dockera i tak daje uprawnienia roota na hoście, więc przejęte proxy zyskuje niewiele ponad to, co już miało. Jeśli chcesz, żeby proxy trzymało tylko gniazdo Dockera, zachowaj montowanie pliku i restartuj proxy po aktualizacji Dockera: powyższy alert powie ci, kiedy.
- Wymaga to Docker Compose 2.30.0 lub nowszego. Starsze wydania odrzucają cały plik z komunikatem `Additional property recursive is not allowed`. Sprawdź to poleceniem `docker compose version`. Debian 13 ma w pakietach Compose 2.26.1, więc w Debianie zainstaluj Compose z własnego repozytorium Dockera. Aktualizacja z poziomu aplikacji używa własnego Compose 2.33, więc odczyta zmieniony plik.
- Działa to tylko w Linuksie. Docker Desktop na macOS i Windows mapuje do swojej maszyny wirtualnej tylko `/var/run/docker.sock`. Tam `/var/run` to folder na twoim Macu lub PC, bez gniazda Dockera.
- W Dockerze bez roota (rootless) gniazdo jest w `/run/user/<your uid>`, które jest osobnym punktem montowania. Użyj tego folderu jako `source`.
- W Podmanie zachowaj montowanie pliku. Nie testowaliśmy tam montowania folderu.

Dostarczane pliki zachowują montowanie pliku, ponieważ montowanie folderu wymaga Compose 2.30 i Linuksa, a CashPilot obsługuje też starsze wydania Compose i Docker Desktop. Nowszy plik compose, który pobierzesz, nie zawiera twojej zmiany, więc wprowadź ją ponownie po wymianie pliku.
