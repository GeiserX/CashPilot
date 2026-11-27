---
source_hash: b4ae1a3ae496
---
# Czekające pieniądze: przypomnienia, zanim stracisz zarobki { #money-waiting-reminders-before-you-lose-earnings }

Niektórzy dostawcy odbierają pieniądze, które leżą zbyt długo. Saldo może wygasnąć po
miesiącach bez aktywności. Okno na odebranie środków może się zamknąć. Dostawca może zablokować
konto, przestać płacić albo zamknąć działalność, gdy twoje saldo wciąż u niego leży.
CashPilot już odczytuje większość tego, czego potrzebuje, żeby to przewidzieć.
Panel **Money waiting** (Czekające pieniądze) na stronie głównej pokazuje, co zrobić i do kiedy, a
twoje kanały powiadomień dostają push przed każdym terminem.

CashPilot nigdy niczego za ciebie nie odbiera ani nie wypłaca. Każde przypomnienie prowadzi
do własnej strony dostawcy i tam działasz.

## O czym przypomina { #what-it-reminds-you-about }

**Zasady z warunków samego dostawcy.** Każda zasada cytuje warunki dostawcy
lub jego stronę pomocy oraz datę, kiedy ktoś ostatnio ją przeczytał. Otwiera ją link **Source** (Źródło)
w menu **More** (Więcej) danego wiersza.

| Usługa | Przypomnienie | Kiedy |
|---|---|---|
| Grass | Odbierz swoje USDC ze Stage 2 | Do 22 stycznia 2027. Grass zatrzymuje to, czego nie odebrano. |
| MystNodes | Odbierz nagrody z ostatniego miesiąca | W ciągu 30 dni od każdej miesięcznej dystrybucji |
| Honeygain | Wypłać saldo | 24 miesiące po tym, jak pierwszy raz osiągnęło $20 |
| Honeygain | Utrzymuj udostępnianie na urządzeniu albo zrób wypłatę | 6 miesięcy po ostatniej aktywności lub wypłacie |
| Repocket | Utrzymuj udostępnianie na urządzeniu albo wypłać | 12 miesięcy po ostatniej aktywności lub wypłacie |
| Bitping | Wypłać saldo | 12 miesięcy po ostatniej wypłacie |
| Salad | Zdobądź trochę Reward Points albo wydaj saldo | 12 miesięcy po tym, jak saldo ostatnio wzrosło. Wydanie jego części tego nie resetuje. |

**Wypłata.** CashPilot informuje cię, gdy saldo osiągnie minimum dostawcy.
Dotyczy to każdej usługi, z której zbiera dane, poza usługami, które
wypłacają same. Saldo musi być też warte co najmniej $5, żeby dostawca
z minimum 5 centów nie nękał cię od pierwszego centa. Gdy minimum dostawcy
jest wyższe, obowiązuje minimum dostawcy. Gdy CashPilot nie potrafi
przeliczyć minimum lub salda, nic nie pokazuje. Nigdy nie zgaduje, że
możesz wypłacić.

**Wygasanie danych logowania.** Dostajesz push, zanim zapisany token lub ciasteczko wygaśnie.
CashPilot używa daty wygaśnięcia, którą podaje sam token lub ciasteczko. Gdy żadnej
nie podaje, CashPilot przyjmuje typowy czas życia tego rodzaju danych logowania, liczony
od dnia, w którym je zapisałeś. Właściciele widzą to już w **Needs attention** (Wymaga uwagi),
z przyciskiem **Renew** (Odnów), więc panel tego nie powtarza. Przypomnienia o danych logowania
z API dostają tylko właściciele, tak samo jak przy kontroli kondycji danych logowania.
Dane logowania odrzucone przez dostawcę są już w dzwonku i już wysłane jako push,
więc nie są wysyłane ponownie.

## Których usług dotyczy { #which-services-it-covers }

Przypomnienie dotyczy usługi, z której korzystasz: wdrożonej, ustawionej przez ciebie
jako zewnętrzna w **Settings** (Ustawienia) albo aplikacji, którą zgłasza telefon. Usługa, którą usunąłeś,
nadal się liczy, dopóki ma saldo, ponieważ zegary braku aktywności zaczynają biec,
gdy usługa przestaje działać. Własne usługi i wycofane usługi nie dostają przypomnień.

## Daty i „lub wcześniej” { #dates-and-or-earlier }

Zegary aktywności liczą od tego, co zarejestrował CashPilot:

- ostatniego wzrostu salda,
- ostatniej wypłaty,
- albo pierwszego odczytu równego minimum lub wyższego.

