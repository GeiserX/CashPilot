---
source_hash: 1a7f6b462b56
---
# Migrer depuis money4band { #moving-from-money4band }

CashPilot peut lire la configuration de money4band et reprendre vos identifiants de services, pour que
vous n'ayez pas à les saisir à nouveau. Vous vérifiez tout avant que CashPilot ne l'enregistre.

## Avant de commencer { #before-you-start }

Il vous faut le compte propriétaire de CashPilot et au moins un worker CashPilot sur la
machine où money4band tourne actuellement, ou sur une autre machine.

Arrêtez money4band sur une machine avant d'y déployer les mêmes services depuis
CashPilot. Deux copies derrière une même connexion gagnent comme une seule, et un même identifiant d'appareil EarnApp
ou ProxyRack ne doit pas tourner deux fois. Utilisez **Stop apps stack** dans le
menu de money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
ou exécutez `docker compose down` dans son dossier. Si vous avez configuré des instances
de proxy supplémentaires, arrêtez-les aussi, chacune.

## Quel fichier utiliser { #which-file-to-use }

Utilisez `config/user-config.json` dans votre dossier money4band. La façon de le
transmettre à CashPilot dépend de votre version de money4band.

Dans money4band 4.x, money4band écrit le fichier quand vous lancez **Setup Apps**, et
il contient exactement ce que vous avez saisi. Le `.env`
à côté est généré à partir de ce fichier et fonctionne aussi, tout comme le `.env`
modifié à la main de money4band 3.x. Les deux restent uniquement sur votre disque : le
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
de money4band les liste.

