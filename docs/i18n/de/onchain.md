---
source_hash: d88e40f8d9a6
---
# On-Chain-Guthaben von Auszahlungsadressen { #on-chain-payout-balances }

Öffne **Payouts** (Auszahlungen), um das Guthaben einer öffentlichen Auszahlungsadresse zu sehen. Bitcoin verwendet
[mempool.space](https://mempool.space/docs/api/rest) und Kaspa verwendet
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon und Solana verwenden
öffentliche RPC-Nodes. CashPilot kann diese Adressen ohne Schlüssel lesen.

| Was du siehst | Was es bedeutet |
|---|---|
| Ein Betrag | Der Explorer hat ein Guthaben gemeldet. Ein gemeldetes Null erscheint als Null. Fahre mit der Maus über den Betrag, um die Quelle zu sehen. |
| Pending (Ausstehend) | Bei Bitcoin sieht der Explorer eine unbestätigte Änderung. Ein Plus bedeutet eingehende Mittel. Ein Minus bedeutet, dass Mittel ausgegeben werden. Der bestätigte Betrag wird separat angezeigt. |
| Could not check (Prüfung nicht möglich) | Der Explorer hat nicht geantwortet oder Daten geschickt, die CashPilot nicht lesen konnte. |
| Address not valid (Adresse ungültig) | Die Adresse hat eine Formatprüfung nicht bestanden. CashPilot hat die Anfrage übersprungen. |
| Private chain (Private Chain) | Um ein Monero-Guthaben zu lesen, braucht es deinen privaten View-Key. Prüfe das Guthaben in deiner Wallet. CashPilot fragt dich nie nach diesem Schlüssel. |
| Ein Strich | Für diese Zeile gibt es keine Adresse oder kein Lesemodul, oder die Abfrage ist aus. Hat eine Einstellung die Abfrage ausgeschaltet, fahre mit der Maus über den Strich, um zu sehen, welche. |

Der öffentliche Endpunkt von Kaspa meldet ein einziges Guthaben. Einen separaten ausstehenden
Betrag liefert er nicht.

Die On-Chain-Spalte zeigt das Guthaben der Adresse genau jetzt. Es kann
Überweisungen aus anderen Quellen enthalten. Das unbezahlte Guthaben des Pools zeigt, was der Pool
noch für dich hält. Eine OCEAN-Auszahlung über Lightning erscheint nicht im
On-Chain-Guthaben. Das Guthaben kann dir auch nicht sagen, welche Überweisungen von
deinem Pool kamen.

## Wähle, wohin die Abfrage geht { #choose-where-the-lookup-goes }

Jede Abfrage teilt deine öffentliche Auszahlungsadresse und die IP des UI-Servers mit dem
Explorer. Der Explorer kann Adressen verknüpfen, die du von derselben IP aus prüfst.

Setze die Basis-URL in der Umgebung des UI-Containers, wenn du einen eigenen Node betreibst.
Lass die Variable leer, um den Standard zu verwenden. Setze sie auf einen leeren Wert, um
die Abfrage für diese Chain auszuschalten.

Ein Compose-Override für den UI-Dienst könnte zum Beispiel Folgendes enthalten:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Verwende die Basis-URL der Esplora- oder Kaspa-API, wenn du Bitcoin oder Kaspa konfigurierst.
Der Bitcoin-Endpunkt liefert außerdem die Netzwerk-Difficulty und die Block-Belohnungen für die
[erwarteten Einnahmen](fleet.md#running-costs) eines Bitcoin-Pools. Diese Abfrage braucht ein
mempool-Backend (seine `/v1/mining`-API); ein einfacher Esplora-Server beantwortet nur die
Guthabenabfrage, und die Zeile des Pools zeigt dann keinen erwarteten Betrag.
Für Ethereum, Polygon und Solana setzt du die entsprechenden Variablen
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` oder
`CASHPILOT_ONCHAIN_URL_SOLANA` auf die RPC-URL eines Nodes. Verwende eine HTTP- oder HTTPS-URL
ohne Zugangsdaten, Query-String oder Fragment. Übernimm die Änderung, indem du
den UI-Container mit der neuen Umgebung neu erstellst.