Czasem zegar zaczął biec przed pierwszym odczytem CashPilot. Wtedy prawdziwy
termin może być wcześniejszy, niż CashPilot widzi, a wiersz mówi
„do 3 października 2027 lub wcześniej”.

CashPilot usuwa historię zarobków po 400 dniach, a zegar Honeygain
biegnie przez 730 dni. Dlatego CashPilot zapisuje początek każdego zegara, gdy pierwszy raz
go zobaczy, i trzyma go, nawet gdy historia, z której wynika, już zniknie. Wypłata resetuje
zegar, z wyjątkiem dostawców, którzy liczą tylko zarabianie. Salad jest jednym z nich:
wypłata, która zostawia saldo, nie resetuje jego 12 miesięcy.

Stała data znika dzień po tym, jak minie, ponieważ pieniądze już przepadły.
Zaległy zegar zostaje i mówi, że dostawca mógł już spisać te
pieniądze na straty. Zostaje, dopóki nie oznaczysz go jako zrobiony lub go nie wyciszysz, albo dopóki wypłata
go nie zresetuje.

## Co możesz zrobić z przypomnieniem { #what-you-can-do-with-a-reminder }

Właściciele i edytorzy widzą przyciski. Przeglądający widzą tylko przypomnienia. Tylko właściciele
mogą działać na przypomnieniu o danych logowania.

- **Done** (Zrobione) albo, przy wypłacie, **Requested** (Zlecone) ukrywa to przypomnienie. Miesięczne
  okno wraca w następnym miesiącu. Wypłata wraca raz po 14 dniach, jeśli
  saldo nadal tam jest, i pyta, czy wypłata dotarła. To mieści się
  w 60-dniowym oknie na reklamację, które daje większość dostawców.
- **Snooze** (Odłóż) ukrywa je na dzień lub tydzień i wstrzymuje jego pushe. Odłożenie nigdy
  nie trwa dłużej niż do ostatniego ostrzeżenia przed terminem.
- **Not for me** (Nie dla mnie), w menu **More** (Więcej), wycisza jedno przypomnienie albo wszystkie przypomnienia
  danej usługi. Przykład: Honeygain w trybie JumpTask, gdzie stałe saldo
  jest normalne. Wyciszone przypomnienia są wymienione na dole panelu, z
  przyciskiem **Unmute** (Wyłącz wyciszenie).

Te wybory są wspólne dla całego gospodarstwa domowego. Gdy jedna osoba oznaczy przypomnienie jako zrobione,
jest ono zrobione dla wszystkich. Każdy wybór jest zapisywany w dzienniku audytu z imieniem
osoby, która go dokonała.

## Pushe { #pushes }

Przypomnienia trafiają do kanałów ustawionych dla alertów: ntfy, webhooka lub Telegrama
([konfiguracja](configuration.md)). Gdy żaden kanał nie jest ustawiony, panel jest jedynym
miejscem, w którym się pojawiają.

- Jeden push na ostrzeżenie. Na przykład Grass wysyła pushe 60, 30, 7 i 1 dzień przed
  swoją datą. Przypomnienie zobaczone pierwszy raz 5 dni przed datą wysyła jeden push, gdy zostało 5
  dni.
- Pushe wychodzą tylko między 09:00 a 21:00. CashPilot używa strefy czasowej pierwszego właściciela
  z **Settings** (Ustawienia), potem `TZ` kontenera, potem UTC. Ostrzeżenie,
  którego termin przypadł w nocy, wychodzi przy pierwszym sprawdzeniu po 09:00.
- Gdy naraz należy się więcej niż 3 pushe, dostajesz zamiast nich jedno podsumowanie. Dzieje się
  tak w dniu aktualizacji, gdy wszystkie salda powyżej minimum pojawiają się
  jednocześnie.
- Push zawiera usługę, co zrobić, co możesz stracić, datę i
  link dostawcy. Nigdy nie zawiera salda, adresu, identyfikatora urządzenia ani
  nazwy workera. Tematy ntfy mogą być publiczne.
- Treść webhooka zawiera `kind: "obligation"`, więc Home Assistant i podobne
  narzędzia mogą ją odpowiednio kierować.

## Dla współtwórców katalogu { #for-catalog-contributors }

Zasady żyją w pliku YAML każdej usługi, pod `obligations:`.
`services/_schema.yml` dokumentuje pola. Dodawaj zasadę tylko wtedy, gdy
własne warunki lub dokumentacja dostawcy ją podają i gdy CashPilot widzi sygnał, od którego
zależy. Link zasady musi być we własnej domenie usługi, ponieważ fałszywe
strony do odbierania środków istnieją właśnie dla tych usług. CI kończy się błędem przy nieprawidłowej zasadzie
oraz przy zasadzie z datą, która minęła ponad 30 dni temu.
