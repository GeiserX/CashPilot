---
source_hash: 7f8476aeb8b6
---
# Migrar do CashFactory { #moving-from-cashfactory }

O CashPilot consegue ler o `.env` do CashFactory e trazer os logins dos seus serviços, para
você não precisar digitá-los de novo. Você confere tudo antes de o CashPilot salvar.

## Antes de começar { #before-you-start }

Você precisa da conta de proprietário do CashPilot e de pelo menos um worker do CashPilot.

Pare o CashFactory em uma máquina antes de implantar os mesmos serviços nela pelo
CashPilot. Duas cópias atrás de uma única conexão ganham como uma só, e o mesmo id de dispositivo
do EarnApp não pode rodar duas vezes. Rode `docker compose down` na pasta
do CashFactory. O
[arquivo compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
dele também inicia três contêineres que montam o socket do Docker: o Portainer (linha 31)
e dois contêineres do Watchtower (linhas 141 e 264). Garanta que eles também tenham sumido: `docker ps` não deve
listar nenhum deles.

## Qual arquivo usar { #which-file-to-use }

Use o arquivo `.env` da sua pasta do CashFactory, aquele que você preencheu a partir do
[exemplo](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

O Docker Compose lê esse arquivo e expande `$` em valores que não estão entre
aspas simples. Um valor assim não é o que o arquivo mostra, então o CashPilot pede
que você o digite de novo em vez de tentar adivinhar.

## Como importar { #how-to-import }

1. Abra **Settings** (Configurações) e depois **Import from another tool** (Importar de outra ferramenta) (ou acesse `/import`).
2. Adicione o arquivo `.env` ou cole o texto dele. Deixe a ferramenta em **Tell from the
   files** (Detectar pelos arquivos) ou escolha CashFactory.
3. Confira a tabela. Marque os serviços que você quer e preencha qualquer valor marcado como
   ausente.
4. Clique em **Save the ticked services** (Salvar os serviços marcados) e depois implante-os nos seus workers pela
   mesma página.

## O que é trazido { #what-comes-over }

| App do CashFactory | Chaves lidas | Serviço do CashPilot | O que é trazido |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id do dispositivo, para que o seu dispositivo vinculado continue ganhando |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | e-mail, senha |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | e-mail, senha |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | e-mail, chave de API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id de usuário |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID do dispositivo |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | chave de API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | nada: não está mais disponível |

Um valor que ainda mostra o placeholder do exemplo (`<email>`, `sdk-node-<md5sum>`)
conta como não definido, e um serviço que só tem placeholders fica de fora da
tabela.

## O que nunca é trazido { #what-never-comes-over }

- **`DEVICE_NAME`.** O CashPilot dá a cada dispositivo o nome do worker em que ele roda, para que
  dois workers nunca informem o mesmo nome. Os seus dispositivos antigos continuam listados como
  offline no painel de cada provedor até você removê-los lá.
- **Bitping.** O CashFactory guarda o login do Bitping em um volume Docker, e não no
  `.env`, então a importação não tem nada para ler e não mostra nenhuma linha do Bitping. Digite o
  login no formulário de implantação do Bitping.
- **Portainer e Watchtower.** O CashPilot gerencia e atualiza os próprios
  contêineres.

## Acompanhamento dos ganhos { #earnings-tracking }

No Honeygain e no IPRoyal Pawns, o login do contêiner também é o login da conta,
então o CashPilot preenche também as credenciais de ganhos deles, a menos que você já
as tenha definido em **Settings** (Configurações). Para todos os outros serviços, adicione o login de ganhos em
**Settings > Earnings collection** (Configurações > Coleta de ganhos).

## Segurança { #safety }

- Nada no arquivo é executado ou expandido, e nenhum endereço contido nele é acessado.
- O arquivo é lido uma vez e não é guardado. O que você salva é armazenado criptografado, como
  todas as outras credenciais do CashPilot.
- Os segredos aparecem na página apenas como "definido".
- As importações salvas ficam na página de importação até você clicar em **Forget** (Esquecer), para que você possa
  implantá-las em mais workers depois.