money4band 5.0 chiffre `config/user-config.json` sur le disque
([notes de sécurité](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
et il supprime son `.env` après chaque démarrage
([générateur du env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot ne peut pas lire le fichier chiffré. Lancez `m4b config edit` dans votre
dossier money4band : la commande ouvre le fichier déchiffré dans votre éditeur
([référence de la CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Copiez tout son texte, collez-le sur la page d'import, puis fermez l'éditeur.

Préférez le fichier JSON. Dans un `.env`, Docker Compose développe `$` dans les valeurs sans guillemets,
donc un mot de passe qui contient `$` n'est pas ce que le fichier affiche. CashPilot ne
devine pas : il vous demande de ressaisir cette valeur.

## Comment importer { #how-to-import }

1. Ouvrez **Settings** (Paramètres), puis **Import from another tool** (Importer depuis un autre outil) (ou allez sur `/import`).
2. Ajoutez `user-config.json`, ou collez son texte. Laissez l'outil sur **Tell from the
   files** (Déduire des fichiers), ou choisissez money4band.
3. Vérifiez le tableau. Cochez les services que vous voulez et remplissez toute valeur signalée
   comme manquante.
4. Appuyez sur **Save the ticked services** (Enregistrer les services cochés), puis déployez-les sur vos workers depuis la
   même page.

## Ce qui est repris { #what-comes-over }

Les noms des champs viennent du
[modèle user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
de money4band et des noms du `.env` qu'écrit son
[générateur](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, par exemple `REPOCKET_APIKEY`). money4band 5.0 garde
les mêmes noms de champs dans son
[catalogue d'apps](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| App money4band | Service CashPilot | Ce qui est repris |
|---|---|---|
| `earnapp` | EarnApp | identifiant d'appareil (`uuid`), pour que votre appareil lié continue de gagner |
| `honeygain` | Honeygain | e-mail, mot de passe |
| `iproyalpawns` | IPRoyal Pawns | e-mail, mot de passe |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | jeton |
| `repocket` | Repocket | e-mail, clé d'API |
| `earnfm` | Earn.fm | clé d'API |
| `proxyrack` | ProxyRack | clé d'API, UUID de l'appareil |
| `proxylite` | ProxyLite | identifiant utilisateur |
| `bitping` | Bitping | e-mail, mot de passe |
| `mystnode` | Mysterium | activé ; voir la note sur Mysterium ci-dessous |

Une app que vous aviez désactivée dans money4band apparaît non cochée. Une app désactivée qui
ne contient rien d'autre que les valeurs d'exemple du modèle (`yourHONEYGAINMail`) et des listes
de ports est laissée de côté, donc un `user-config.json` jamais modifié donne un tableau vide.

Ces apps sont listées mais pas reprises :

| App money4band | Pourquoi |
|---|---|
| `proxybase` | money4band exécute l'ancien client de ProxyBase avec un identifiant utilisateur. CashPilot exécute le client actuel, qui a besoin de l'Access Token de proxybase.org. |
| `urnetwork` | money4band conserve un jeton de session. CashPilot connecte URnetwork avec votre e-mail et votre mot de passe. |
| `grass` | Grass fonctionne comme une extension de navigateur. CashPilot ne fait que le suivre, avec le jeton d'accès du tableau de bord de Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot les suit, mais il n'y a pas de conteneur à déployer. |
| `packetshare`, `peer2profit`, `speedshare` | Plus disponibles. |

Toute autre app est listée avec la mention **CashPilot has no such service** (CashPilot n'a pas ce service).

## Ce qui n'est jamais repris { #what-never-comes-over }

- **Le nom de l'appareil.** CashPilot nomme chaque appareil d'après le worker sur lequel il tourne, pour que
  deux workers ne signalent jamais le même nom. Vos anciens appareils restent listés comme
  hors ligne dans le tableau de bord de chaque fournisseur jusqu'à ce que vous les y supprimiez.
- **Les proxys.** Ajoutez chacun d'eux dans la section **Proxies** (Proxys) de la page **Fleet** (Parc), puis faites passer
  des copies de vos services par ce proxy ; ajouter un proxy ne démarre rien à lui seul.
  Enregistrer un import ne démarre rien non plus. Une copie via proxy nécessite que le même service
  soit d'abord déployé sur le worker, et ce déploiement le fait tourner sur la connexion propre du worker,
  donc un service qui ne doit jamais utiliser cette connexion doit rester
  non coché. Consultez [Copies via proxy](../proxies.md).
- **Watchtower et les notifications.** CashPilot met à jour ses propres conteneurs.
- **Le tableau de bord de money4band et ses ports.**

## Suivi des gains { #earnings-tracking }

Pour Honeygain, IPRoyal Pawns et Bitping, l'identifiant du conteneur est aussi celui du
compte, donc CashPilot remplit également leurs identifiants de collecte des gains, sauf si vous
les avez déjà définis dans **Settings** (Paramètres). Pour tous les autres services, ajoutez l'identifiant de collecte des gains
dans **Settings > Earnings collection** (Paramètres > Collecte des gains).

## Mysterium { #mysterium }

L'import active Mysterium, mais CashPilot démarre un nouveau nœud avec une nouvelle
identité. Le keystore de l'ancien nœud et tous les gains non réglés restent dans le dossier
`.data/mysterium-node` de money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Réglez-les d'abord, ou suivez le
[guide Mysterium](../guides/mysterium.md) pour transférer l'identité.

Un `.env` 3.x ne permet pas de savoir si vous faisiez tourner Mysterium : son modèle liste toujours
le port du tableau de bord. Depuis un fichier 3.x, Mysterium n'est pas importé, donc ajoutez-le
depuis le catalogue si vous le faisiez tourner.

## Sécurité { #safety }

- Rien dans le fichier n'est exécuté ni développé, et aucune adresse qu'il contient n'est consultée.
- Le fichier est lu une fois et n'est pas conservé. Ce que vous enregistrez est stocké chiffré, comme
  tous les autres identifiants dans CashPilot.
- Les secrets n'apparaissent sur la page que sous la forme **set** (défini).
- Les imports enregistrés restent sur la page d'import jusqu'à ce que vous appuyiez sur **Forget** (Oublier), pour que vous puissiez
  les déployer plus tard sur d'autres workers.
