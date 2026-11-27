---
source_hash: 38029ca1a5d6
---
# Exportación de ingresos para impuestos { #income-export-for-taxes }

Abre **Payouts** (Pagos), busca **Income for taxes** (Ingresos para impuestos) y elige un rango de fechas y una moneda. **This year** (Este año) llega hasta hoy, y **Last year** (El año pasado) cubre el año natural anterior. Deja las fechas en blanco para exportar todo el historial disponible hasta hoy. CashPilot usa fechas en UTC e incluye los dos extremos del rango.

CashPilot borra las lecturas de ganancias 400 días después de registrarlas. El CSV usa el historial que queda, así que un año pasado puede contener solo una parte de sus ingresos ganados o devengados.

## Elige un criterio contable { #choose-an-accounting-basis }

- **Criterio de caja.** Usa las filas de pago. Registran el dinero que el servicio te pagó. CashPilot incluye solo los pagos confirmados.
- **Criterio de devengo.** Usa las filas ganadas y devengadas. Las filas ganadas muestran crédito que puedes retirar según las condiciones del servicio. Las filas devengadas muestran crédito no pagado del pool que puede que el pool no llegue a pagar nunca.

Usa un solo criterio para los mismos ingresos. Sumar las filas de pago a las filas ganadas y devengadas puede contar dos veces el mismo dinero. Comprueba qué criterio se aplica a tu declaración.

## Columnas del CSV { #csv-columns }

| Columna | Significado |
|---|---|
| date | Día UTC de la lectura posterior o del pago. Un pago usa la fecha que introdujiste o el día en que CashPilot lo detectó. |
| period_start | Día UTC de la lectura anterior de este servicio y esta fuente. En blanco en los pagos. Un hueco entre lecturas significa que el importe cubre todo el intervalo. |
| kind | earned (ganado), accrued (devengado) o payout (pago). |
| service | ID del servicio en CashPilot. |
| coin | Código de la moneda o del token tal como lo registró CashPilot. |
| amount | Importe en esa moneda o ese token. |
| usd_rate | Número de dólares estadounidenses por unidad de coin. |
| usd_value | Importe valorado en dólares estadounidenses. |
| local_currency | Moneda fiat que elegiste para la exportación. |
| local_rate | Unidades de la moneda que elegiste por cada dólar estadounidense. |
| local_value | Importe valorado en la moneda que elegiste. |
| method | Método de pago, si se registró. |

Una valoración en blanco significa que el tipo de cambio no estaba disponible. El importe nativo sigue presente. CashPilot omite los puntos internos, como los puntos de Grass, en las lecturas de ganancias. La primera lectura de cada fuente da un saldo inicial. Las filas posteriores registran aumentos, así que el CSV puede empezar después de la lectura más antigua del rango elegido.

Si más de una fuente lee la misma cuenta, el CSV puede contar esos ingresos más de una vez.

El tipo en USD viene de la lectura posterior o del registro del pago. Cuando CashPilot completa a posteriori el precio de una lectura, usa el precio de CoinGecko a las 00:00 UTC de ese día. Para convertir de USD a la moneda que elegiste, CashPilot usa el tipo de referencia del BCE más reciente en el día de la fila o antes. Esto cubre los fines de semana, los festivos y los días en que el BCE aún no ha publicado su tipo. [Tipos diarios de Frankfurter](https://frankfurter.dev/v1/)

Frankfurter ofrece estas monedas para la exportación. [Monedas compatibles](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR e ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD y ZAR.

Elige USD si tu moneda no está en esa lista o si Frankfurter no está disponible.

## Importar en otra herramienta { #import-into-another-tool }

Convierte el CSV al formato de la herramienta antes de importarlo. Primero elige las filas de tu criterio contable. Omite las filas de pago de una billetera que la herramienta ya sincroniza.

### rotki { #rotki }

Usa Generic Events con estas cabeceras.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Pon Type en Income y Location en external. rotki también acepta Deposit, Withdrawal, Loss, Spend y Staking cuando esos tipos describen un evento. Asigna coin a Currency, amount a Amount y service a Description. Usa el identificador de activo de rotki cuando sea distinto del código de la moneda. Convierte date a una marca de tiempo Unix en UTC, en milisegundos. Deja en blanco los dos campos de comisión. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Usa las columnas obligatorias de la plantilla Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Da a Date el formato YYYY-MM-DD HH:mm:ss en UTC. Rellena Received Amount con amount y Received Currency con coin. Deja en blanco los dos campos Sent. Para los valores conocidos, asigna local_value y local_currency a las columnas opcionales Net Worth Amount y Net Worth Currency. Usa la columna Tag para mining o reward cuando corresponda. Description y TxHash son opcionales. [Plantilla Universal de Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

¿Aún no tienes cuenta de Koinly? Puedes registrarte aquí: https://koinly.io/?via=FFF185D5. Es un enlace de referido y no te cuesta nada.

### CoinTracking { #cointracking }

Convierte las filas de ingresos al formato CSV normal de CoinTracking. El Custom Importer exige campos de operación en los dos lados, y una fila de ingresos solo tiene el lado de compra. [Requisitos del Custom Importer de CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Pon Type en Income o Mining según corresponda. Asigna amount a Buy Amount, coin a Buy Currency y service a Comment. Deja en blanco los campos Sell. Da a Date el formato DD.MM.YYYY HH:MM:SS. La exportación da el día en UTC, así que usa 00:00:00 como hora. Usa las etiquetas de tipo del idioma de tu cuenta. [Formato CSV normal de CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

¿Aún no tienes cuenta de CoinTracking? Este enlace de registro te da un 10 % de descuento en todos los planes de pago: https://cointracking.info?ref=G962413. Es un enlace de referido. CoinTracking paga al proyecto CashPilot el 20 % de lo que pagues, y a ti no te cuesta más.
