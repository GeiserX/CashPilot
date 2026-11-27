---
source_hash: ca9dd25d45ca
---
# Migrar do InternetIncome { #moving-from-internetincome }

O CashPilot consegue ler o `properties.conf` do InternetIncome e os arquivos em que ele
guarda os ids de dispositivo do EarnApp e do ProxyRack, e trazê-los. Você confere
tudo antes de o CashPilot salvar.

## Antes de começar { #before-you-start }

Você precisa da conta de proprietário do CashPilot e de pelo menos um worker do CashPilot.

Pare o InternetIncome em uma máquina antes de implantar os mesmos serviços nela pelo
CashPilot. Duas cópias atrás de uma única conexão ganham como uma só, e o mesmo id de dispositivo
não pode rodar duas vezes. Na pasta do InternetIncome, rode:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` remove os contêineres e mantém `earnapp.txt`, `proxyrack.txt` e
a pasta de dados do Mysterium. `--deleteBackup` remove esses também
([internetIncome.sh, linhas 61 a 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
e [linha 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
então importe antes.

## Quais arquivos usar { #which-files-to-use }

Da pasta do InternetIncome:

- `properties.conf`, as suas configurações.
- `earnapp.txt`, se você rodava o EarnApp. Cada linha contém um link de dispositivo
  ([linhas 1250 a 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, se você rodava o ProxyRack. Um UUID de dispositivo por linha
  ([linhas 817 a 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

O CashPilot pega o primeiro dispositivo de cada arquivo: aquele que o seu contêiner principal
usava e aquele que você vinculou à sua conta. As outras linhas pertenciam às cópias via
proxy, e a página informa quantas ficaram de fora.

O InternetIncome passa cada valor pelo shell
([linha 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Um valor entre aspas simples é usado como está escrito, como recomendam os comentários do
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Um valor fora de aspas simples que contém `$`, uma crase, um espaço ou
outro caractere que o shell alteraria não é o que o arquivo mostra, então o
CashPilot pede que você o digite de novo em vez de rodar um shell para descobrir.

## Como importar { #how-to-import }

1. Abra **Settings** (Configurações) e depois **Import from another tool** (Importar de outra ferramenta) (ou acesse `/import`).
2. Adicione o `properties.conf`, mais o `earnapp.txt` e o `proxyrack.txt` se você
   os tiver. Deixe a ferramenta em **Tell from the files** (Detectar pelos arquivos) ou escolha InternetIncome.
3. Confira a tabela. Marque os serviços que você quer e preencha qualquer valor marcado como
   ausente. O Repocket precisa do e-mail da sua conta, que o InternetIncome nunca pediu.
4. Clique em **Save the ticked services** (Salvar os serviços marcados) e depois implante-os nos seus workers pela
   mesma página.

## O que é trazido { #what-comes-over }

| App do InternetIncome | Chaves lidas | Serviço do CashPilot | O que é trazido |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | chave de API (adicione o seu e-mail) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | chave de API, UUID do dispositivo |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | e-mail, senha |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | e-mail, senha |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id de usuário |
| `earnfm` | `EARN_FM_API` | Earn.fm | chave de API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id do dispositivo |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | e-mail, senha |
| `mysterium` | `MYSTERIUM=true` | Mysterium | ativado; veja a observação sobre o Mysterium abaixo |

Um valor em branco significa que o app estava desativado, e ele não aparece na lista.

Estes apps aparecem na lista, mas não são trazidos:

| App do InternetIncome | Motivo |
|---|---|
| `urnetwork` | O InternetIncome usa um token de sessão. O CashPilot faz login no URnetwork com o seu e-mail e a sua senha. |
| `grass` | O Grass roda como extensão de navegador. O CashPilot apenas o acompanha, com o token de acesso do painel do Grass. |
| `titan`, `ebesucher`, `wipter` | O CashPilot acompanha esses, mas não há contêiner para implantar. |
| `peer2profit` | Não está mais disponível. |

As configurações de apps que o CashPilot não tem (antGain, Adnade e outros) aparecem
listadas pelo nome como não lidas.

## O que nunca é trazido { #what-never-comes-over }

- **`DEVICE_NAME`.** O CashPilot dá a cada dispositivo o nome do worker em que ele roda, para que
  dois workers nunca informem o mesmo nome. Os seus dispositivos antigos continuam listados como
  offline no painel de cada provedor até você removê-los lá.
- **Proxies** (`USE_PROXIES`, `proxies.txt`). Adicione cada um na seção **Proxies** (Proxies)
  da página **Fleet** (Frota) e depois rode cópias dos seus serviços por ele; adicionar
  um proxy não inicia nada por si só. Com `USE_PROXIES=true`, o InternetIncome rodava
  os seus serviços apenas por proxies. Salvar uma importação também não inicia nada. Uma
  cópia via proxy precisa que o mesmo serviço já esteja implantado no worker, e
  implantá-lo faz com que ele rode na própria conexão do worker, então um serviço que nunca
  deve usar essa conexão deve ficar desmarcado. Veja [Cópias via
  proxy](../proxies.md).
- **`BROWSER_USERNAME` e `BROWSER_PASSWORD`**, o login do navegador do próprio
  InternetIncome.

## Acompanhamento dos ganhos { #earnings-tracking }

No Honeygain, no IPRoyal Pawns e no Bitping, o login do contêiner também é o
login da conta, então o CashPilot preenche também as credenciais de ganhos deles, a menos que você
já as tenha definido em **Settings** (Configurações). Para todos os outros serviços, adicione o login de ganhos
em **Settings > Earnings collection** (Configurações > Coleta de ganhos).

## Mysterium { #mysterium }

A importação ativa o Mysterium, mas o CashPilot inicia um nó novo com uma nova
identidade. O keystore do nó antigo e quaisquer ganhos não liquidados ficam na
pasta `mysterium-data` do InternetIncome. Liquide-os antes ou siga o
[guia do Mysterium](../guides/mysterium.md) para levar a identidade junto.

## Segurança { #safety }

- Nada nos arquivos é executado ou expandido, e nenhum endereço contido neles é acessado.
- Os arquivos são lidos uma vez e não são guardados. O que você salva é armazenado criptografado, como
  todas as outras credenciais do CashPilot.
- Os segredos aparecem na página apenas como "definido".
- As importações salvas ficam na página de importação até você clicar em **Forget** (Esquecer), para que você possa
  implantá-las em mais workers depois.
