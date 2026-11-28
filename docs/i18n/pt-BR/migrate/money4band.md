---
source_hash: 05d0f97e7d36
---
# Migrar do money4band { #moving-from-money4band }

O CashPilot consegue ler a configuração do money4band e trazer os logins dos seus serviços, para
você não precisar digitá-los de novo. Você confere tudo antes de o CashPilot salvar.

## Antes de começar { #before-you-start }

Você precisa da conta de proprietário do CashPilot e de pelo menos um worker do CashPilot na
máquina em que o money4band roda hoje, ou em outra máquina.

Pare o money4band em uma máquina antes de implantar os mesmos serviços nela pelo
CashPilot. Duas cópias atrás de uma única conexão ganham como uma só, e o mesmo id de dispositivo do EarnApp
ou do ProxyRack não pode rodar duas vezes. Use **Stop apps stack** no
menu do money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
ou rode `docker compose down` na pasta dele. Se você configurou instâncias de proxy
extras, pare cada uma delas também.

## Qual arquivo usar { #which-file-to-use }

Use o `config/user-config.json` da sua pasta do money4band. Como você o leva ao
CashPilot depende da sua versão do money4band.

No money4band 4.x, o money4band grava o arquivo quando você roda **Setup Apps**, e
ele contém exatamente o que você digitou. O `.env`
ao lado dele é gerado a partir desse arquivo e também funciona, assim como o `.env`
editado à mão do money4band 3.x. Os dois ficam apenas no seu disco: o
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
do money4band os lista.

O money4band 5.0 criptografa o `config/user-config.json` no disco
([notas de segurança](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
e apaga o `.env` dele depois de cada inicialização
([gerador do env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
O CashPilot não consegue ler o arquivo criptografado. Na sua pasta do money4band, rode
o comando `config edit` dele: `./Money4Band-<os>-<arch> config edit` para o binário
publicado, ou `python main.py config edit` a partir do código-fonte. Ele abre o
arquivo descriptografado no seu editor
([referência da CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Copie todo o texto dele, cole na página **Import from another tool** (Importar de outra ferramenta) e depois feche o editor.

Prefira o arquivo JSON. Em um `.env`, o Docker Compose expande `$` em valores
sem aspas, então uma senha com `$` não é o que o arquivo mostra. O CashPilot não
tenta adivinhar: ele pede que você digite esse valor de novo.

## Como importar { #how-to-import }

1. Abra **Settings** (Configurações) e depois **Import from another tool** (Importar de outra ferramenta) (ou acesse `/import`).
2. Adicione o `user-config.json` ou cole o texto dele. Deixe a ferramenta em **Tell from the
   files** (Detectar pelos arquivos) ou escolha money4band.
3. Confira a tabela. Marque os serviços que você quer e preencha qualquer valor marcado como
   ausente.
4. Clique em **Save the ticked services** (Salvar os serviços marcados) e depois implante-os nos seus workers pela
   mesma página.

## O que é trazido { #what-comes-over }

Os nomes dos campos vêm do
[template de user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
do money4band e dos nomes do `.env` que o
[gerador](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
dele grava (`<APP>_<FLAG>`, por exemplo `REPOCKET_APIKEY`). O money4band 5.0 mantém
os mesmos nomes de campo no
[catálogo de apps](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported) dele.

| App do money4band | Serviço do CashPilot | O que é trazido |
|---|---|---|
| `earnapp` | EarnApp | id do dispositivo (`uuid`), para que o seu dispositivo vinculado continue ganhando |
| `honeygain` | Honeygain | e-mail, senha |
| `iproyalpawns` | IPRoyal Pawns | e-mail, senha |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | e-mail, chave de API |
| `earnfm` | Earn.fm | chave de API |
| `proxyrack` | ProxyRack | chave de API, UUID do dispositivo |
| `proxylite` | ProxyLite | id de usuário |
| `bitping` | Bitping | e-mail, senha |
| `mystnode` | Mysterium | ativado; veja a observação sobre o Mysterium abaixo |

Um app que você desativou no money4band aparece desmarcado. Um app que está desativado e
não contém nada além dos placeholders do template (`yourHONEYGAINMail`) e das listas de portas
fica de fora, então um `user-config.json` intocado gera uma tabela vazia.

Estes apps aparecem na lista, mas não são trazidos:

| App do money4band | Motivo |
|---|---|
| `proxybase` | O money4band roda o cliente antigo do ProxyBase com um id de usuário. O CashPilot roda o atual, que precisa do Access Token de proxybase.org. |
| `urnetwork` | O money4band guarda um token de sessão. O CashPilot faz login no URnetwork com o seu e-mail e a sua senha. |
| `grass` | O Grass roda como extensão de navegador. O CashPilot apenas o acompanha, com o token de acesso do painel do Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | O CashPilot acompanha esses, mas não há contêiner para implantar. |
| `packetshare`, `peer2profit`, `speedshare` | Não estão mais disponíveis. |

Qualquer outro app aparece como **CashPilot has no such service** (O CashPilot não tem esse serviço).

## O que nunca é trazido { #what-never-comes-over }

- **Nome do dispositivo.** O CashPilot dá a cada dispositivo o nome do worker em que ele roda, para que
  dois workers nunca informem o mesmo nome. Os seus dispositivos antigos continuam listados como
  offline no painel de cada provedor até você removê-los lá.
- **Proxies.** Adicione cada um na seção **Proxies** (Proxies) da página **Fleet** (Frota) e depois rode
  cópias dos seus serviços por ele; adicionar um proxy não inicia nada por si só.
  Salvar uma importação também não inicia nada. Uma cópia via proxy precisa que o mesmo serviço
  já esteja implantado no worker, e implantá-lo faz com que ele rode na própria conexão do worker, então um serviço que nunca
  deve usar essa conexão deve ficar desmarcado. Veja [Cópias via proxy](../proxies.md).
- **Watchtower e notificações.** O CashPilot atualiza os próprios contêineres.
- **O painel do money4band e as portas dele.**

## Acompanhamento dos ganhos { #earnings-tracking }

No Honeygain, no IPRoyal Pawns e no Bitping, o login do contêiner também é o
login da conta, então o CashPilot preenche também as credenciais de ganhos deles, a menos que você
já as tenha definido em **Settings** (Configurações). Para todos os outros serviços, adicione o login de ganhos
em **Settings > Earnings collection** (Configurações > Coleta de ganhos).

## Mysterium { #mysterium }

A importação ativa o Mysterium, mas o CashPilot inicia um nó novo com uma nova
identidade. O keystore do nó antigo e quaisquer ganhos não liquidados ficam na
pasta `.data/mysterium-node` do money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Liquide-os antes ou siga o
[guia do Mysterium](../guides/mysterium.md) para levar a identidade junto.

Um `.env` 3.x não tem como dizer se você rodava o Mysterium: o template dele sempre
lista a porta do painel. A partir de um arquivo 3.x, o Mysterium não é importado, então adicione-o
pelo catálogo se você o rodava.

## Segurança { #safety }

- Nada no arquivo é executado ou expandido, e nenhum endereço contido nele é acessado.
- O arquivo é lido uma vez e não é guardado. O que você salva é armazenado criptografado, como
  todas as outras credenciais do CashPilot.
- Os segredos aparecem na página apenas como "definido".
- As importações salvas ficam na página de importação até você clicar em **Forget** (Esquecer), para que você possa
  implantá-las em mais workers depois.
