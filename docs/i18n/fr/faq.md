---
source_hash: 915470497dbc
---
# FAQ { #faq }

**Le partage de bande passante est-il sûr ?**

Les services de partage de bande passante font généralement passer par votre connexion un trafic légitime (études de marché, vérification publicitaire, comparaison de prix, diffusion de contenu). Cela dit, vous partagez votre adresse IP, donc lisez attentivement les conditions d'utilisation et la politique de confidentialité de chaque service avant de vous inscrire. Pour certains services, il est possible de les faire tourner sur un VPS plutôt que sur une IP résidentielle. **Ceci n'est pas un conseil juridique : renseignez-vous auprès des services que vous comptez utiliser et, si nécessaire, consultez un conseiller juridique indépendant au sujet de votre juridiction.**

**Combien puis-je gagner ?**

Les gains varient beaucoup selon le lieu, le fournisseur d'accès, le nombre d'appareils et les services que vous faites tourner. Le tableau de bord suit vos gains réels dans le temps pour que vous puissiez optimiser votre installation. À titre indicatif, et sans aucune promesse, un serveur domestique qui fait tourner 10 à 15 services rapporte environ 30 à 100 $ par mois, et il peut rapporter moins, jusqu'à zéro. Davantage de serveurs, ou du calcul GPU, s'y ajoutent.

**Puis-je l'exécuter sur un VPS ou un serveur cloud ?**

Certains services exigent une IP résidentielle et ne paieront pas (ou banniront) les IP de VPS ou de centre de données. Le catalogue indique « IP résidentielle » dans ce dont ils ont besoin. Les services qui fonctionnent sur un VPS sont un bon moyen de monter en charge sans matériel supplémentaire à la maison.

**Comment les identifiants sont-ils stockés ?**

Tous les identifiants des services sont chiffrés au repos dans la base SQLite avec une clé Fernet stockée dans `/data/.fernet_key`, générée automatiquement au premier lancement. Le fichier de base de données se trouve dans le volume Docker monté (`cashpilot_data:/data`). Aucun identifiant n'est jamais envoyé ailleurs qu'aux conteneurs des services eux-mêmes.

Notez qu'il s'agit d'une clé différente de `CASHPILOT_SECRET_KEY`, qui ne signe que les sessions de connexion.

### Sauvegarder la clé de chiffrement { #backing-up-the-encryption-key }

Vos identifiants ne sont récupérables que si `/data/.fernet_key` l'est. Si vous perdez ce fichier, vous devrez saisir à nouveau chaque identifiant, car il n'existe aucun moyen de déchiffrer les valeurs stockées sans lui.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Le fichier a toujours la priorité sur la variable d'environnement, donc définir `CASHPILOT_ENCRYPTION_KEY` sur une instance qui a déjà une clé ne change rien et ne présente aucun risque. Elle n'est adoptée que lorsqu'aucun fichier de clé n'existe, ce qui correspond exactement au cas d'une restauration.

Si CashPilot ne peut pas du tout écrire la clé sur le disque, parce que `/data` n'est pas accessible en écriture ou n'est pas monté, il refuse de démarrer plutôt que de chiffrer vos identifiants avec une clé qui disparaîtrait au prochain redémarrage. Définissez `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` si c'est vraiment ce que vous voulez.

<a id="forgot-password"></a>

### Mot de passe ou nom d'utilisateur oublié { #forgot-password-or-username }

CashPilot n'a pas de réinitialisation par e-mail. La personne qui gère le serveur réinitialise le mot de passe depuis la console du conteneur de l'interface de CashPilot. Vos services, vos gains et vos identifiants enregistrés ne sont pas touchés : ils sont chiffrés avec `/data/.fernet_key`, pas avec votre mot de passe.

