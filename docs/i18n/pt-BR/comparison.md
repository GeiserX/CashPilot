---
source_hash: 06e0336d2a02
---
# Como o CashPilot se compara { #how-cashpilot-compares }

Esta página compara o CashPilot com os outros projetos abertos que rodam vários apps de renda passiva no Docker. Verificamos cada projeto em 2026-11-04, e o CashPilot de novo em 2026-11-28. Cada célula sobre outro projeto aponta para o arquivo de onde ela vem, em um commit fixo, para que você possa conferir por conta própria. Se uma célula estiver errada ou desatualizada, [abra uma issue](https://github.com/GeiserX/CashPilot/issues).

## Projetos comparados { #projects-compared }

| Projeto | O que verificamos | Estrelas em 2026-11-04 | Licença |
|---|---|---|---|
| [money4band][m4b-tree] | Versão 5.0.0, commit da tag `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` em `65e900d` (2026-10-20), mais o que o README afirma sobre o binário 3.0.0-beta.9 | 238 | Proprietária, [licença própria v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` em `db9338a` (2026-11-03) | 257 | Sem arquivo LICENSE. O [README][ii-license] permite copiar o original e proíbe distribuir cópias modificadas |
| [CashFactory][cf-tree] | `main` em `0ff4bd0` (2025-04-08) | 410 | O arquivo [LICENSE][cf-license-file] é GPL-3.0, mas o [README][cf-license] proíbe distribuir cópias modificadas |
| [home-assistant-passive-income][ha-tree] (add-ons do HA) | Versão 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Versão v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

O money4band tem duas linhas de código. O branch padrão `main` (`3bfafb1`) ainda contém o código 4.x, e a última mudança de código nele foi em 2026-03-03. A versão 5.0.0 é construída a partir de um histórico separado. Comparamos a 5.0.0 porque é ela que a versão mais recente distribui.

A UI web, o gerenciamento de frota e o binário instalador do IGM são de código fechado e não estão no repositório. Quando uma célula depende deles, ela diz "o README afirma" e aponta para a linha do README. Todo o resto da coluna do IGM vem dos scripts shell e dos arquivos compose do repositório.

Ficaram de fora: [earning-machine](https://github.com/jf-m/earning-machine) e [passiveMachine](https://github.com/Xpl0itU/passiveMachine) não têm commits desde 2024. Uma busca no GitHub não encontrou mais nada mantido que rode mais de um app, apenas imagens de um único app.

## Versão curta { #short-version }

- **InternetIncome, money4band, IGM e, desde a v1.69.0, o CashPilot conseguem ganhar em vários IPs por meio de proxies.** Os três primeiros rodam cada app uma vez por proxy, e os proxies são o recurso principal do InternetIncome. O CashPilot roda cópias extras de um serviço já implantado em um worker, cada uma por um proxy SOCKS5, HTTP CONNECT ou exit node do Tailscale ([cópias via proxy](proxies.md)).
- **O InternetIncome inicia 23 apps, o IGM inicia 20 e o worker do CashPilot inicia <!-- n:docker -->21<!-- /n -->.** O CashPilot acompanha mais serviços no total (<!-- n:live -->50<!-- /n -->) porque também segue serviços de extensão de navegador, desktop e GPU que ele não roda. Desde a v1.64.0, ele também consegue rodar qualquer imagem que você indicar como um [serviço personalizado](custom-services.md).
- **O money4band e o IGM resgatam recompensas diárias por você e mantêm as imagens dos apps atualizadas com o Watchtower.** O CashPilot não faz nenhuma das duas coisas. Ele só baixa uma imagem de novo quando você implanta ou reimplanta.
- **O CashPilot é o único aqui que lê os saldos das suas contas nos provedores e mantém um histórico.** O money4band 5.0.0 mostra estimativas do próprio catálogo, e não das suas contas. Os outros apontam para o painel de cada provedor.
- **O CashPilot é o único de código aberto aqui com uma única UI para vários servidores.** O README do IGM afirma ter gerenciamento de frota, mas esse código está no binário fechado.
- **Desde a v1.70.0, o CashPilot é o único aqui que mantém os contêineres dos apps de renda fora da sua LAN por padrão, com limites.** Isso vem ativado em instalações novas e em instalações atualizadas sem nenhum app de renda na bridge padrão do Docker. Uma instalação atualizada cujos apps de renda já estão nessa bridge os mantém lá até você ativar o isolamento e uma rede que você indicar em `CASHPILOT_CONTAINER_NETWORK` não recebe barreira do CashPilot ([isolamento](isolation.md#modes)). Desde a 2.0.7, o Mysterium também roda atrás da barreira; um nó implantado até a 2.0.6 fica na rede do host, sem barreira, até você reimplantá-lo ([Mysterium atrás da barreira](mysterium-fence.md)).

## Lado a lado { #side-by-side }

A coluna do CashPilot descreve a v3.0.1. Cada célula dela é curta, e as [notas abaixo da tabela](#cashpilot-notes) trazem os detalhes e os links para o código. As outras colunas descrevem os commits da tabela acima.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Add-ons do HA |
|---|---|---|---|---|---|---|
| Apps que ele consegue iniciar (veja [como contamos](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> rodados pelo worker, mais [imagens personalizadas](custom-services.md); <!-- n:live -->50<!-- /n --> acompanhados no total | 15 ([catálogo][m4b-catalog]). O README diz 35, o que [inclui][m4b-readme-35] apps da comunidade e apps abandonados | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([arquivo compose][cf-compose]) | 10 ([pastas de add-ons][ha-tree]) |
| Como instalar | Docker Compose: uma UI, mais um worker em cada servidor ([frota](fleet.md)) | CLI em Python ou um binário pré-compilado que gera um arquivo compose ([versão][m4b-tree]) | Instalador `curl \| sh` ([README][igm-install]) que baixa um binário fechado, verificado apenas contra um arquivo SHA256SUMS da mesma versão ([instalador][igm-installer-sums]) | Um único script bash de 1.608 linhas que chama `sudo docker run` ([script][ii-script]) | Um arquivo compose estático mais um `setup.sh` executado com sudo ([setup][cf-setup]) | Um repositório de add-ons do Home Assistant; exige Home Assistant OS ou Supervised |
| Vários servidores, uma visão | Sim ([frota](fleet.md)) | Não, uma stack por dispositivo | O README afirma que sim, no binário fechado ([README][igm-features]) | Não | Não | Não |
| Vários proxies ou IPs | Sim, por proxies SOCKS5, HTTP CONNECT ou exit nodes do Tailscale ([cópias via proxy](proxies.md), [notas](#cashpilot-notes)) | Sim ([README][m4b-features], [código][m4b-multiproxy]) | Sim ([README][igm-features], [compose][igm-proxy]) | Sim, é o recurso principal ([README][ii-readme-top]) | Não | Não |
| Ganhos | <!-- n:collectors -->20<!-- /n --> coletores leem os saldos das suas contas nos provedores e mantêm um histórico | Estimativas a partir das faixas do catálogo, e não dados da conta ([código][m4b-earnings]) | Nada encontrado nos scripts | Nenhum | Nenhum | Nenhum |
| Pagamentos | Propõe um pagamento quando um saldo cai e o registra depois que você confirma ([schema][cp-payouts]) | Nenhum | Nenhum | Nenhum | Nenhum | Nenhum |
| Resgate de recompensas diárias | Não | Sim, sidecars ([README][m4b-features]) | Sim ([README][igm-features], [compose][igm-sidecars]) | Não | Não | Não |
| Credenciais em repouso | Criptografadas (Fernet) no banco de dados da UI ([notas](#cashpilot-notes)) | Criptografadas (Fernet); o arquivo de chave fica no diretório de dados ([código][m4b-crypto]) | Criptografadas (AES-256 com openssl); o arquivo de chave fica ao lado do cofre ([código][igm-encryptor]) | Texto puro em `properties.conf`; algumas senhas são passadas como argumentos do `docker run` ([script][ii-password-arg]) | Texto puro em `.env` ([arquivo][cf-env]) | Opções do add-on, armazenadas pelo Supervisor em `/data/options.json` ([documentação do HA][ha-options]) |
| Configurações dos contêineres dos apps de renda | Todas as capabilities removidas, `no-new-privileges`, um limite de pids; privilegiados recusados ([notas](#cashpilot-notes)) | `no-new-privileges` em todo serviço não privilegiado ([código][m4b-nnp]); o contêiner de proxy é privilegiado com `NET_ADMIN` ([template][m4b-tun]) | Nada definido nos serviços dos apps; o Mysterium recebe `NET_ADMIN` ([compose][igm-hosting-myst]); o contêiner de proxy recebe `NET_ADMIN`, com `no-new-privileges` e um limite de pids ([compose][igm-proxy]) | O Ebesucher roda com `seccomp=unconfined` ([script][ii-seccomp]); os contêineres de proxy e o Mysterium recebem `NET_ADMIN` | Nada definido | Nenhum add-on pede modo privilegiado, rede do host ou acesso à API do Docker ([exemplo de configuração][ha-config]) |
| Socket do Docker montado em | O socket proxy, somente leitura, e um contêiner de migração de execução única ([notas](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, que é somente leitura com `no-new-privileges` ([compose][igm-watchtower]) | Cinco contêineres auxiliares de reinicialização ([script][ii-sock-helper]) e o Watchtower ([script][ii-watchtower]) | Portainer, publicado nas portas 8000, 9000 e 9443 em todas as interfaces ([compose][cf-portainer]), e dois Watchtowers ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Nenhum |
| Tags de imagem | <!-- n:pinned -->9<!-- /n --> das <!-- n:docker -->21<!-- /n --> imagens de apps de renda fixadas em uma versão ou digest; as demais são móveis | As 15 imagens de apps usam `:latest` ([exemplo][m4b-image]); contêiner de proxy fixado na v2.6.0, Watchtower em `:1` | Sem tag, então o Docker usa `latest` ([compose][igm-hosting]); só há tag em alguns builds ARM | Quase sempre `:latest` ([exemplo][ii-seccomp]); EarnApp `:lite`, Honeygain fixado na 0.6.6 quando via proxy em amd64 ([script][ii-honeygain]), tags por arquitetura do Traffmonetizer em ARM; Watchtower `:nightly` | `:latest` ou sem tag, exceto EarnApp `:lite` ([compose][cf-compose]) | Uma versão por add-on, atualizada por um job diário de CI ([workflow][ha-bump], [exemplo][ha-dockerfile]) |
| Atualização das imagens dos apps | Baixadas de novo a cada implantação ou reimplantação; sem atualizador automático | Watchtower ([template][m4b-watchtower]) | Watchtower a cada 4 horas ([compose][igm-watchtower]) | Watchtower uma vez por dia, se você ativar ([script][ii-watchtower]) | Dois Watchtowers, cada um limitado a um app, PacketStream ([compose][cf-watchtower-ps]) e EarnFM ([compose][cf-watchtower-efm]); os outros 9 apps não são atualizados | Atualizações de add-ons do Home Assistant |
| Isolamento da LAN | Ativado por padrão em instalações novas ([isolamento](isolation.md#lan-isolation-by-default), [notas](#cashpilot-notes)) | Sub-rede de bridge própria ([config][m4b-subnet]), que não bloqueia a LAN | Nada mesclado | Nada encontrado | Nada encontrado | Nada encontrado |
| ARM | UI e worker arm64, com uma verificação de plataforma antes de cada implantação ([ARM](arm.md)) | Binários arm64 e armv7 ([versão][m4b-release]) | O README afirma amd64 e arm64, arm32 com limitações, e configura o QEMU ([README][igm-arch]) | Precisa de emulação binfmt para imagens só amd64 ([README][ii-arm]) | O README diz que não funciona em um Raspberry Pi ([README][cf-raspberry]) | Por add-on; o ProxyRack é só amd64 ([config][ha-proxyrack]) |
| UI | UI web, mais clientes Desktop, Android, MCP e Home Assistant | CLI, menus e um painel web local vinculado a 127.0.0.1 por padrão ([código][m4b-bind]) | CLI, menus e, segundo o README, uma UI web na porta 4747 acessível pela LAN ([README][igm-webui]) | Nenhuma, é um script | Uma página de favoritos na porta 80 mais o Portainer ([README][cf-ui]) | O painel de add-ons do Home Assistant |
| Versão mais recente | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Sem versões numeradas | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Chamadas de saída além dos apps | Verificação de atualizações, consulta do IP público, taxas de câmbio e saldos on-chain; fontes e Chart.js de CDNs ([notas](#cashpilot-notes)) | GitHub releases, para a verificação de atualização ([código][m4b-updater]); Docker Hub e ghcr.io, para verificar as tags de imagem ([código][m4b-registry]); quando você roda a verificação de IP, `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` para o seu IP público e `ip-api.com` por HTTP simples para as pontuações de IP ([código][m4b-ipscore]) | GitHub releases ([código][igm-version]); `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` para o seu IP público ([código][igm-ifconfig]); `ip-api.com` por HTTP simples para as pontuações de IP ([código][igm-ipscore]). O binário fechado não foi verificado | Nada encontrado | Nada encontrado | Nada encontrado |

### Notas sobre a coluna do CashPilot { #cashpilot-notes }

- **Vários proxies ou IPs.** Desde a v1.69.0, o CashPilot roda cópias extras de um serviço já implantado em um worker, cada uma pelo seu próprio proxy. SOCKS5 e HTTP CONNECT só transportam TCP: o túnel só deixa sair TCP para a porta do proxy, então os relays UDP do SOCKS5 são descartados. Um exit node do Tailscale também transporta UDP. O app de renda compartilha o namespace de rede de um contêiner de túnel ([código][cp-proxy-deploy]). Esse namespace só deixa sair o loopback, o túnel e a própria conexão do túnel com o proxy: TCP para o endereço e a porta dele, ou os pacotes marcados do tailscaled ([firewall do túnel][cp-tunnel-fw]). Assim, um proxy morto faz o app de renda parar em vez de vazar o tráfego dele ([como funciona](proxies.md#how-it-works)). Um serviço não pode rodar por um proxy quando precisa de rede do host, portas publicadas, volumes, dispositivos, uma GPU ou `NET_ADMIN`, `NET_RAW` ou `SYS_ADMIN`, ou quando os termos dele proíbem proxies. Por isso, <!-- n:noproxy -->10<!-- /n --> dos <!-- n:docker -->21<!-- /n --> apps de renda só ganham a partir do IP do próprio servidor ([o que não pode](proxies.md#what-cannot-run-through-a-proxy)).
- **Ganhos.** Alguns coletores precisam de um cookie ou token copiado do seu navegador, e alguns desses expiram. O guia de cada serviço diz quais.
- **Credenciais em repouso.** A UI guarda o arquivo da chave de criptografia no mesmo volume de dados que o banco de dados ([código][cp-fernet]). As credenciais dos apps de renda chegam a cada worker como variáveis de ambiente do contêiner, então ficam em texto puro na configuração do Docker desse worker (`docker inspect`).
- **Configurações dos contêineres dos apps de renda.** O worker remove todas as capabilities e depois adiciona de volta as que o catálogo lista para o serviço. Ele define `no-new-privileges` e um limite de pids, e recusa contêineres privilegiados ([código][cp-hardening], [código][cp-privileged], [padrões de segurança](security-defaults.md)). O Mysterium roda no próprio namespace de rede, na bridge atrás da barreira, com `NET_ADMIN`, `SETUID` e `SETGID`, em uma imagem fixada por digest ([catálogo][cp-myst]). Um runtime gVisor opcional pode adicionar um kernel em espaço de usuário ([runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Socket do Docker.** Desde a v1.71.0, o worker não tem socket. O socket proxy fica com ele: sockguard 2.4.7, fixado por digest, somente leitura ([compose][cp-sock]). O worker recebe uma cópia filtrada que recusa contêineres privilegiados, binds de `/` ou do socket, e capabilities ou dispositivos fora dos do catálogo ([socket proxy](security-defaults.md#docker-socket-proxy)). O contêiner de execução única `cashpilot-migrate` também monta o socket. Ele dá o rótulo de dono aos volumes e à rede da barreira que versões anteriores criaram e recria os contêineres delas sobre eles, para que o isolamento por dono do proxy os cubra. Ele termina antes de o proxy iniciar ([compose][cp-migrate]). Um app de renda nunca recebe o socket ([código][cp-mounts]). O proxy ainda não é uma fronteira de root. Com `CASHPILOT_COMPOSE_DIR` ou `CASHPILOT_PROXY_BIND_MOUNTS` definido, um worker comprometido pode colocar um symlink em uma pasta permitida com um contêiner e alcançar o `/` do host com um segundo ([detalhes](security-defaults.md#docker-socket-proxy)). As listagens do Unraid e do TrueNAS ainda montam o socket bruto no worker ([lojas de apps](app-stores.md)).
- **Isolamento da LAN.** Ativado por padrão desde a v1.70.0, em instalações novas e em instalações atualizadas sem nenhum app de renda na bridge padrão do Docker. O worker coloca os apps de renda na própria bridge e grava uma tabela de firewall para ela ([código][cp-fence]). A tabela descarta as faixas privadas, a faixa da tailnet, os metadados da nuvem, as sub-redes conectadas ao host e o próprio host. Com a detecção de IP público ativada, ela também descarta o IP público da casa ([isolamento](isolation.md#lan-isolation-by-default)). Uma instalação atualizada cujos apps de renda já estão na bridge padrão fica lá até você clicar em **Turn on isolation** (Ativar o isolamento). `CASHPILOT_ISOLATION=off` o desativa. Com `CASHPILOT_CONTAINER_NETWORK` definido, o CashPilot não grava nenhuma barreira para essa rede, e as regras de firewall ficam por sua conta. No Podman não há barreira, e a página da frota avisa isso ([modos](isolation.md#modes), [código][cp-fence-mode]). Desde a 2.0.7, o Mysterium também fica atrás da barreira. Um nó implantado até a 2.0.6 fica na rede do host até você reimplantá-lo ([Mysterium atrás da barreira](mysterium-fence.md)). Uma verificação mostra o que os apps de renda conseguem alcançar ([verificação](isolation-check.md)).
- **Chamadas de saída.** Além dos próprios apps, o CashPilot chama:
    - GitHub releases, uma vez por dia, para a verificação de atualizações (`CASHPILOT_UPDATE_CHECK=off` desativa, [código][cp-update]).
    - `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` uma vez por hora a partir de cada worker, para o IP público dele (`CASHPILOT_EGRESS_DETECT=off` desativa, [código][cp-egress]).
    - CoinGecko e Frankfurter, para as taxas de câmbio ([código][cp-rates]).
    - mempool.space, api.kaspa.org e nós RPC públicos de Ethereum, Ethereum Classic, Polygon e Solana, para os [saldos on-chain](onchain.md).
    - iptoasn.com, para a tabela de nomes de rede do CashPilot, no máximo uma vez por semana e só enquanto um worker estiver com a [atividade](activity.md#network-names-and-countries) ativada ([código][cp-ipgeo]).
    - cada provedor, para os coletores.

    O navegador carrega o Google Fonts ([template][cp-cdn]) e o Chart.js do jsDelivr ([template][cp-chartjs]).

Nenhum dos projetos envia telemetria de uso no código que lemos. O binário fechado do IGM não pôde ser lido.

Todos os projetos aqui passam as credenciais dos apps aos contêineres como variáveis de ambiente, e o InternetIncome também passa algumas como argumentos de comando, então, no host que roda os apps, elas ficam em texto puro na configuração dos contêineres do Docker (`Env` e `Args` no `docker inspect`), legíveis por qualquer pessoa com acesso ao Docker. A linha "Credenciais em repouso" descreve apenas a cópia armazenada.

## Como contamos { #how-we-counted }

- **CashPilot.** Serviços do catálogo com status active ou beta e uma imagem Docker, sem contar computação com GPU nem pools de mineração. O número desta página vem de `scripts/generate_readme_tables.py`, e o CI falha se ele divergir.
- **money4band 5.0.0.** Um arquivo JSON por app em `config/catalog/supported/`: 15. Os "35 apps" do README também contam o catálogo da comunidade, que vem desativado por padrão ([config][m4b-community]), apps sem imagem Docker e apps abandonados.
- **IGM.** Entradas em `apps.json`: 20, todas ativadas. O contêiner de proxy, o Watchtower e os sidecars de resgate não entram na conta.
- **InternetIncome.** Cada bloco de comentário `# Starting ... container` em `internetIncome.sh`, exceto os blocos do proxy e do Watchtower: 24. Os blocos de Chrome e Firefox do Ebesucher são um único app, assim como EarnFM e EarnFM Fleetshare, que usam a mesma conta EarnFM. O bloco das extensões DePIN inicia Grass e Gradient ([script][ii-depin]), dois apps. Total: 23. A tabela do README lista 27 apps, alguns só com um link de cadastro.
- **CashFactory.** Serviços de renda em `docker-compose.yml`: 11. O Portainer, o servidor web e os dois Watchtowers não entram na conta. Um serviço está comentado.
- **Add-ons do HA.** Pastas de add-on com um arquivo de configuração: 10.

Não verificamos se cada app de cada lista ainda paga.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
