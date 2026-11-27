---
source_hash: d88e40f8d9a6
---
# On-chain saldi van uitbetalingen { #on-chain-payout-balances }

Open **Payouts** (Uitbetalingen) om het saldo op een openbaar uitbetalingsadres te zien. Bitcoin gebruikt
[mempool.space](https://mempool.space/docs/api/rest) en Kaspa gebruikt
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon en Solana gebruiken
openbare RPC-nodes. CashPilot kan deze adressen zonder sleutel lezen.

| Wat je ziet | Wat het betekent |
|---|---|
| Een bedrag | De explorer meldde een saldo. Een gemeld nul verschijnt als nul. Beweeg de muis over het bedrag om de bron te zien. |
| **Pending** (In behandeling) | Op Bitcoin ziet de explorer een onbevestigde wijziging. Een plus betekent dat er geld binnenkomt. Een min betekent dat er geld wordt uitgegeven. Het bevestigde bedrag staat er apart bij. |
| **Could not check** (Kon niet controleren) | De explorer antwoordde niet of stuurde gegevens die CashPilot niet kon lezen. |
| **Address not valid** (Adres niet geldig) | Het adres slaagde niet voor een formaatcontrole. CashPilot sloeg het verzoek over. |
| **Private chain** (Privéchain) | Om een Monero-saldo te lezen is je privé-view key nodig. Controleer het saldo in je wallet. CashPilot vraagt je nooit om deze sleutel. |
| Een streepje | Er is geen adres of lezer voor deze rij, of het opzoeken staat uit. Als een instelling het opzoeken uitzet, beweeg dan de muis over het streepje om te zien welke. |

Het openbare endpoint van Kaspa meldt één saldo. Het geeft geen apart bedrag
dat nog in behandeling is.

De on-chain kolom toont het saldo op het adres op dit moment. Daar kunnen
overboekingen uit andere bronnen in zitten. Het onbetaalde saldo van de pool toont wat de pool
nog voor je vasthoudt. Een OCEAN-uitbetaling via Lightning verschijnt niet in het
on-chain saldo. Het saldo kan je ook niet vertellen welke overboekingen van
je pool kwamen.

## Kies waar het opzoeken heen gaat { #choose-where-the-lookup-goes }

Elke opzoeking deelt je openbare uitbetalingsadres en het IP-adres van de UI-server met de
explorer. De explorer kan adressen die je vanaf hetzelfde IP-adres controleert aan elkaar koppelen.

Stel de basis-URL in de omgeving van de UI-container in als je je eigen node draait.
Laat de variabele weg om de standaard te gebruiken. Geef hem een lege waarde om
het opzoeken voor die chain uit te zetten.

Een Compose-override voor de UI-dienst kan bijvoorbeeld dit bevatten:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Gebruik de basis-URL van de Esplora- of Kaspa-API wanneer je Bitcoin of Kaspa instelt.
Het Bitcoin-endpoint geeft ook de netwerkmoeilijkheid en de blokbeloningen voor de
[verwachte inkomsten](fleet.md#running-costs) van een Bitcoin-pool. Die lezing heeft een
mempool-backend nodig (de API `/v1/mining`); een gewone Esplora-server beantwoordt alleen het
opzoeken van het saldo, en de rij van de pool toont dan geen verwacht bedrag.
Stel voor Ethereum, Polygon en Solana de bijbehorende variabelen
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` of
`CASHPILOT_ONCHAIN_URL_SOLANA` in op de RPC-URL van een node. Gebruik een HTTP- of HTTPS-URL
zonder inloggegevens, querystring of fragment. Pas de wijziging toe door
de UI-container opnieuw te maken met de nieuwe omgeving.
