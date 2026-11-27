---
source_hash: 915470497dbc
---
# Perguntas frequentes { #faq }

**Compartilhar largura de banda é seguro?**

Os serviços de compartilhamento de largura de banda geralmente encaminham tráfego legítimo (pesquisa de mercado, verificação de anúncios, comparação de preços, entrega de conteúdo) pela sua conexão. Ainda assim, você está compartilhando o seu endereço IP, então leia com atenção os termos de serviço e a política de privacidade de cada serviço antes de se cadastrar. Rodar esses serviços em uma VPS em vez de um IP residencial é uma opção para alguns deles. **Isto não é aconselhamento jurídico -- consulte os serviços específicos que você pretende usar e, se necessário, procure um advogado independente sobre a legislação do seu país.**

**Quanto posso ganhar?**

Os ganhos variam muito conforme a localização, o provedor de internet, o número de dispositivos e os serviços que você roda. O painel acompanha os seus ganhos reais ao longo do tempo para que você possa otimizar a sua configuração. Como referência aproximada, e não como promessa, um servidor doméstico rodando de 10 a 15 serviços rende cerca de $30 a $100 por mês, e pode render menos, até zero. Mais servidores, ou computação com GPU, somam a isso.

**Posso rodar em uma VPS ou servidor na nuvem?**

Alguns serviços exigem um IP residencial e não pagam (ou banem) IPs de VPS/datacenter. O catálogo lista "IP residencial" entre o que eles exigem. Os serviços que funcionam em VPS são uma boa forma de crescer sem hardware adicional em casa.

**Como as credenciais são armazenadas?**

Todas as credenciais dos serviços são criptografadas em repouso no banco de dados SQLite com uma chave Fernet armazenada em `/data/.fernet_key`, que é gerada automaticamente na primeira execução. O arquivo do banco de dados fica no volume Docker montado (`cashpilot_data:/data`). Nenhuma credencial é enviada a lugar nenhum, exceto aos próprios contêineres dos serviços.

Observe que essa é uma chave diferente de `CASHPILOT_SECRET_KEY`, que apenas assina as sessões de login.

### Fazer backup da chave de criptografia { #backing-up-the-encryption-key }

As suas credenciais só podem ser recuperadas enquanto existir o `/data/.fernet_key`. Se você perder esse arquivo, vai ter que digitar de novo todas as credenciais, porque não há como descriptografar os valores armazenados sem ele.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

O arquivo sempre tem precedência sobre a variável de ambiente, então definir `CASHPILOT_ENCRYPTION_KEY` em uma instância que já tem uma chave não muda nada e é seguro. Ela só é adotada quando não existe nenhum arquivo de chave, que é exatamente o caso da restauração.

Se o CashPilot não conseguir gravar a chave no disco de forma alguma, porque `/data` não permite escrita ou não está montado, ele se recusa a iniciar em vez de criptografar as suas credenciais com uma chave que desaparece na próxima reinicialização. Defina `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` se for isso mesmo que você quer.

<a id="forgot-password"></a>

### Esqueci a senha ou o nome de usuário { #forgot-password-or-username }

O CashPilot não tem redefinição por e-mail. Quem administra o servidor redefine a senha pelo console do contêiner da UI do CashPilot. Os seus serviços, ganhos e credenciais salvas não são afetados: eles são criptografados com `/data/.fernet_key`, e não com a sua senha.

