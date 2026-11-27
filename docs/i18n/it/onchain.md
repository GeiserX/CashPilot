---
source_hash: d88e40f8d9a6
---
# Saldi di pagamento on-chain { #on-chain-payout-balances }

Apri **Payouts** (Pagamenti) per vedere il saldo di un indirizzo di pagamento pubblico. Bitcoin usa
[mempool.space](https://mempool.space/docs/api/rest) e Kaspa usa
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon e Solana usano
nodi RPC pubblici. CashPilot può leggere questi indirizzi senza una chiave.

| Cosa vedi | Cosa significa |
|---|---|
| Un importo | L'explorer ha riportato un saldo. Uno zero riportato compare come zero. Passa il puntatore sull'importo per vedere la fonte. |
| In sospeso | Su Bitcoin, l'explorer vede una variazione non confermata. Un più significa fondi in arrivo. Un meno significa fondi in uscita. L'importo confermato è mostrato a parte. |
| Impossibile verificare | L'explorer non ha risposto o ha inviato dati che CashPilot non ha saputo leggere. |
| Indirizzo non valido | L'indirizzo non ha superato un controllo di formato. CashPilot ha saltato la richiesta. |
| Catena privata | Leggere un saldo Monero richiede la tua chiave di visualizzazione privata. Controlla il saldo nel tuo wallet. CashPilot non ti chiede mai questa chiave. |
| Un trattino | Per questa riga non c'è un indirizzo o un lettore, oppure la ricerca è disattivata. Quando è un'impostazione a disattivare la ricerca, passa il puntatore sul trattino per vedere quale. |

L'endpoint pubblico di Kaspa riporta un solo saldo. Non fornisce un importo
in sospeso separato.

La colonna on-chain mostra il saldo dell'indirizzo in questo momento. Può includere
trasferimenti da altre fonti. Il saldo non pagato del pool mostra ciò che il pool
tiene ancora per te. Un pagamento di OCEAN tramite Lightning non compare nel
saldo on-chain. Il saldo inoltre non può dirti quali trasferimenti sono arrivati dal
tuo pool.

## Scegli dove va la ricerca { #choose-where-the-lookup-goes }

Ogni ricerca condivide con l'explorer il tuo indirizzo di pagamento pubblico e l'IP del server della UI.
L'explorer può collegare tra loro gli indirizzi che controlli dallo stesso IP.

Se gestisci un tuo nodo, imposta l'URL di base nell'ambiente del container della UI.
Lascia la variabile non impostata per usare il valore predefinito. Impostala a un valore vuoto per disattivare
la ricerca per quella catena.

Per esempio, un override di Compose per il servizio della UI potrebbe contenere:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Per configurare Bitcoin o Kaspa usa l'URL di base dell'API Esplora o Kaspa.
L'endpoint di Bitcoin fornisce anche la difficoltà della rete e le ricompense dei blocchi per i
[guadagni attesi](fleet.md#running-costs) di un pool Bitcoin. Quella lettura richiede un
backend mempool (la sua API `/v1/mining`); un semplice server Esplora risponde solo alla
ricerca del saldo, e allora la riga del pool non mostra nessun importo atteso.
Per Ethereum, Polygon e Solana, imposta le variabili corrispondenti
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` o
`CASHPILOT_ONCHAIN_URL_SOLANA` all'URL RPC di un nodo. Usa un URL HTTP o HTTPS
senza credenziali, query string o frammento. Applica la modifica
ricreando il container della UI con il nuovo ambiente.