La commande `python -m app.users` nécessite CashPilot 2.3 ou plus récent. Sur la 2.2 ou une version antérieure, elle échoue avec `No module named app.users`. Mettez d'abord à jour : avec Docker Compose, changez les tags `drumsergio/cashpilot` et `drumsergio/cashpilot-worker` en `2.3` ou plus récent (un épinglage comme `2.2` ou `2.2.9` reste sur cette version), puis exécutez `docker compose up -d` ([Mettre à jour CashPilot](getting-started.md#updating-cashpilot)). Sur Unraid, mettez à jour le conteneur.

1. Listez les comptes. Cela affiche aussi un nom d'utilisateur oublié. Les noms d'utilisateur sont sensibles à la casse.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Définissez un nouveau mot de passe aléatoire pour le compte. Remplacez `alice` par le nom d'utilisateur de l'étape 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    S'il n'y a qu'un seul propriétaire, vous pouvez omettre le nom d'utilisateur, et la commande réinitialise ce propriétaire. Si le nom d'utilisateur commence par `-`, mettez `--` devant : `reset-password -- -alice`.

    La commande affiche le nouveau mot de passe une seule fois.

3. Si quelqu'un d'autre a pu avoir accès au compte, redémarrez maintenant le conteneur de l'interface (`docker restart cashpilot-ui`). Les navigateurs encore connectés avec cet utilisateur ne sont déconnectés qu'après un redémarrage. Si vous avez seulement oublié le mot de passe, le redémarrage est facultatif.
4. Connectez-vous avec le nouveau mot de passe, puis changez-le depuis le menu de l'avatar (en haut à droite), **Change password** (Changer le mot de passe).

Le nom du conteneur dépend de la façon dont vous avez installé CashPilot :

| Installation | Conteneur de l'interface |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | un nom généré ; `docker ps` l'affiche |

Portainer, Unraid et CasaOS ont aussi un bouton de console pour un conteneur. La commande ne demande aucune saisie au terminal, elle fonctionne donc aussi à cet endroit.

Pour changer un nom d'utilisateur :

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Le nouveau nom suit la règle d'inscription : 3 à 32 lettres, chiffres, `_` ou `-`. Déconnectez-vous puis reconnectez-vous pour le voir.

**Après une compromission présumée**, par exemple une sauvegarde perdue qui contient `/data/.secret_key`, une réinitialisation du mot de passe ne suffit pas. Quiconque détient cette clé peut signer un cookie de connexion valide, et une réinitialisation ne l'en empêche pas. Remplacez la clé, puis redémarrez le conteneur de l'interface. Le `&&` ne le redémarre que lorsque la nouvelle clé est en place ; si la commande affiche une erreur, corrigez-la d'abord :

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Après le redémarrage, tous les navigateurs sont déconnectés et chacun se reconnecte avec son mot de passe. Les identifiants enregistrés ne sont pas touchés. Si vous avez défini `CASHPILOT_SECRET_KEY` vous-même, la commande refuse : mettez une nouvelle valeur aléatoire dans cette variable et recréez le conteneur à la place. Un `docker run` depuis l'image ne voit pas cette variable et ne peut pas refuser, donc utilisez `docker exec` sur le conteneur de l'interface.

Une nouvelle clé met fin aux cookies falsifiés, mais pas à ce que l'attaquant a fait pendant qu'il avait accès. Deux étapes de plus :

1. Exécutez `docker exec cashpilot-ui python -m app.users list`. Supprimez depuis le tableau de bord tout compte que vous ne reconnaissez pas.
2. Si la copie perdue contenait tout `/data`, changez les mots de passe de vos comptes chez les fournisseurs. `.fernet_key` et `cashpilot.db` ensemble déchiffrent chaque identifiant enregistré.

