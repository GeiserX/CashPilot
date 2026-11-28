---
source_hash: 06e0336d2a02
---
# CashPilot face aux autres outils { #how-cashpilot-compares }

Cette page compare CashPilot aux autres projets ouverts qui font tourner plusieurs apps de revenus passifs dans Docker. Nous avons vérifié chaque projet le 2026-11-04, et CashPilot à nouveau le 2026-11-28. Chaque cellule qui concerne un autre projet renvoie au fichier dont elle provient, à un commit fixe, pour que vous puissiez vérifier vous-même. Si une cellule est fausse ou dépassée, merci d'[ouvrir une issue](https://github.com/GeiserX/CashPilot/issues).

## Projets comparés { #projects-compared }

| Projet | Ce que nous avons vérifié | Étoiles au 2026-11-04 | Licence |
|---|---|---|---|
| [money4band][m4b-tree] | Version 5.0.0, commit du tag `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` à `65e900d` (2026-10-20), plus ce que le README affirme sur son binaire 3.0.0-beta.9 | 238 | Propriétaire, [licence propre v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` à `db9338a` (2026-11-03) | 257 | Pas de fichier LICENSE. Le [README][ii-license] autorise la copie de l'original et interdit de distribuer des copies modifiées |
| [CashFactory][cf-tree] | `main` à `0ff4bd0` (2025-04-08) | 410 | Le fichier [LICENSE][cf-license-file] est en GPL-3.0, mais le [README][cf-license] interdit de distribuer des copies modifiées |
| [home-assistant-passive-income][ha-tree] (modules complémentaires HA) | Version 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Version v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band a deux lignes de code. Sa branche par défaut `main` (`3bfafb1`) contient encore le code 4.x, et son dernier changement de code y date du 2026-03-03. La version 5.0.0 est construite à partir d'un historique séparé. Nous comparons la 5.0.0 parce que c'est ce que livre sa dernière version.

L'interface web d'IGM, sa gestion de parc et son binaire d'installation sont fermés et absents de son dépôt. Là où une cellule en dépend, elle indique « le README affirme » et renvoie à la ligne du README. Tout le reste de la colonne d'IGM provient des scripts shell et des fichiers compose du dépôt.

Laissés de côté : [earning-machine](https://github.com/jf-m/earning-machine) et [passiveMachine](https://github.com/Xpl0itU/passiveMachine) n'ont reçu aucun commit depuis 2024. Une recherche sur GitHub n'a rien trouvé d'autre de maintenu qui fasse tourner plus d'une app, seulement des images pour une seule app.

## En bref { #short-version }

- **InternetIncome, money4band, IGM et, depuis la v1.69.0, CashPilot peuvent gagner sur de nombreuses IP grâce à des proxys.** Les trois premiers exécutent chaque app une fois par proxy, et les proxys sont la fonction principale d'InternetIncome. CashPilot exécute des copies supplémentaires d'un service déjà déployé sur un worker, chacune via un proxy SOCKS5, HTTP CONNECT ou un exit node Tailscale ([copies via proxy](proxies.md)).
- **InternetIncome démarre 23 apps, IGM en démarre 20 et le worker de CashPilot en démarre <!-- n:docker -->21<!-- /n -->.** CashPilot suit davantage de services au total (<!-- n:live -->50<!-- /n -->), car il suit aussi des services d'extension de navigateur, de bureau et GPU qu'il n'exécute pas. Depuis la v1.64.0, il peut aussi exécuter n'importe quelle image que vous nommez comme [service personnalisé](custom-services.md).
- **money4band et IGM réclament les récompenses quotidiennes pour vous et tiennent les images des apps à jour avec Watchtower.** CashPilot ne fait ni l'un ni l'autre. Il ne télécharge à nouveau une image que lorsque vous déployez ou redéployez.
- **CashPilot est le seul ici à lire les soldes depuis vos comptes chez les fournisseurs et à garder un historique.** money4band 5.0.0 affiche des estimations tirées de son propre catalogue, pas de vos comptes. Les autres renvoient au tableau de bord de chaque fournisseur.
- **CashPilot est le seul projet open source ici avec une seule interface pour plusieurs serveurs.** Le README d'IGM affirme une gestion de parc, mais ce code se trouve dans son binaire fermé.
- **Depuis la v1.70.0, CashPilot est le seul ici à tenir par défaut les conteneurs des apps de gains à l'écart de votre réseau local, avec des limites.** C'est activé sur les nouvelles installations et sur les installations mises à jour sans app de gains sur le bridge par défaut de Docker. Une installation mise à jour dont les apps de gains sont déjà sur ce bridge les y garde jusqu'à ce que vous activiez l'isolement, et un réseau que vous nommez dans `CASHPILOT_CONTAINER_NETWORK` ne reçoit aucune barrière de CashPilot ([isolement](isolation.md#modes)). Depuis la 2.0.7, Mysterium tourne lui aussi derrière la barrière ; un nœud déployé jusqu'à la 2.0.6 reste sur le réseau de l'hôte, sans barrière, jusqu'à ce que vous le redéployiez ([Mysterium derrière la barrière](mysterium-fence.md)).

## Côte à côte { #side-by-side }

La colonne de CashPilot décrit la v3.0.1. Chacune de ses cellules est courte, et les [notes sous le tableau](#cashpilot-notes) donnent les détails et les liens vers le code. Les autres colonnes décrivent les commits du tableau ci-dessus.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Modules complémentaires HA |
|---|---|---|---|---|---|---|
| Apps qu'il peut démarrer (voir [notre méthode de comptage](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> exécutées par le worker, plus des [images personnalisées](custom-services.md) ; <!-- n:live -->50<!-- /n --> suivies au total | 15 ([catalogue][m4b-catalog]). Le README en annonce 35, ce qui [inclut][m4b-readme-35] des apps de la communauté et des apps abandonnées | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([fichier compose][cf-compose]) | 10 ([dossiers des modules][ha-tree]) |
| Mode d'installation | Docker Compose : une interface, plus un worker sur chaque serveur ([parc](fleet.md)) | CLI Python ou binaire précompilé qui écrit un fichier compose ([version][m4b-tree]) | Installateur `curl \| sh` ([README][igm-install]) qui télécharge un binaire fermé, vérifié seulement avec un fichier SHA256SUMS de la même version ([installateur][igm-installer-sums]) | Un seul script bash de 1 608 lignes qui appelle `sudo docker run` ([script][ii-script]) | Un fichier compose statique plus `setup.sh` exécuté avec sudo ([setup][cf-setup]) | Un dépôt de modules complémentaires Home Assistant ; nécessite Home Assistant OS ou Supervised |
| Plusieurs serveurs, une seule vue | Oui ([parc](fleet.md)) | Non, une stack par appareil | Le README affirme que oui, dans le binaire fermé ([README][igm-features]) | Non | Non | Non |
| Plusieurs proxys ou IP | Oui, via des proxys SOCKS5, HTTP CONNECT ou des exit nodes Tailscale ([copies via proxy](proxies.md), [notes](#cashpilot-notes)) | Oui ([README][m4b-features], [code][m4b-multiproxy]) | Oui ([README][igm-features], [compose][igm-proxy]) | Oui, c'est sa fonction principale ([README][ii-readme-top]) | Non | Non |
| Gains | <!-- n:collectors -->20<!-- /n --> collecteurs lisent les soldes depuis vos comptes chez les fournisseurs et gardent un historique | Estimations tirées des fourchettes du catalogue, pas des données du compte ([code][m4b-earnings]) | Rien trouvé dans les scripts | Aucun | Aucun | Aucun |
| Paiements | Propose un paiement quand un solde baisse, et l'enregistre une fois que vous confirmez ([schéma][cp-payouts]) | Aucun | Aucun | Aucun | Aucun | Aucun |
| Réclamation des récompenses quotidiennes | Non | Oui, conteneurs annexes ([README][m4b-features]) | Oui ([README][igm-features], [compose][igm-sidecars]) | Non | Non | Non |
| Identifiants au repos | Chiffrés (Fernet) dans la base de données de l'interface ([notes](#cashpilot-notes)) | Chiffrés (Fernet) ; le fichier de clé se trouve dans le répertoire des données ([code][m4b-crypto]) | Chiffrés (AES-256 avec openssl) ; le fichier de clé se trouve à côté du coffre ([code][igm-encryptor]) | En clair dans `properties.conf` ; certains mots de passe sont passés comme arguments de `docker run` ([script][ii-password-arg]) | En clair dans `.env` ([fichier][cf-env]) | Options du module, stockées par le Supervisor dans `/data/options.json` ([doc HA][ha-options]) |
| Réglages des conteneurs des apps de gains | Toutes les capacités retirées, `no-new-privileges`, une limite de pids ; mode privilégié refusé ([notes](#cashpilot-notes)) | `no-new-privileges` sur chaque service non privilégié ([code][m4b-nnp]) ; le conteneur proxy est privilégié avec `NET_ADMIN` ([modèle][m4b-tun]) | Rien de défini sur les services des apps ; Mysterium reçoit `NET_ADMIN` ([compose][igm-hosting-myst]) ; le conteneur proxy reçoit `NET_ADMIN`, avec `no-new-privileges` et une limite de pids ([compose][igm-proxy]) | Ebesucher tourne avec `seccomp=unconfined` ([script][ii-seccomp]) ; les conteneurs proxy et Mysterium reçoivent `NET_ADMIN` | Rien de défini | Aucun module ne demande le mode privilégié, le réseau hôte ou l'accès à l'API Docker ([exemple de configuration][ha-config]) |
| Socket Docker monté dans | Le proxy de socket, en lecture seule, et un conteneur de migration ponctuel ([notes](#cashpilot-notes)) | Watchtower ([modèle][m4b-watchtower]) | Watchtower, en lecture seule avec `no-new-privileges` ([compose][igm-watchtower]) | Cinq conteneurs d'aide au redémarrage ([script][ii-sock-helper]) et Watchtower ([script][ii-watchtower]) | Portainer, publié sur les ports 8000, 9000 et 9443 sur toutes les interfaces ([compose][cf-portainer]), et deux Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Aucun |
| Tags d'image | <!-- n:pinned -->9<!-- /n --> des <!-- n:docker -->21<!-- /n --> images d'apps de gains épinglées sur une version ou un digest ; les autres flottent | Les 15 images d'apps utilisent toutes `:latest` ([exemple][m4b-image]) ; conteneur proxy épinglé sur v2.6.0, Watchtower sur `:1` | Pas de tag, donc Docker utilise `latest` ([compose][igm-hosting]) ; un tag n'est défini que pour certaines builds ARM | Surtout `:latest` ([exemple][ii-seccomp]) ; EarnApp `:lite`, Honeygain épinglé sur 0.6.6 quand il passe par un proxy sur amd64 ([script][ii-honeygain]), Traffmonetizer avec des tags par architecture sur ARM ; Watchtower `:nightly` | `:latest` ou pas de tag, sauf EarnApp `:lite` ([compose][cf-compose]) | Une version par module, relevée par une tâche CI quotidienne ([workflow][ha-bump], [exemple][ha-dockerfile]) |
| Mises à jour des images des apps | Téléchargées à nouveau à chaque déploiement ou redéploiement ; pas d'outil de mise à jour automatique | Watchtower ([modèle][m4b-watchtower]) | Watchtower toutes les 4 heures ([compose][igm-watchtower]) | Watchtower une fois par jour, si vous l'activez ([script][ii-watchtower]) | Deux Watchtower, chacun limité à une app, PacketStream ([compose][cf-watchtower-ps]) et EarnFM ([compose][cf-watchtower-efm]) ; les 9 autres apps ne sont pas mises à jour | Les mises à jour des modules de Home Assistant |
| Isolement du réseau local | Activé par défaut sur les nouvelles installations ([isolement](isolation.md#lan-isolation-by-default), [notes](#cashpilot-notes)) | Sous-réseau de bridge propre ([configuration][m4b-subnet]), qui ne bloque pas le réseau local | Rien de fusionné | Rien trouvé | Rien trouvé | Rien trouvé |
| ARM | Interface et worker arm64, avec une vérification de plateforme avant chaque déploiement ([ARM](arm.md)) | Binaires arm64 et armv7 ([version][m4b-release]) | Le README affirme amd64 et arm64, arm32 avec des limites, et configure QEMU ([README][igm-arch]) | Nécessite l'émulation binfmt pour les images uniquement amd64 ([README][ii-arm]) | Le README indique qu'il ne fonctionne pas sur un Raspberry Pi ([README][cf-raspberry]) | Selon le module ; ProxyRack est uniquement amd64 ([configuration][ha-proxyrack]) |
| Interface | Interface web, plus des clients Desktop, Android, MCP et Home Assistant | CLI, menus et un tableau de bord web local lié à 127.0.0.1 par défaut ([code][m4b-bind]) | CLI, menus et, d'après le README, une interface web sur le port 4747 joignable depuis le réseau local ([README][igm-webui]) | Aucune, c'est un script | Une page de favoris sur le port 80 plus Portainer ([README][cf-ui]) | Le panneau des modules complémentaires de Home Assistant |
| Dernière version | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Pas de versions numérotées | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Appels sortants en dehors des apps | Vérification des mises à jour, détection de l'IP publique, taux de change et soldes on-chain ; polices et Chart.js depuis des CDN ([notes](#cashpilot-notes)) | Versions GitHub, pour sa vérification des mises à jour ([code][m4b-updater]) ; Docker Hub et ghcr.io, pour vérifier les tags d'image ([code][m4b-registry]) ; quand vous lancez la vérification d'IP, `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` pour votre IP publique et `ip-api.com` en HTTP non chiffré pour les scores d'IP ([code][m4b-ipscore]) | Versions GitHub ([code][igm-version]) ; `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` pour votre IP publique ([code][igm-ifconfig]) ; `ip-api.com` en HTTP non chiffré pour les scores d'IP ([code][igm-ipscore]). Le binaire fermé n'a pas été vérifié | Rien trouvé | Rien trouvé | Rien trouvé |

### Notes sur la colonne de CashPilot { #cashpilot-notes }

- **Plusieurs proxys ou IP.** Depuis la v1.69.0, CashPilot fait tourner des copies supplémentaires d'un service déjà déployé sur un worker, chacune via son propre proxy. SOCKS5 et HTTP CONNECT ne transportent que du TCP : le tunnel ne laisse sortir que du TCP vers le port du proxy, donc les relais UDP SOCKS5 sont abandonnés. Un exit node Tailscale transporte aussi l'UDP. L'app de gains partage l'espace de noms réseau d'un conteneur tunnel ([code][cp-proxy-deploy]). Cet espace de noms ne laisse sortir que la boucle locale, le tunnel et la connexion du tunnel lui-même vers le proxy : TCP vers son adresse et son port, ou les paquets marqués de tailscaled ([pare-feu du tunnel][cp-tunnel-fw]). Ainsi, un proxy mort arrête l'app de gains au lieu de laisser fuir son trafic ([fonctionnement](proxies.md#how-it-works)). Un service ne peut pas passer par un proxy quand il a besoin du réseau hôte, de ports publiés, de volumes, de périphériques, d'un GPU ou de `NET_ADMIN`, `NET_RAW` ou `SYS_ADMIN`, ou quand ses conditions interdisent les proxys. Donc <!-- n:noproxy -->10<!-- /n --> des <!-- n:docker -->21<!-- /n --> apps de gains ne gagnent que depuis l'IP propre du serveur ([ce qui ne peut pas](proxies.md#what-cannot-run-through-a-proxy)).
- **Gains.** Certains collecteurs ont besoin d'un cookie ou d'un jeton copié depuis votre navigateur, et certains de ceux-ci expirent. Le guide de chaque service indique lesquels.
- **Identifiants au repos.** L'interface garde le fichier de la clé de chiffrement dans le même volume de données que la base de données ([code][cp-fernet]). Les identifiants des apps de gains arrivent sur chaque worker sous forme de variables d'environnement du conteneur, ils sont donc en clair dans la configuration Docker de ce worker (`docker inspect`).
- **Réglages des conteneurs des apps de gains.** Le worker retire toutes les capacités, puis rajoute celles que le catalogue liste pour le service. Il définit `no-new-privileges` et une limite de pids, et il refuse les conteneurs privilégiés ([code][cp-hardening], [code][cp-privileged], [paramètres de sécurité par défaut](security-defaults.md)). Mysterium tourne dans son propre espace de noms réseau sur le bridge protégé par la barrière, avec `NET_ADMIN`, `SETUID` et `SETGID`, sur une image épinglée par digest ([catalogue][cp-myst]). Un runtime gVisor facultatif peut ajouter un noyau en espace utilisateur ([runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Socket Docker.** Depuis la v1.71.0, le worker n'a pas de socket. Le proxy de socket le détient : sockguard 2.4.7, épinglé par digest, en lecture seule ([compose][cp-sock]). Le worker reçoit une copie filtrée qui refuse les conteneurs privilégiés, les montages de `/` ou du socket, et les capacités ou périphériques hors de ceux du catalogue ([proxy de socket](security-defaults.md#docker-socket-proxy)). Le conteneur ponctuel `cashpilot-migrate` monte aussi le socket. Il donne l'étiquette de propriétaire aux volumes et au réseau de la barrière que les versions précédentes ont créés, et recrée leurs conteneurs dessus, pour que l'isolement par propriétaire du proxy les couvre. Il se termine avant le démarrage du proxy ([compose][cp-migrate]). Une app de gains ne reçoit jamais le socket ([code][cp-mounts]). Le proxy n'est pas encore une frontière fiable contre l'accès root. Quand `CASHPILOT_COMPOSE_DIR` ou `CASHPILOT_PROXY_BIND_MOUNTS` est défini, un worker compromis peut placer un lien symbolique dans un dossier autorisé avec un conteneur et atteindre le `/` de l'hôte avec un second ([détails](security-defaults.md#docker-socket-proxy)). Les fiches Unraid et TrueNAS montent encore le socket brut dans le worker ([magasins d'apps](app-stores.md)).
- **Isolement du réseau local.** Activé par défaut depuis la v1.70.0, sur les nouvelles installations et sur les installations mises à jour sans app de gains sur le bridge par défaut de Docker. Le worker place les apps de gains sur son propre bridge et écrit une table de pare-feu pour celui-ci ([code][cp-fence]). La table rejette les plages privées, la plage du tailnet, les métadonnées cloud, les sous-réseaux connectés à l'hôte et l'hôte lui-même. Quand la détection de l'IP publique est activée, elle rejette aussi l'IP publique du domicile ([isolement](isolation.md#lan-isolation-by-default)). Une installation mise à jour dont les apps de gains sont déjà sur le bridge par défaut y reste jusqu'à ce que vous appuyiez sur **Turn on isolation** (Activer l'isolement). `CASHPILOT_ISOLATION=off` le désactive. Quand `CASHPILOT_CONTAINER_NETWORK` est défini, CashPilot n'écrit aucune barrière pour ce réseau, et les règles de pare-feu sont à votre charge. Sous Podman, il n'y a pas de barrière, et la page du parc l'indique ([modes](isolation.md#modes), [code][cp-fence-mode]). Depuis la 2.0.7, Mysterium est lui aussi derrière la barrière. Un nœud déployé jusqu'à la 2.0.6 reste sur le réseau de l'hôte jusqu'à ce que vous le redéployiez ([Mysterium derrière la barrière](mysterium-fence.md)). Une vérification montre ce que les apps de gains peuvent atteindre ([vérification](isolation-check.md)).
- **Appels sortants.** En dehors des apps elles-mêmes, CashPilot appelle :
    - les versions GitHub, une fois par jour, pour sa vérification des mises à jour (`CASHPILOT_UPDATE_CHECK=off` les arrête, [code][cp-update]).
    - `api.ipify.org`, `ifconfig.me` ou `icanhazip.com` une fois par heure depuis chaque worker, pour son IP publique (`CASHPILOT_EGRESS_DETECT=off` les arrête, [code][cp-egress]).
    - CoinGecko et Frankfurter, pour les taux de change ([code][cp-rates]).
    - mempool.space, api.kaspa.org et des nœuds RPC publics Ethereum, Ethereum Classic, Polygon et Solana, pour les [soldes on-chain](onchain.md).
    - iptoasn.com, pour la table de noms de réseau de CashPilot, au plus une fois par semaine et seulement tant qu'un worker a l'[activité](activity.md#network-names-and-countries) activée ([code][cp-ipgeo]).
    - chaque fournisseur, pour les collecteurs.

    Le navigateur charge Google Fonts ([modèle][cp-cdn]) et Chart.js depuis jsDelivr ([modèle][cp-chartjs]).

Aucun des projets n'envoie de télémétrie d'usage dans le code que nous avons lu. Le binaire fermé d'IGM n'a pas pu être lu.

Chaque projet ici transmet les identifiants des apps aux conteneurs sous forme de variables d'environnement, et InternetIncome en transmet aussi certains comme arguments de commande, donc sur l'hôte qui exécute les apps, ils sont en clair dans la configuration des conteneurs de Docker (`Env` et `Args` dans `docker inspect`), lisibles par toute personne ayant accès à Docker. La ligne « Identifiants au repos » ne décrit que la copie stockée.

## Notre méthode de comptage { #how-we-counted }

- **CashPilot.** Les services du catalogue au statut active ou beta avec une image Docker, sans compter le calcul GPU ni les pools de minage. Le nombre de cette page vient de `scripts/generate_readme_tables.py`, et la CI échoue s'il dérive.
- **money4band 5.0.0.** Un fichier JSON par app dans `config/catalog/supported/` : 15. Les « 35 apps » du README comptent aussi le catalogue de la communauté, désactivé par défaut ([configuration][m4b-community]), les apps sans image Docker et les apps abandonnées.
- **IGM.** Les entrées de `apps.json` : 20, toutes activées. Le conteneur proxy, Watchtower et les conteneurs annexes de réclamation ne sont pas comptés.
- **InternetIncome.** Chaque bloc de commentaire `# Starting ... container` de `internetIncome.sh`, hors blocs du proxy et de Watchtower : 24. Les blocs Chrome et Firefox d'Ebesucher forment une seule app, de même qu'EarnFM et EarnFM Fleetshare, qui utilisent le même compte EarnFM. Le bloc des extensions Depin démarre Grass et Gradient ([script][ii-depin]), soit deux apps. Total : 23. Le tableau du README liste 27 apps, certaines avec seulement un lien d'inscription.
- **CashFactory.** Les services de gains de `docker-compose.yml` : 11. Portainer, le serveur web et les deux Watchtower ne sont pas comptés. Un service est commenté.
- **Modules complémentaires HA.** Les dossiers de modules avec un fichier de configuration : 10.

Nous n'avons pas vérifié si chaque app de chaque liste paie encore.

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
