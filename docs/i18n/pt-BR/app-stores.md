---
source_hash: e99e2c0c80bb
---
# Lojas de apps { #app-stores }

Você pode instalar o CashPilot pela loja de apps de vários sistemas de servidor doméstico.
Cada listagem instala o painel (`drumsergio/cashpilot`) e o worker
(`drumsergio/cashpilot-worker`), que inicia e para os contêineres
dos serviços. Apenas os pacotes de CasaOS e Runtipi deste repositório também
instalam o socket proxy do Docker a partir do `docker-compose.yml`, então o worker deles
nunca segura o socket bruto do Docker. Os templates do Unraid, o app do TrueNAS e
o pacote no pull request aberto na loja de apps do CasaOS ainda montam o socket
do Docker diretamente no worker.

Seja qual for a loja que você usar, mantenha o painel na sua LAN ou VPN. Ele pode comandar
o worker, e o worker controla o Docker no host. Quando o próprio worker segura
o socket, isso equivale a root no host.

## Disponíveis hoje { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Pesquise **CashPilot** na aba Apps e instale os dois templates:
`cashpilot` (o painel) e `cashpilot-worker`. Defina a mesma
`CASHPILOT_API_KEY` nos dois.

Os templates vêm de https://github.com/GeiserX/docker-templates e seguem
a tag de imagem `latest`, então os usuários do Community Applications recebem cada versão
sem nenhuma mudança no template.

### TrueNAS SCALE { #truenas-scale }

O CashPilot está no train **community** do TrueNAS. Abra Apps, depois Discover Apps,
e pesquise **CashPilot**.

A definição do app é mantida em
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot e fixa
um digest de imagem exato. Os próprios bots do TrueNAS a atualizam para as novas versões, então ela pode
estar algumas versões atrás do CashPilot mais recente.

## Aguardando revisão { #waiting-for-review }

### CasaOS { #casaos }

Há um pull request aberto na loja de apps do CasaOS:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Até ele ser aceito, instale como app personalizado: no CasaOS, escolha App Store,
depois Custom Install, depois Import, e cole o conteúdo de
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

É preciso o CasaOS 0.4.5 ou mais recente: a partir dessa versão, o gerenciador de apps dele é baseado no
Docker Compose 2.23, que lê do arquivo a política do socket proxy.
As versões mais antigas a descartam, e aí o worker não consegue alcançar o Docker.

Esse arquivo fixa uma versão exata. Antes de importá-lo, defina as duas tags de imagem
(`drumsergio/cashpilot` e `drumsergio/cashpilot-worker`) com a versão
mais recente de https://github.com/GeiserX/CashPilot/releases. A política do proxy
no arquivo segue a `main`; se a página de status do worker disser que a política dele está
desatualizada, importe o arquivo de novo.

## Preparados, ainda não enviados { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

O pacote está pronto em
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
mas ainda não está na loja de apps do Runtipi. Para usá-lo agora, adicione-o a uma loja de apps
personalizada que você controla, seguindo a documentação do Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Não oferecidos { #not-offered }

O Umbrel precisa de um design de worker diferente, porque os apps do Umbrel alcançam o Docker
por um contêiner Docker-in-Docker, e não pelo socket do host. Ainda não
testamos isso, então ainda não existe um pacote para o Umbrel.

Para qualquer outro sistema, use o `docker-compose.yml` do repositório, como em
[Primeiros passos](getting-started.md).