Si vous restaurez plus tard une sauvegarde faite avant la rotation, laissez de côté son `.secret_key` ([Sauvegarde et restauration](backup-restore.md#restore)), ou refaites une rotation et un redémarrage. Sinon, l'ancienne clé revient. La base de données restaurée ramène aussi les comptes et mots de passe qu'elle contenait, donc refaites la vérification des comptes et toute réinitialisation de mot de passe.

**Si le conteneur de l'interface ne démarre pas**, exécutez la commande depuis la même image sur les mêmes données. Trouvez d'abord le dossier de l'hôte qui contient le `/data` de l'interface. Cela fonctionne pour un conteneur arrêté, et pour un volume nommé comme pour un montage bind (Unraid, CasaOS, Runtipi) :

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Montez ensuite ce dossier et utilisez le tag d'image que vous exécutez :

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Vérifiez que la liste affiche vos comptes, puis exécutez la même ligne avec `reset-password alice` à la place de `list`.

Un chemin sans base de données renvoie une erreur « no database », et la commande n'y crée et n'y modifie rien. Docker peut quand même laisser derrière lui un dossier ou un volume vide portant ce nom ; supprimez-le.

**Ne supprimez pas** le volume de données : cela efface `/data/.fernet_key` et, avec elle, chaque identifiant enregistré. **Ne supprimez pas** non plus de lignes de la table `users`.

**Comment supprimer complètement CashPilot ?**

`docker compose down -v` ne supprime que les conteneurs propres à CashPilot. Les services qu'il a déployés continuent de tourner, et leurs données, le réseau protégé par la barrière et une table de pare-feu restent en place. [Supprimer complètement CashPilot](uninstall.md) supprime tout cela, indique ce qui est perdu pour de bon et montre comment vérifier qu'il ne reste rien.

**Et la sécurité ?**

Chaque service que CashPilot déploie tourne dans son propre conteneur, avec toutes les capacités Linux retirées (quelques services ne rajoutent que celles qu'ils déclarent) et `--security-opt no-new-privileges` défini, de sorte qu'un processus à l'intérieur ne peut pas obtenir de privilèges. Les conteneurs ne voient pas le système de fichiers de votre hôte au-delà des volumes qu'un service déclare. Sur une nouvelle installation, le worker les isole aussi derrière une barrière qui les coupe de votre réseau local, de l'hôte, de votre tailnet et des métadonnées cloud : ils atteignent internet et rien de local ([Isolement réseau](isolation.md)). Sur Podman, la barrière n'est pas disponible : les apps de gains tournent sur le réseau par défaut de Podman, qui peut atteindre votre réseau local, et la page **Fleet** (Parc) le signale ([Isolement réseau](isolation.md) liste les options). Une installation mise à jour depuis une version antérieure à 1.70 garde ses apps de gains sur le bridge par défaut de Docker, qui peut atteindre votre réseau local, jusqu'à ce que vous cliquiez sur **Turn on isolation** (Activer l'isolement) sur la page **Fleet** (Parc). Depuis la 2.0.7, Mysterium tourne aussi derrière la barrière ; un nœud déployé jusqu'à la 2.0.6 reste sur le réseau de l'hôte jusqu'à ce que vous le redéployiez ([Placer votre nœud Mysterium derrière la barrière](mysterium-fence.md)). [Protéger votre réseau domestique](home-network-security.md) explique plutôt comment protéger par pare-feu votre propre bridge. Les identifiants des services sont chiffrés au repos avec le chiffrement symétrique Fernet. L'interface n'a aucun accès à Docker. Avec les fichiers compose livrés, le worker ne reçoit jamais le socket Docker brut : il accède à Docker via `cashpilot-socket-proxy`, qui refuse les conteneurs privilégiés et les montages de `/` ou du socket (sauf si vous mettez l'un d'eux, ou un dossier au-dessus du socket, dans `CASHPILOT_PROXY_BIND_MOUNTS` ou `CASHPILOT_COMPOSE_DIR` : le proxy les accepte tels quels), et limite le worker aux conteneurs, volumes et réseaux qui portent son étiquette de propriétaire ([sécurité par défaut](security-defaults.md)). Les modèles Unraid et l'application TrueNAS montent encore le socket brut dans le worker, ce qui équivaut à root sur l'hôte ([boutiques d'applications](app-stores.md)).

