---
source_hash: 38029ca1a5d6
---
# Exportação de renda para impostos { #income-export-for-taxes }

Abra **Payouts** (Pagamentos), encontre **Income for taxes** (Renda para impostos) e selecione um intervalo de datas e uma moeda. **This year** (Este ano) vai até hoje, e **Last year** (Ano passado) cobre o ano-calendário anterior. Deixe as datas em branco para exportar o histórico disponível até hoje. O CashPilot usa datas em UTC e inclui as duas pontas do intervalo.

O CashPilot apaga as leituras de ganhos 400 dias depois de registrá-las. O CSV usa o histórico que resta, então um ano passado pode conter só parte da renda ganha ou acumulada dele.

## Escolha um regime contábil { #choose-an-accounting-basis }

- **Regime de caixa.** Use as linhas de payout. Elas registram o dinheiro que o serviço pagou. O CashPilot inclui apenas pagamentos confirmados.
- **Regime de competência.** Use as linhas earned e accrued. As linhas earned mostram crédito que você pode sacar nas condições do serviço. As linhas accrued mostram crédito não pago do pool, que o pool pode nunca pagar.

Use um único regime para a mesma renda. Somar as linhas de payout às linhas earned e accrued pode contar o mesmo dinheiro duas vezes. Verifique qual regime se aplica à sua declaração.

## Colunas do CSV { #csv-columns }

| Coluna | Significado |
|---|---|
| date | Dia em UTC da leitura mais recente ou do pagamento. Um pagamento usa a data que você informou ou o dia em que o CashPilot o detectou. |
| period_start | Dia em UTC da leitura anterior deste serviço e desta fonte. Em branco para pagamentos. Um intervalo entre leituras significa que o valor cobre o período inteiro. |
| kind | earned, accrued ou payout. |
| service | ID do serviço no CashPilot. |
| coin | Código da moeda ou do token conforme registrado pelo CashPilot. |
| amount | Valor nessa moeda ou nesse token. |
| usd_rate | Quantidade de dólares americanos por unidade de coin. |
| usd_value | Valor em dólares americanos. |
| local_currency | Moeda fiduciária que você selecionou para a exportação. |
| local_rate | Unidades da moeda selecionada por dólar americano. |
| local_value | Valor na moeda selecionada. |
| method | Método de pagamento, se registrado. |

Uma avaliação em branco significa que a cotação não estava disponível. O valor nativo continua presente. O CashPilot ignora pontos internos, como os pontos da Grass, nas leituras de ganhos. A primeira leitura de cada fonte fornece um saldo de abertura. As linhas seguintes registram aumentos, então o CSV pode começar depois da leitura mais antiga do intervalo selecionado.

Se mais de uma fonte lê a mesma conta, o CSV pode contar essa renda mais de uma vez.

A cotação em USD vem da leitura mais recente ou do registro do pagamento. Quando o CashPilot preenche retroativamente o preço de uma leitura, ele usa o preço do CoinGecko às 00:00 UTC daquele dia. O CashPilot usa a taxa de referência do BCE mais recente na data da linha ou antes dela para converter USD para a moeda selecionada. Isso cobre fins de semana, feriados e dias em que o BCE ainda não publicou a taxa. [Taxas diárias do Frankfurter](https://frankfurter.dev/v1/)

O Frankfurter lista estas moedas para a exportação. [Moedas suportadas](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR e ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD e ZAR.

Escolha USD se a sua moeda estiver fora dessa lista ou se o Frankfurter estiver indisponível.

## Importar em outra ferramenta { #import-into-another-tool }

Converta o CSV para o formato da ferramenta antes de importar. Primeiro escolha as linhas do seu regime contábil. Pule as linhas de payout de uma carteira que a ferramenta já sincroniza.

### rotki { #rotki }

Use Generic Events com estes cabeçalhos.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Defina Type como Income e Location como external. O rotki também aceita Deposit, Withdrawal, Loss, Spend e Staking quando esses tipos descrevem um evento. Mapeie coin para Currency, amount para Amount e service para Description. Use o identificador de ativo do rotki quando ele for diferente do código da moeda. Converta date em um timestamp Unix em UTC, em milissegundos. Deixe os dois campos de taxa em branco. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Use as colunas obrigatórias do template Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Formate Date como YYYY-MM-DD HH:mm:ss em UTC. Preencha Received Amount com amount e Received Currency com coin. Deixe os dois campos Sent em branco. Para os valores conhecidos, mapeie local_value e local_currency para os campos opcionais Net Worth Amount e Net Worth Currency. Use a coluna Tag para mining ou reward quando for o caso. Description e TxHash são opcionais. [Template Universal do Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Ainda não tem conta no Koinly? Você pode se cadastrar aqui: https://koinly.io/?via=FFF185D5. É um link de indicação, e não custa nada para você.

### CoinTracking { #cointracking }

Converta as linhas de renda para o formato CSV regular do CoinTracking. O Custom Importer exige campos de negociação dos dois lados, e uma linha de renda só tem o lado da compra. [Requisitos do Custom Importer do CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Defina Type como Income ou Mining, conforme o caso. Mapeie amount para Buy Amount, coin para Buy Currency e service para Comment. Deixe os campos Sell em branco. Formate Date como DD.MM.YYYY HH:MM:SS. A exportação fornece o dia em UTC, então use 00:00:00 como horário. Use os rótulos de tipo do idioma da sua conta. [Formato CSV regular do CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Ainda não tem conta no CoinTracking? Este link de cadastro dá 10% de desconto em todos os planos pagos: https://cointracking.info?ref=G962413. É um link de indicação. O CoinTracking paga ao projeto CashPilot 20% do que você pagar, e isso não custa mais para você.
