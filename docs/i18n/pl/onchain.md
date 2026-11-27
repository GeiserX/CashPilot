---
source_hash: d88e40f8d9a6
---
# Salda wypłat on-chain { #on-chain-payout-balances }

Otwórz **Payouts** (Wypłaty), aby zobaczyć saldo publicznego adresu wypłat. Bitcoin korzysta z
[mempool.space](https://mempool.space/docs/api/rest), a Kaspa z
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon i Solana korzystają z
publicznych węzłów RPC. CashPilot może odczytać te adresy bez klucza.

| Co widzisz | Co to oznacza |
|---|---|
| Kwota | Eksplorator zgłosił saldo. Zgłoszone zero pojawia się jako zero. Najedź kursorem na kwotę, aby zobaczyć źródło. |
| **Pending** (Oczekujące) | W Bitcoinie eksplorator widzi niepotwierdzoną zmianę. Plus oznacza, że środki napływają. Minus oznacza, że środki są wydawane. Potwierdzona kwota jest pokazana osobno. |
| **Could not check** (Nie udało się sprawdzić) | Eksplorator nie odpowiedział albo wysłał dane, których CashPilot nie potrafił odczytać. |
| **Address not valid** (Nieprawidłowy adres) | Adres nie przeszedł kontroli formatu. CashPilot pominął zapytanie. |
| **Private chain** (Prywatny łańcuch) | Odczyt salda Monero wymaga twojego prywatnego klucza podglądu (view key). Sprawdź saldo w swoim portfelu. CashPilot nigdy nie prosi cię o ten klucz. |
| Kreska | Dla tego wiersza nie ma adresu ani czytnika albo sprawdzanie jest wyłączone. Gdy wyłącza je jakieś ustawienie, najedź kursorem na kreskę, aby zobaczyć które. |

Publiczny punkt końcowy Kaspy zgłasza jedno saldo. Nie podaje osobnej kwoty
oczekującej.

Kolumna on-chain pokazuje saldo adresu w tej chwili. Może obejmować
przelewy z innych źródeł. Niewypłacone saldo puli pokazuje, co pula
wciąż trzyma dla ciebie. Wypłata OCEAN przez Lightning nie pojawia się w
saldzie on-chain. Saldo nie powie ci też, które przelewy przyszły z
twojej puli.

## Wybierz, dokąd trafia zapytanie { #choose-where-the-lookup-goes }

Każde zapytanie udostępnia eksploratorowi twój publiczny adres wypłat i IP serwera UI.
Eksplorator może powiązać adresy, które sprawdzasz z tego samego IP.

Jeśli prowadzisz własny węzeł, ustaw bazowy URL w środowisku kontenera UI.
Zostaw zmienną nieustawioną, aby użyć domyślnego. Ustaw ją na pustą wartość, aby wyłączyć
sprawdzanie dla tego łańcucha.

Na przykład nadpisanie Compose dla usługi UI mogłoby zawierać:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Przy konfiguracji Bitcoina lub Kaspy użyj bazowego URL-a API Esplora lub Kaspa.
Punkt końcowy Bitcoina podaje też trudność sieci i nagrody za blok potrzebne do
[oczekiwanych zarobków](fleet.md#running-costs) puli bitcoinowej. Ten odczyt wymaga
backendu mempool (jego API `/v1/mining`); zwykły serwer Esplora odpowiada tylko na
zapytanie o saldo, a wiersz puli nie pokazuje wtedy oczekiwanej kwoty.
Dla Ethereum, Polygon i Solany ustaw odpowiednie zmienne
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` lub
`CASHPILOT_ONCHAIN_URL_SOLANA` na URL RPC węzła. Użyj URL-a HTTP lub HTTPS
bez danych logowania, parametrów zapytania i fragmentu. Zastosuj zmianę,
tworząc kontener UI od nowa z nowym środowiskiem.