Cela dit, aucune installation n'est infaillible. Vous exécutez toujours un logiciel tiers qui fait passer du trafic externe par votre réseau. L'isolation Docker réduit nettement la surface d'attaque par rapport à l'exécution directe de ces services sur votre hôte, mais elle n'élimine pas tous les risques. Nous recommandons d'exécuter CashPilot sur une machine ou un VLAN dédié, de tenir Docker et le système d'exploitation de votre hôte à jour, et d'examiner le code open source de chaque service avant de le déployer.

**Que se passe-t-il si le conteneur d'un service plante ?**

CashPilot surveille en continu la santé des conteneurs. Si le conteneur d'un service s'arrête de façon inattendue, il est redémarré automatiquement. Le tableau de bord affiche la disponibilité et l'état de santé de chaque service en cours d'exécution.

**Mon nœud Mysterium ne démarre plus après un redéploiement. Pourquoi ?**

La cause la plus fréquente est un port de sa plage UDP déjà occupé par un autre programme de l'hôte. Docker doit réserver chaque port de la plage, donc un seul port occupé empêche le démarrage. [Choisir la plage de ports UDP](mysterium-fence.md#choosing-the-udp-port-range) explique comment choisir une plage qui reste libre.

**Ma copie via proxy tourne mais ne gagne rien. Pourquoi ?**

