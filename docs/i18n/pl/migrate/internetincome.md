---
source_hash: ca9dd25d45ca
---
# Przejście z InternetIncome { #moving-from-internetincome }

CashPilot potrafi odczytać `properties.conf` InternetIncome oraz pliki, w których
trzyma on identyfikatory twoich urządzeń EarnApp i ProxyRack, i je przenieść. Wszystko
sprawdzasz, zanim CashPilot to zapisze.

## Zanim zaczniesz { #before-you-start }

Potrzebujesz konta właściciela CashPilot i co najmniej jednego workera CashPilot.

Zatrzymaj InternetIncome na maszynie, zanim wdrożysz tam te same usługi z
CashPilot. Dwie kopie za jednym łączem zarabiają jak jedna, a ten sam identyfikator urządzenia
nie może działać dwa razy. W folderze InternetIncome uruchom:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` usuwa kontenery i zachowuje `earnapp.txt`, `proxyrack.txt` oraz
folder danych Mysterium. `--deleteBackup` usuwa także je
([internetIncome.sh, linie od 61 do 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
i [linia 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
więc najpierw zrób import.

## Których plików użyć { #which-files-to-use }

Z folderu InternetIncome:

- `properties.conf`, twoje ustawienia.
- `earnapp.txt`, jeśli uruchamiałeś EarnApp. Każda linia zawiera link urządzenia
  ([linie od 1250 do 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, jeśli uruchamiałeś ProxyRack. Jeden UUID urządzenia na linię
  ([linie od 817 do 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot bierze pierwsze urządzenie z każdego pliku: to, którego używał twój główny kontener,
i to, które połączyłeś ze swoim kontem. Pozostałe linie należały do kopii przez proxy,
a strona mówi ci, ile z nich pominęła.

InternetIncome przepuszcza każdą wartość przez powłokę
([linia 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Wartość w pojedynczych cudzysłowach jest brana tak, jak jest zapisana, zgodnie z radą komentarzy w
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Wartość poza pojedynczymi cudzysłowami, która zawiera `$`, grawis, spację lub
inny znak, który powłoka by zmieniła, nie jest tym, co pokazuje plik, więc
CashPilot prosi cię o jej ponowne wpisanie, zamiast uruchamiać powłokę, żeby to sprawdzić.

## Jak zaimportować { #how-to-import }

1. Otwórz **Settings** (Ustawienia), potem **Import from another tool** (Import z innego narzędzia) (albo przejdź do `/import`).
2. Dodaj `properties.conf` oraz `earnapp.txt` i `proxyrack.txt`, jeśli je
   masz. Zostaw narzędzie na **Tell from the files** (Rozpoznaj z plików) albo wybierz InternetIncome.
3. Sprawdź tabelę. Zaznacz usługi, które chcesz, i uzupełnij każdą wartość oznaczoną
   jako brakująca. Repocket potrzebuje e-maila twojego konta, o który InternetIncome nigdy nie
   pytał.
4. Naciśnij **Save the ticked services** (Zapisz zaznaczone usługi), a potem wdróż je na swoje workery z
   tej samej strony.

## Co zostaje przeniesione { #what-comes-over }

| Aplikacja InternetIncome | Odczytywane klucze | Usługa CashPilot | Co zostaje przeniesione |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | klucz API (dodaj swój e-mail) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | klucz API, UUID urządzenia |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | e-mail, hasło |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | e-mail, hasło |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | identyfikator użytkownika |
| `earnfm` | `EARN_FM_API` | Earn.fm | klucz API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | identyfikator urządzenia |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | e-mail, hasło |
| `mysterium` | `MYSTERIUM=true` | Mysterium | włączona; zobacz uwagę o Mysterium poniżej |

Pusta wartość oznacza, że aplikacja była wyłączona, i nie jest ona wymieniana.

Te aplikacje są wymienione, ale nie zostają przeniesione:

| Aplikacja InternetIncome | Dlaczego |
|---|---|
| `urnetwork` | InternetIncome używa tokena sesji. CashPilot loguje się do URnetwork twoim e-mailem i hasłem. |
| `grass` | Grass działa jako rozszerzenie przeglądarki. CashPilot tylko go śledzi, za pomocą tokena dostępu z panelu Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot je śledzi, ale nie ma kontenera do wdrożenia. |
| `peer2profit` | Już niedostępna. |

Ustawienia aplikacji, których CashPilot nie ma (antGain, Adnade i inne), są
wymienione z nazwy jako nieodczytane.

## Czego nigdy nie przenosi { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot nazywa każde urządzenie od workera, na którym działa, więc
  dwa workery nigdy nie zgłaszają tej samej nazwy. Twoje stare urządzenia pozostają na liście jako
  offline w panelu każdego dostawcy, dopóki ich tam nie usuniesz.
- **Proxy** (`USE_PROXIES`, `proxies.txt`). Dodaj każde w sekcji **Proxies** (Proxy)
  na stronie **Fleet** (Flota), a potem uruchamiaj przez nie kopie swoich usług; samo dodanie
  proxy niczego nie uruchamia. Przy `USE_PROXIES=true` InternetIncome uruchamiał
  twoje usługi tylko przez proxy. Zapisanie importu też niczego nie uruchamia. Kopia
  przez proxy wymaga, by ta sama usługa była najpierw wdrożona na workerze, a
  jej wdrożenie uruchamia ją na własnym łączu workera, więc usługa, która
  nigdy nie może używać tego łącza, powinna zostać niezaznaczona. Zobacz [Kopie
  przez proxy](../proxies.md).
- **`BROWSER_USERNAME` i `BROWSER_PASSWORD`**, własne dane logowania przeglądarki
  InternetIncome.

## Śledzenie zarobków { #earnings-tracking }

W Honeygain, IPRoyal Pawns i Bitping dane logowania kontenera są zarazem danymi logowania
do konta, więc CashPilot uzupełnia też ich dane do zbierania zarobków, chyba że
już ustawiłeś je w **Settings** (Ustawienia). Dla każdej innej usługi dodaj dane logowania do zbierania zarobków
w **Settings > Earnings collection** (Ustawienia > Zbieranie zarobków).

## Mysterium { #mysterium }

Import włącza Mysterium, ale CashPilot uruchamia nowy węzeł z nową
tożsamością. Magazyn kluczy starego węzła i wszelkie nierozliczone zarobki zostają w
folderze `mysterium-data` InternetIncome. Najpierw je rozlicz albo postępuj zgodnie z
[przewodnikiem po Mysterium](../guides/mysterium.md), aby przenieść tożsamość.

## Bezpieczeństwo { #safety }

- Nic z plików nie jest uruchamiane ani rozwijane i żaden adres z nich nie jest pobierany.
- Pliki są czytane raz i nie są przechowywane. To, co zapiszesz, jest przechowywane w postaci zaszyfrowanej, jak
  wszystkie inne dane logowania w CashPilot.
- Sekrety są pokazywane na stronie tylko jako **set** (ustawione).
- Zapisane importy zostają na stronie importu, dopóki nie naciśniesz **Forget** (Zapomnij), więc możesz
  później wdrożyć je na kolejne workery.
