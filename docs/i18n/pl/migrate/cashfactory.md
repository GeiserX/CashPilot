---
source_hash: 7f8476aeb8b6
---
# Przejście z CashFactory { #moving-from-cashfactory }

CashPilot potrafi odczytać plik `.env` CashFactory i przenieść twoje dane logowania do usług,
więc nie musisz ich wpisywać ponownie. Wszystko sprawdzasz, zanim CashPilot to zapisze.

## Zanim zaczniesz { #before-you-start }

Potrzebujesz konta właściciela CashPilot i co najmniej jednego workera CashPilot.

Zatrzymaj CashFactory na maszynie, zanim wdrożysz tam te same usługi z
CashPilot. Dwie kopie za jednym łączem zarabiają jak jedna, a ten sam identyfikator
urządzenia EarnApp nie może działać dwa razy. Uruchom `docker compose down` w folderze
CashFactory. Jego
[plik compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
uruchamia też trzy kontenery, które montują gniazdo Dockera: Portainer (linia 31)
i dwa kontenery Watchtower (linie 141 i 264). Upewnij się, że ich też już nie ma: `docker ps` nie powinien
wymieniać żadnego z nich.

## Którego pliku użyć { #which-file-to-use }

Użyj pliku `.env` w swoim folderze CashFactory, tego, który wypełniłeś na podstawie
[przykładu](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose czyta ten plik i rozwija `$` w wartościach, które nie są w
pojedynczych cudzysłowach. Taka wartość nie jest tym, co pokazuje plik, więc CashPilot prosi
cię o jej ponowne wpisanie, zamiast zgadywać.

## Jak zaimportować { #how-to-import }

1. Otwórz **Settings** (Ustawienia), potem **Import from another tool** (Import z innego narzędzia) (albo przejdź do `/import`).
2. Dodaj plik `.env` albo wklej jego tekst. Zostaw narzędzie na **Tell from the
   files** (Rozpoznaj z plików) albo wybierz CashFactory.
3. Sprawdź tabelę. Zaznacz usługi, które chcesz, i uzupełnij każdą wartość oznaczoną
   jako brakująca.
4. Naciśnij **Save the ticked services** (Zapisz zaznaczone usługi), a potem wdróż je na swoje workery z
   tej samej strony.

## Co zostaje przeniesione { #what-comes-over }

| Aplikacja CashFactory | Odczytywane klucze | Usługa CashPilot | Co zostaje przeniesione |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | identyfikator urządzenia, więc twoje połączone urządzenie dalej zarabia |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | e-mail, hasło |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | e-mail, hasło |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | e-mail, klucz API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | identyfikator użytkownika |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID urządzenia |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | klucz API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | nic: już niedostępna |

Wartość, która nadal pokazuje symbol zastępczy z przykładu (`<email>`, `sdk-node-<md5sum>`),
liczy się jako nieustawiona, a usługa, która ma tylko symbole zastępcze, jest pomijana w
tabeli.

## Czego nigdy nie przenosi { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot nazywa każde urządzenie od workera, na którym działa, więc
  dwa workery nigdy nie zgłaszają tej samej nazwy. Twoje stare urządzenia pozostają na liście jako
  offline w panelu każdego dostawcy, dopóki ich tam nie usuniesz.
- **Bitping.** CashFactory trzyma dane logowania Bitping w wolumenie Dockera, a nie w
  `.env`, więc import nie ma czego odczytać i nie pokazuje wiersza Bitping. Wpisz
  dane logowania w formularzu wdrożenia Bitping.
- **Portainer i Watchtower.** CashPilot sam zarządza swoimi kontenerami i je
  aktualizuje.

## Śledzenie zarobków { #earnings-tracking }

W Honeygain i IPRoyal Pawns dane logowania kontenera są zarazem danymi logowania do konta,
więc CashPilot uzupełnia też ich dane do zbierania zarobków, chyba że już ustawiłeś
je w **Settings** (Ustawienia). Dla każdej innej usługi dodaj dane logowania do zbierania zarobków w
**Settings > Earnings collection** (Ustawienia > Zbieranie zarobków).

## Bezpieczeństwo { #safety }

- Nic z pliku nie jest uruchamiane ani rozwijane i żaden adres z niego nie jest pobierany.
- Plik jest czytany raz i nie jest przechowywany. To, co zapiszesz, jest przechowywane w postaci zaszyfrowanej, jak
  wszystkie inne dane logowania w CashPilot.
- Sekrety są pokazywane na stronie tylko jako **set** (ustawione).
- Zapisane importy zostają na stronie importu, dopóki nie naciśniesz **Forget** (Zapomnij), więc możesz
  później wdrożyć je na kolejne workery.