Le proxy refuse peut-être de se connecter aux serveurs de cette app de gains, ou n'autorise que les ports 80 et 443. Le **Test** (Tester) de CashPilot vérifie seulement que le proxy atteint internet. [Sonder les serveurs d'une app de gains à travers le proxy](proxies.md#probe-an-earners-servers-through-the-proxy) montre comment vérifier l'hôte et le port propres à l'app de gains.

**Quels services sont gourmands, et où les faire tourner ?**

Les nœuds de stockage, les relais et sorties VPN, et le travail GPU consomment le plus. [Prévoir le budget d'une petite machine](fleet.md#budgeting-a-small-box) les liste et montre comment mesurer chaque conteneur avant de décider.

<a id="worker-lost-docker"></a>

### Le worker a perdu Docker après une mise à jour de Docker { #the-worker-lost-docker-after-a-docker-update }

**Ce que vous voyez.** Le worker reste en ligne sur la page **Fleet** (Parc), mais CashPilot ne peut pas démarrer, arrêter ni mettre à jour ses conteneurs. La page **Fleet** (Parc) affiche **Docker unreachable** (Docker injoignable) à côté du worker. Après 10 minutes, le contrôle de santé du worker échoue (`docker ps` affiche le worker comme `unhealthy`). Après 30 minutes, la cloche et vos notifications indiquent que le worker ne peut pas joindre Docker. `docker logs cashpilot-socket-proxy` affiche `upstream Docker socket unreachable`, et avec un fichier compose actuel, `docker ps` affiche le proxy comme `unhealthy` en 3 minutes environ. Vos apps de gains continuent de tourner.

**Cause.** Les fichiers compose livrés montent le fichier de socket `/var/run/docker.sock` dans `cashpilot-socket-proxy`. Un montage de fichier tient ce seul fichier. Une mise à jour de Docker (par exemple `unattended-upgrades` qui installe un nouveau `docker-ce`) redémarre Docker, et Docker crée un nouveau fichier de socket au même chemin. Avec le live-restore de Docker activé, le proxy continue de tourner pendant ce redémarrage et garde l'ancien fichier. Rien ne répond plus sur l'ancien fichier.

**Correctif rapide.** Sur cette machine, redémarrez le proxy :

```bash
docker restart cashpilot-socket-proxy
```

Le redémarrage monte le nouveau socket, et le worker retrouve Docker à son prochain signal de vie. Vous n'avez pas besoin de redémarrer le worker. Sur Unraid et TrueNAS, le worker détient lui-même le socket, donc redémarrez le worker.

**Correctif durable.** Montez le dossier du socket, pas le fichier du socket. Un montage de dossier fait apparaître immédiatement un socket remplacé. Dans le service `cashpilot-socket-proxy` de votre fichier compose, remplacez la ligne `- /var/run/docker.sock:/var/run/docker.sock:ro` par le montage ci-dessous, et ajoutez la ligne `SOCKGUARD_UPSTREAM_SOCKET` à son `environment` :

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

Exécutez ensuite `docker compose up -d`. La même modification fonctionne dans `docker-compose.worker.yml` et `docker-compose.fleet.yml`. Compose ne lit ces fichiers que si vous les nommez, donc exécutez `docker compose -f docker-compose.worker.yml up -d` ou `docker compose -f docker-compose.fleet.yml up -d`, sauf si `COMPOSE_FILE` nomme déjà le fichier.

- `recursive: disabled` est indispensable. `/var/run` contient d'autres montages, par exemple les espaces de noms réseau de Docker sous `/run/docker/netns` et `/run/user/...`. Un montage récursif les fait tous entrer dans le proxy. Un montage non récursif ne montre que le dossier lui-même.
- `SOCKGUARD_UPSTREAM_SOCKET` envoie le proxy vers le nouveau chemin. Le bloc de politique et son empreinte restent tels quels, car la variable d'environnement remplace `upstream.socket` dans la politique. Sans la variable, le proxy ne démarre pas (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` peut garder son montage de fichier. Il redémarre à chaque `docker compose up`, il obtient donc toujours le socket actuel. Si vous lui donnez le même montage de dossier, ajoutez `DOCKER_HOST=unix:///host-run/docker.sock` à son `environment`. Le worker 2.8.4 et les versions suivantes lisent cette variable. Ne la faites jamais pointer vers le socket du proxy : le migrateur a besoin de celui de l'hôte.
- Le montage de dossier donne au proxy tous les sockets de `/var/run`, pas seulement celui de Docker. Sur un serveur typique, cela inclut le socket de systemd lui-même, D-Bus, et les sockets d'outils comme Tailscale ou snapd. `read_only` n'empêche pas un programme de se connecter à un socket, et le proxy tourne en root. L'accès au socket Docker donne déjà root sur l'hôte, donc un proxy compromis gagne peu de choses qu'il n'avait pas déjà. Si vous voulez que le proxy ne détienne que le socket Docker, gardez le montage de fichier et redémarrez le proxy après une mise à jour de Docker : l'alerte ci-dessus vous indique quand.
- Il faut Docker Compose 2.30.0 ou plus récent. Les versions plus anciennes refusent tout le fichier avec `Additional property recursive is not allowed`. Exécutez `docker compose version` pour vérifier. Debian 13 fournit Compose 2.26.1, donc sur Debian, installez Compose depuis le dépôt de Docker lui-même. La mise à jour depuis l'application utilise son propre Compose 2.33, elle lit donc le fichier modifié.
- Cela ne fonctionne que sous Linux. Docker Desktop sur macOS et Windows ne fait correspondre que `/var/run/docker.sock` dans sa machine virtuelle. Là, `/var/run` est un dossier de votre Mac ou de votre PC, sans socket Docker dedans.
- Avec Docker rootless, le socket se trouve dans `/run/user/<your uid>`, qui est un montage séparé. Utilisez ce dossier comme `source`.
- Sur Podman, gardez le montage de fichier. Nous n'y avons pas testé le montage de dossier.

Les fichiers livrés gardent le montage de fichier, car le montage de dossier nécessite Compose 2.30 et Linux, et CashPilot prend aussi en charge des versions plus anciennes de Compose et Docker Desktop. Un fichier compose plus récent que vous téléchargez ne contient pas votre modification, donc refaites-la après avoir remplacé le fichier.