O comando `python -m app.users` precisa do CashPilot 2.3 ou mais recente. Na 2.2 ou anterior, ele falha com `No module named app.users`. Atualize antes: com o Docker Compose, mude as tags `drumsergio/cashpilot` e `drumsergio/cashpilot-worker` para `2.3` ou mais recente (uma fixação como `2.2` ou `2.2.9` fica nessa versão) e depois rode `docker compose up -d` ([Atualizar o CashPilot](getting-started.md#updating-cashpilot)). No Unraid, atualize o contêiner.

1. Liste as contas. Isso também mostra um nome de usuário que você esqueceu. Os nomes de usuário diferenciam maiúsculas de minúsculas.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Defina uma nova senha aleatória para a conta. Substitua `alice` pelo nome de usuário do passo 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Com exatamente um proprietário, você pode omitir o nome de usuário, e o comando redefine esse proprietário. Se o nome de usuário começar com `-`, coloque `--` antes dele: `reset-password -- -alice`.

    O comando imprime a nova senha uma única vez.

3. Se outra pessoa pode ter tido acesso à conta, reinicie agora o contêiner da UI (`docker restart cashpilot-ui`). Os navegadores que ainda estavam conectados como esse usuário só são desconectados depois de uma reinicialização. Se você só esqueceu a senha, a reinicialização é opcional.
4. Entre com a nova senha e depois altere-a pelo menu do avatar (canto superior direito), **Change password** (Alterar senha).

O nome do contêiner depende de como você instalou o CashPilot:

| Instalação | Contêiner da UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | um nome gerado; `docker ps` o mostra |

Portainer, Unraid e CasaOS também têm um botão de console para cada contêiner. O comando não precisa de entrada no terminal, então funciona lá também.

Para mudar um nome de usuário:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

O novo nome segue a regra do cadastro: de 3 a 32 letras, dígitos, `_` ou `-`. Saia e entre de novo para vê-lo.

**Depois de um possível comprometimento**, por exemplo um backup perdido que contém `/data/.secret_key`, só redefinir a senha não basta. Quem tem essa chave consegue assinar um cookie de login válido, e uma redefinição não impede isso. Substitua a chave e depois reinicie o contêiner da UI. O `&&` só reinicia quando a nova chave está no lugar; se o comando imprimir um erro, corrija isso primeiro:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Depois da reinicialização, todos os navegadores são desconectados, e todo mundo entra de novo com a própria senha. As credenciais salvas não são afetadas. Se você mesmo definiu `CASHPILOT_SECRET_KEY`, o comando se recusa: coloque um novo valor aleatório nessa variável e recrie o contêiner. Um `docker run` a partir da imagem não vê essa variável e não consegue recusar, então use `docker exec` no contêiner da UI.

Uma chave nova acaba com os cookies forjados, mas não com o que o invasor fez enquanto estava dentro. Mais dois passos:

1. Rode `docker exec cashpilot-ui python -m app.users list`. Apague pelo painel qualquer conta que você não reconheça.
2. Se a cópia perdida continha todo o `/data`, mude as senhas das suas contas nos provedores. `.fernet_key` e `cashpilot.db` juntos descriptografam todas as credenciais salvas.

Se mais tarde você restaurar um backup feito antes da rotação, deixe de fora o `.secret_key` dele ([Backup e restauração](backup-restore.md#restore)), ou faça a rotação e reinicie de novo. Caso contrário, a chave antiga volta. O banco de dados restaurado também traz de volta as contas e senhas que continha, então repita a verificação das contas e qualquer redefinição de senha.

**Se o contêiner da UI não iniciar**, rode o comando a partir da mesma imagem, sobre os mesmos dados. Primeiro encontre a pasta do host que contém o `/data` da UI. Isso funciona com um contêiner parado, e tanto com um volume nomeado quanto com um bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Depois monte essa pasta e use a tag de imagem que você roda:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Confira se a lista mostra as suas contas e depois rode a mesma linha com `reset-password alice` no lugar de `list`.

Um caminho sem banco de dados gera um erro "no database", e o comando não cria nem altera nada ali. Mesmo assim, o Docker pode deixar para trás uma pasta ou um volume vazio com esse nome; remova-o.

**Não** apague o volume de dados: isso apaga `/data/.fernet_key` e, com ele, todas as credenciais salvas. **Também não** apague linhas da tabela `users`.

**Como removo o CashPilot por completo?**

`docker compose down -v` remove apenas os contêineres do próprio CashPilot. Os serviços que ele implantou continuam rodando, e os dados deles, a rede isolada pela barreira e uma tabela de firewall ficam. [Remover o CashPilot por completo](uninstall.md) remove tudo isso, diz o que se perde para sempre e mostra como verificar que nada ficou para trás.

**E a segurança?**

Cada serviço que o CashPilot implanta roda no próprio contêiner, com todas as capabilities do Linux removidas (alguns serviços adicionam de volta apenas as que declaram) e com `--security-opt no-new-privileges` definido, então um processo lá dentro não consegue ganhar privilégios. Os contêineres não enxergam o sistema de arquivos do host além dos volumes que um serviço declara. Em uma instalação nova, o worker também os isola atrás de uma barreira, longe da sua LAN, do host, da sua tailnet e dos metadados da nuvem, então eles alcançam a internet e nada local ([Isolamento de rede](isolation.md)). No Podman a barreira não está disponível: os apps de renda rodam na rede padrão do Podman, que alcança a sua LAN, e a página **Fleet** (Frota) avisa isso ([Isolamento de rede](isolation.md) lista as opções). Uma instalação atualizada a partir de uma versão anterior à 1.70 mantém os apps de renda na bridge padrão do Docker, que alcança a sua LAN, até você clicar em **Turn on isolation** (Ativar o isolamento) na página **Fleet** (Frota). Desde a 2.0.7, o Mysterium também roda atrás da barreira; um nó implantado até a 2.0.6 fica na rede do host até você reimplantá-lo ([Mover o seu nó Mysterium para trás da barreira](mysterium-fence.md)). [Proteger a sua rede doméstica](home-network-security.md) explica como aplicar um firewall à sua própria bridge como alternativa. As credenciais dos serviços são criptografadas em repouso com criptografia simétrica Fernet. A UI não tem acesso ao Docker. Com os arquivos compose distribuídos, o worker nunca recebe o socket bruto do Docker: ele alcança o Docker pelo `cashpilot-socket-proxy`, que recusa contêineres privilegiados e binds de `/` ou do socket (a menos que você coloque um deles, ou uma pasta acima do socket, em `CASHPILOT_PROXY_BIND_MOUNTS` ou `CASHPILOT_COMPOSE_DIR`: o proxy aceita esses como estão), e limita o worker a contêineres, volumes e redes com o rótulo de proprietário dele ([padrões de segurança](security-defaults.md)). Os templates do Unraid e o app do TrueNAS ainda montam o socket bruto no worker, o que equivale a root no host ([lojas de apps](app-stores.md)).

Dito isso, nenhuma configuração é à prova de falhas. Você continua rodando software de terceiros que encaminha tráfego externo pela sua rede. O isolamento do Docker reduz bastante a superfície de ataque em comparação com rodar esses serviços diretamente no host, mas não elimina todo o risco. Recomendamos rodar o CashPilot em uma máquina ou VLAN dedicada, manter o Docker e o sistema operacional do host atualizados e revisar o código aberto de qualquer serviço antes de implantá-lo.

**O que acontece se o contêiner de um serviço travar?**

O CashPilot monitora a saúde dos contêineres o tempo todo. Se o contêiner de um serviço encerrar inesperadamente, ele é reiniciado automaticamente. O painel mostra o tempo de atividade e o status de saúde de cada serviço em execução.

**O meu nó Mysterium não inicia depois de uma reimplantação. Por quê?**

A causa mais comum é uma porta da faixa UDP dele que outro programa do host já ocupa. O Docker precisa reservar todas as portas da faixa, então uma única porta ocupada impede a inicialização. [Escolher a faixa de portas UDP](mysterium-fence.md#choosing-the-udp-port-range) explica como escolher uma faixa que fique livre.

**A minha cópia via proxy está rodando, mas não ganha nada. Por quê?**

O proxy pode se recusar a conectar aos servidores desse app de renda, ou permitir apenas as portas 80 e 443. O **Test** (Testar) do CashPilot verifica apenas se o proxy alcança a internet. [Testar os servidores de um app de renda pelo proxy](proxies.md#probe-an-earners-servers-through-the-proxy) mostra como verificar o host e a porta do próprio app de renda.

**Quais serviços são pesados, e onde eles devem rodar?**

Nós de armazenamento, relays e saídas de VPN, e trabalho com GPU são os que mais consomem. [Planejar uma máquina pequena](fleet.md#budgeting-a-small-box) os lista e mostra como medir cada contêiner antes de decidir.

<a id="worker-lost-docker"></a>

### O worker perdeu o Docker depois de uma atualização do Docker { #the-worker-lost-docker-after-a-docker-update }

**O que você vê.** O worker continua online na página **Fleet** (Frota), mas o CashPilot não consegue iniciar, parar nem atualizar os contêineres dele. A página **Fleet** (Frota) mostra **Docker unreachable** (Docker inacessível) ao lado do worker. Depois de 10 minutos, o healthcheck do worker falha (`docker ps` mostra o worker como `unhealthy`). Depois de 30 minutos, o sino e as suas notificações avisam que o worker não consegue alcançar o Docker. `docker logs cashpilot-socket-proxy` mostra `upstream Docker socket unreachable` e, com um arquivo compose atual, `docker ps` mostra o proxy como `unhealthy` em cerca de 3 minutos. Os seus apps de renda continuam rodando.

**Causa.** Os arquivos compose distribuídos fazem bind do arquivo de socket `/var/run/docker.sock` no `cashpilot-socket-proxy`. Um bind de arquivo prende aquele arquivo específico. Uma atualização do Docker (por exemplo, o `unattended-upgrades` instalando um novo `docker-ce`) reinicia o Docker, e o Docker cria um novo arquivo de socket no mesmo caminho. Com o live-restore do Docker ativado, o proxy continua rodando durante essa reinicialização e fica com o arquivo antigo. Nada responde no arquivo antigo.

**Correção rápida.** Nessa máquina, reinicie o proxy:

```bash
docker restart cashpilot-socket-proxy
```

A reinicialização faz bind do novo socket, e o worker encontra o Docker de novo no próximo sinal de vida. Você não precisa reiniciar o worker. No Unraid e no TrueNAS, o próprio worker segura o socket, então reinicie o worker.

**Correção definitiva.** Faça bind da pasta do socket, e não do arquivo do socket. Um bind de pasta mostra na hora um socket substituído. No serviço `cashpilot-socket-proxy` do seu arquivo compose, substitua a linha `- /var/run/docker.sock:/var/run/docker.sock:ro` pelo bind abaixo e adicione a linha `SOCKGUARD_UPSTREAM_SOCKET` ao `environment` dele:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Depois rode `docker compose up -d`. A mesma mudança funciona em `docker-compose.worker.yml` e `docker-compose.fleet.yml`. O Compose só lê esses arquivos quando você os nomeia, então rode `docker compose -f docker-compose.worker.yml up -d` ou `docker compose -f docker-compose.fleet.yml up -d`, a menos que `COMPOSE_FILE` já nomeie o arquivo.

- `recursive: disabled` é necessário. `/var/run` contém outras montagens, por exemplo os namespaces de rede do Docker em `/run/docker/netns` e `/run/user/...`. Um bind recursivo leva todas elas para dentro do proxy. Um bind não recursivo mostra só a própria pasta.
- `SOCKGUARD_UPSTREAM_SOCKET` aponta o proxy para o novo caminho. O bloco de política e a impressão digital dele ficam como estão, porque a variável de ambiente sobrepõe `upstream.socket` na política. Sem a variável, o proxy não inicia (`upstream socket not found (/var/run/docker.sock)`).
- O `cashpilot-migrate` pode manter o bind de arquivo. Ele inicia de novo a cada `docker compose up`, então sempre recebe o socket atual. Se você der a ele o mesmo bind de pasta, adicione `DOCKER_HOST=unix:///host-run/docker.sock` ao `environment` dele. O worker 2.8.4 e posteriores leem essa variável. Nunca a aponte para o socket do proxy: o migrador precisa do socket do próprio host.
- O bind de pasta dá ao proxy todos os sockets em `/var/run`, e não só o do Docker. Em um servidor típico, isso inclui o socket do próprio systemd, o D-Bus e os sockets de ferramentas como Tailscale ou snapd. `read_only` não impede um programa de se conectar a um socket, e o proxy roda como root. O acesso ao socket do Docker já dá root no host, então um proxy comprometido ganha pouco que já não tivesse. Se você quiser que o proxy segure apenas o socket do Docker, mantenha o bind de arquivo e reinicie o proxy depois de cada atualização do Docker: o alerta acima avisa quando.
- É preciso o Docker Compose 2.30.0 ou mais recente. As versões mais antigas recusam o arquivo inteiro com `Additional property recursive is not allowed`. Rode `docker compose version` para verificar. O Debian 13 empacota o Compose 2.26.1, então no Debian instale o Compose pelo repositório do próprio Docker. A atualização pelo app usa o próprio Compose 2.33, então lê o arquivo alterado.
- Funciona só no Linux. O Docker Desktop no macOS e no Windows mapeia apenas `/var/run/docker.sock` para dentro da máquina virtual dele. Lá, `/var/run` é uma pasta no seu Mac ou PC, sem nenhum socket do Docker dentro.
- Com o Docker rootless, o socket fica em `/run/user/<your uid>`, que é uma montagem separada. Use essa pasta como `source`.
- No Podman, mantenha o bind de arquivo. Ainda não testamos o bind de pasta lá.

Os arquivos distribuídos mantêm o bind de arquivo, porque o bind de pasta exige o Compose 2.30 e Linux, e o CashPilot também oferece suporte a versões mais antigas do Compose e ao Docker Desktop. Um arquivo compose mais novo que você baixar não terá a sua mudança, então refaça-a depois de substituir o arquivo.
