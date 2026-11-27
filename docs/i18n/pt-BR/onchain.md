---
source_hash: d88e40f8d9a6
---
# Saldos de pagamento on-chain { #on-chain-payout-balances }

Abra **Payouts** (Pagamentos) para ver o saldo de um endereço de pagamento público. O Bitcoin usa
[mempool.space](https://mempool.space/docs/api/rest) e o Kaspa usa
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon e Solana usam
nós RPC públicos. O CashPilot consegue ler esses endereços sem chave.

| O que você vê | O que significa |
|---|---|
| Um valor | O explorador informou um saldo. Um zero informado aparece como zero. Passe o mouse sobre o valor para ver a fonte. |
| **Pending** (Pendente) | No Bitcoin, o explorador vê uma alteração não confirmada. Um sinal de mais significa que há fundos chegando. Um sinal de menos significa que fundos estão sendo gastos. O valor confirmado aparece separado. |
| **Could not check** (Não foi possível verificar) | O explorador não respondeu ou enviou dados que o CashPilot não conseguiu ler. |
| **Address not valid** (Endereço inválido) | O endereço não passou na verificação de formato. O CashPilot pulou a consulta. |
| **Private chain** (Blockchain privada) | Ler um saldo de Monero exige a sua chave de visualização privada. Verifique o saldo na sua carteira. O CashPilot nunca pede essa chave a você. |
| Um traço | Não há endereço nem leitor para esta linha, ou a consulta está desativada. Quando uma configuração desativa a consulta, passe o mouse sobre o traço para ver qual. |

O endpoint público do Kaspa informa um único saldo. Ele não fornece um valor
pendente separado.

A coluna on-chain mostra o saldo do endereço neste momento. Ela pode incluir
transferências de outras origens. O saldo não pago do pool mostra o que o pool
ainda guarda para você. Um pagamento do OCEAN pela Lightning não aparece no
saldo on-chain. O saldo também não consegue dizer quais transferências vieram do
seu pool.

## Escolha para onde vai a consulta { #choose-where-the-lookup-goes }

Cada consulta compartilha com o explorador o seu endereço de pagamento público e o IP do servidor da UI.
O explorador pode vincular os endereços que você consulta a partir do mesmo IP.

Defina a URL base no ambiente do contêiner da UI se você roda o seu próprio nó.
Deixe a variável sem definir para usar o padrão. Defina-a com um valor vazio para desativar
a consulta dessa blockchain.

Por exemplo, um override do Compose para o serviço da UI poderia conter:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Use a URL base da API Esplora ou Kaspa ao configurar Bitcoin ou Kaspa.
O endpoint do Bitcoin também fornece a dificuldade da rede e as recompensas de bloco para os
[ganhos esperados](fleet.md#running-costs) de um pool de Bitcoin. Essa leitura precisa de um
backend mempool (a API `/v1/mining` dele); um servidor Esplora simples só responde à
consulta de saldo, e a linha do pool então não mostra nenhum valor esperado.
Para Ethereum, Polygon e Solana, defina as variáveis correspondentes
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` ou
`CASHPILOT_ONCHAIN_URL_SOLANA` com a URL RPC de um nó. Use uma URL HTTP ou HTTPS
sem credenciais, query string nem fragmento. Aplique a mudança
recriando o contêiner da UI com o novo ambiente.
