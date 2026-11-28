---
source_hash: 5a764f1d0f5a
---
# Przejście z money4band { #moving-from-money4band }

CashPilot potrafi odczytać konfigurację money4band i przenieść twoje dane logowania do usług,
więc nie musisz ich wpisywać ponownie. Wszystko sprawdzasz, zanim CashPilot to zapisze.

## Zanim zaczniesz { #before-you-start }

Potrzebujesz konta właściciela CashPilot i co najmniej jednego workera CashPilot na
maszynie, na której teraz działa money4band, albo na innej maszynie.

Zatrzymaj money4band na maszynie, zanim wdrożysz tam te same usługi z
CashPilot. Dwie kopie za jednym łączem zarabiają jak jedna, a ten sam identyfikator urządzenia EarnApp
lub ProxyRack nie może działać dwa razy. Użyj **Stop apps stack** w
menu money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
albo uruchom `docker compose down` w jego folderze. Jeśli skonfigurowałeś dodatkowe instancje
proxy, zatrzymaj też każdą z nich.

## Którego pliku użyć { #which-file-to-use }

Użyj `config/user-config.json` w swoim folderze money4band. To, jak przekażesz go do
CashPilot, zależy od twojej wersji money4band.

W money4band 4.x money4band zapisuje ten plik, gdy uruchamiasz **Setup Apps**, i zawiera
on dokładnie to, co wpisałeś. Plik `.env` obok niego jest generowany z tego pliku i również
działa, podobnie jak ręcznie edytowany `.env` z money4band 3.x. Oba zostają tylko na twoim
dysku:
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
money4band je wymienia.

