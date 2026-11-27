---
source_hash: d88e40f8d9a6
---
# Saldos de pago on-chain { #on-chain-payout-balances }

Abre **Payouts** (Pagos) para ver el saldo de una dirección de pago pública. Bitcoin usa
[mempool.space](https://mempool.space/docs/api/rest) y Kaspa usa
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon y Solana usan
nodos RPC públicos. CashPilot puede leer estas direcciones sin ninguna clave.

| Lo que ves | Qué significa |
|---|---|
| Un importe | El explorador informó de un saldo. Un cero informado aparece como cero. Pasa el cursor sobre el importe para ver la fuente. |
| Pending (pendiente) | En Bitcoin, el explorador ve un cambio sin confirmar. Un signo más significa que llegan fondos. Un signo menos significa que se están gastando fondos. El importe confirmado se muestra aparte. |
| Could not check (no se pudo comprobar) | El explorador no respondió o envió datos que CashPilot no pudo leer. |
| Address not valid (dirección no válida) | La dirección no pasó una comprobación de formato. CashPilot no hizo la consulta. |
| Private chain (cadena privada) | Para leer un saldo de Monero hace falta tu clave privada de visualización. Comprueba el saldo en tu billetera. CashPilot nunca te pide esta clave. |
| Un guion | No hay dirección ni lector para esta fila, o la consulta está desactivada. Cuando un ajuste desactiva la consulta, pasa el cursor sobre el guion para ver cuál. |

El endpoint público de Kaspa informa de un solo saldo. No da un importe
pendiente aparte.

La columna on-chain muestra el saldo que tiene la dirección en este momento. Puede incluir
transferencias de otras fuentes. El saldo no pagado del pool muestra lo que el pool
todavía guarda para ti. Un pago de OCEAN por Lightning no aparece en el
saldo on-chain. El saldo tampoco puede decirte qué transferencias vinieron de
tu pool.

## Elige adónde va la consulta { #choose-where-the-lookup-goes }

Cada consulta comparte con el explorador tu dirección de pago pública y la IP del servidor de la UI.
El explorador puede relacionar las direcciones que consultas desde la misma IP.

Configura la URL base en el entorno del contenedor de la UI si tienes tu propio nodo.
Deja la variable sin configurar para usar la predeterminada. Ponle un valor vacío para desactivar
la consulta de esa cadena.

Por ejemplo, un override de Compose para el servicio de la UI podría contener:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Usa la URL base de la API de Esplora o de Kaspa al configurar Bitcoin o Kaspa.
El endpoint de Bitcoin también da la dificultad de la red y las recompensas por bloque para las
[ganancias esperadas](fleet.md#running-costs) de un pool de Bitcoin. Esa lectura necesita un
backend de mempool (su API `/v1/mining`); un servidor Esplora sin más solo responde a la
consulta del saldo, y entonces la fila del pool no muestra ningún importe esperado.
Para Ethereum, Polygon y Solana, pon en las variables correspondientes
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` o
`CASHPILOT_ONCHAIN_URL_SOLANA` la URL RPC de un nodo. Usa una URL HTTP o HTTPS
sin credenciales, sin query string y sin fragmento. Aplica el cambio
volviendo a crear el contenedor de la UI con el nuevo entorno.