money4band 5.0 szyfruje `config/user-config.json` na dysku
([uwagi o bezpieczeństwie](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption))
i usuwa swój `.env` po każdym uruchomieniu
([generator env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot nie potrafi odczytać zaszyfrowanego pliku. W swoim folderze money4band uruchom
jego polecenie `config edit`. Dla pliku binarnego z wydania użyj pliku dla swojego systemu, na przykład `./Money4Band-linux-amd64 config edit`, albo `.\Money4Band-windows-amd64.exe config edit` w systemie Windows.
Przy uruchamianiu ze źródeł uruchom `python run.py config edit`.
Uruchamia ono money4band przez uv, a gdy uv nie ma, przez środowisko pip ([run.py](https://github.com/MRColorR/money4band/blob/eebbdd410131e4b0fd4c9f9d49f84dc60e6a0e3d/run.py#L48-L69)).
Polecenie otwiera odszyfrowany plik w twoim edytorze ([dokumentacja CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Skopiuj cały jego tekst, wklej go na stronie **Import from another tool** (Import z innego narzędzia), a potem zamknij edytor.

Wybieraj plik JSON. W `.env` Docker Compose rozwija `$` w wartościach bez cudzysłowów,
więc hasło zawierające `$` nie jest tym, co pokazuje plik. CashPilot nie
zgaduje: prosi cię o ponowne wpisanie tej wartości.

## Jak zaimportować { #how-to-import }

1. Otwórz **Settings** (Ustawienia), potem **Import from another tool** (Import z innego narzędzia) (albo przejdź do `/import`).
2. Dodaj `user-config.json` albo wklej jego tekst. Zostaw narzędzie na **Tell from the
   files** (Rozpoznaj z plików) albo wybierz money4band.
3. Sprawdź tabelę. Zaznacz usługi, które chcesz, i uzupełnij każdą wartość oznaczoną
   jako brakująca.
4. Naciśnij **Save the ticked services** (Zapisz zaznaczone usługi), a potem wdróż je na swoje workery z
   tej samej strony.

## Co zostaje przeniesione { #what-comes-over }

Nazwy pól pochodzą z
[szablonu user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
money4band oraz z nazw w `.env`, które zapisuje jego
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, na przykład `REPOCKET_APIKEY`). money4band 5.0 zachowuje te same nazwy
pól w swoim
[katalogu aplikacji](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| Aplikacja money4band | Usługa CashPilot | Co zostaje przeniesione |
|---|---|---|
| `earnapp` | EarnApp | identyfikator urządzenia (`uuid`), więc twoje połączone urządzenie dalej zarabia |
| `honeygain` | Honeygain | e-mail, hasło |
| `iproyalpawns` | IPRoyal Pawns | e-mail, hasło |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | e-mail, klucz API |
| `earnfm` | Earn.fm | klucz API |
| `proxyrack` | ProxyRack | klucz API, UUID urządzenia |
| `proxylite` | ProxyLite | identyfikator użytkownika |
| `bitping` | Bitping | e-mail, hasło |
| `mystnode` | Mysterium | włączona; zobacz uwagę o Mysterium poniżej |

Aplikacja wyłączona w money4band pojawia się bez zaznaczenia. Aplikacja, która jest wyłączona i
zawiera tylko symbole zastępcze z szablonu (`yourHONEYGAINMail`) i listy portów,
jest pomijana, więc nietknięty `user-config.json` daje pustą tabelę.

Te aplikacje są wymienione, ale nie zostają przeniesione:

| Aplikacja money4band | Dlaczego |
|---|---|
| `proxybase` | money4band uruchamia starego klienta ProxyBase z identyfikatorem użytkownika. CashPilot uruchamia aktualnego, który potrzebuje Access Token z proxybase.org. |
| `urnetwork` | money4band trzyma token sesji. CashPilot loguje się do URnetwork twoim e-mailem i hasłem. |
| `grass` | Grass działa jako rozszerzenie przeglądarki. CashPilot tylko go śledzi, za pomocą tokena dostępu z panelu Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot je śledzi, ale nie ma kontenera do wdrożenia. |
| `packetshare`, `peer2profit`, `speedshare` | Już niedostępne. |

Każda inna aplikacja jest wymieniona jako **CashPilot has no such service** (CashPilot nie ma takiej usługi).

## Czego nigdy nie przenosi { #what-never-comes-over }

- **Nazwy urządzenia.** CashPilot nazywa każde urządzenie od workera, na którym działa, więc
  dwa workery nigdy nie zgłaszają tej samej nazwy. Twoje stare urządzenia pozostają na liście jako
  offline w panelu każdego dostawcy, dopóki ich tam nie usuniesz.
- **Proxy.** Dodaj każde w sekcji **Proxies** (Proxy) na stronie **Fleet** (Flota), a potem uruchamiaj
  przez nie kopie swoich usług; samo dodanie proxy niczego nie uruchamia.
  Zapisanie importu też niczego nie uruchamia. Kopia przez proxy wymaga, by ta sama usługa
  była najpierw wdrożona na workerze, a jej wdrożenie uruchamia ją na własnym
  łączu workera, więc usługa, która nigdy nie może używać tego łącza, powinna zostać
  niezaznaczona. Zobacz [Kopie przez proxy](../proxies.md).
- **Watchtowera i powiadomień.** CashPilot sam aktualizuje swoje kontenery.
- **Panelu money4band i jego portów.**

## Śledzenie zarobków { #earnings-tracking }

W Honeygain, IPRoyal Pawns i Bitping dane logowania kontenera są zarazem danymi logowania
do konta, więc CashPilot uzupełnia też ich dane do zbierania zarobków, chyba że
już ustawiłeś je w **Settings** (Ustawienia). Dla każdej innej usługi dodaj dane logowania do zbierania zarobków
w **Settings > Earnings collection** (Ustawienia > Zbieranie zarobków).

## Mysterium { #mysterium }

Import włącza Mysterium, ale CashPilot uruchamia nowy węzeł z nową
tożsamością. Magazyn kluczy starego węzła i wszelkie nierozliczone zarobki zostają w
folderze `.data/mysterium-node` money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Najpierw je rozlicz albo postępuj zgodnie z
[przewodnikiem po Mysterium](../guides/mysterium.md), aby przenieść tożsamość.

Plik `.env` z wersji 3.x nie mówi, czy uruchamiałeś Mysterium: jego szablon zawsze
wymienia port panelu. Z pliku 3.x Mysterium nie jest importowane, więc dodaj
je z katalogu, jeśli je uruchamiałeś.

## Bezpieczeństwo { #safety }

- Nic z pliku nie jest uruchamiane ani rozwijane i żaden adres z niego nie jest pobierany.
- Plik jest czytany raz i nie jest przechowywany. To, co zapiszesz, jest przechowywane w postaci zaszyfrowanej, jak
  wszystkie inne dane logowania w CashPilot.
- Sekrety są pokazywane na stronie tylko jako **set** (ustawione).
- Zapisane importy zostają na stronie importu, dopóki nie naciśniesz **Forget** (Zapomnij), więc możesz
  później wdrożyć je na kolejne workery.
