---
source_hash: ca9dd25d45ca
---
# Migrer depuis InternetIncome { #moving-from-internetincome }

CashPilot peut lire le `properties.conf` d'InternetIncome, ainsi que les fichiers où il
conserve vos identifiants d'appareils EarnApp et ProxyRack, et les reprendre. Vous vérifiez
tout avant que CashPilot ne l'enregistre.

## Avant de commencer { #before-you-start }

Il vous faut le compte propriétaire de CashPilot et au moins un worker CashPilot.

Arrêtez InternetIncome sur une machine avant d'y déployer les mêmes services depuis
CashPilot. Deux copies derrière une même connexion gagnent comme une seule, et un même identifiant d'appareil
ne doit pas tourner deux fois. Dans le dossier d'InternetIncome, exécutez :

```bash
sudo bash internetIncome.sh --delete
```

`--delete` supprime les conteneurs et garde `earnapp.txt`, `proxyrack.txt` et
le dossier de données de Mysterium. `--deleteBackup` les supprime aussi
([internetIncome.sh, lignes 61 à 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
et [ligne 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
donc importez d'abord.

## Quels fichiers utiliser { #which-files-to-use }

Depuis le dossier d'InternetIncome :

- `properties.conf`, vos réglages.
- `earnapp.txt`, si vous faisiez tourner EarnApp. Chaque ligne contient un lien d'appareil
  ([lignes 1250 à 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, si vous faisiez tourner ProxyRack. Un UUID d'appareil par ligne
  ([lignes 817 à 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot prend le premier appareil de chaque fichier : celui que votre conteneur principal
utilisait et celui que vous avez lié à votre compte. Les autres lignes appartenaient à des copies
via proxy, et la page vous indique combien elle en a laissé de côté.

InternetIncome fait passer chaque valeur par le shell
([ligne 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Une valeur entre guillemets simples est prise telle qu'elle est écrite, comme le conseillent les commentaires de
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Une valeur hors guillemets simples qui contient `$`, un accent grave, une espace ou
un autre caractère que le shell modifierait n'est pas ce que le fichier affiche, donc
CashPilot vous demande de la ressaisir plutôt que de lancer un shell pour le savoir.

## Comment importer { #how-to-import }

1. Ouvrez **Settings** (Paramètres), puis **Import from another tool** (Importer depuis un autre outil) (ou allez sur `/import`).
2. Ajoutez `properties.conf`, plus `earnapp.txt` et `proxyrack.txt` si vous
   les avez. Laissez l'outil sur **Tell from the files** (Déduire des fichiers), ou choisissez InternetIncome.
3. Vérifiez le tableau. Cochez les services que vous voulez et remplissez toute valeur signalée
   comme manquante. Repocket a besoin de l'e-mail de votre compte, qu'InternetIncome ne demandait
   jamais.
4. Appuyez sur **Save the ticked services** (Enregistrer les services cochés), puis déployez-les sur vos workers depuis la
   même page.

## Ce qui est repris { #what-comes-over }

| App InternetIncome | Clés lues | Service CashPilot | Ce qui est repris |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | clé d'API (ajoutez votre e-mail) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | jeton |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | clé d'API, UUID de l'appareil |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | e-mail, mot de passe |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | e-mail, mot de passe |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | identifiant utilisateur |
| `earnfm` | `EARN_FM_API` | Earn.fm | clé d'API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | identifiant d'appareil |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | e-mail, mot de passe |
| `mysterium` | `MYSTERIUM=true` | Mysterium | activé ; voir la note sur Mysterium ci-dessous |

Une valeur vide signifie que l'app était désactivée, et elle n'est pas listée.

Ces apps sont listées mais pas reprises :

| App InternetIncome | Pourquoi |
|---|---|
| `urnetwork` | InternetIncome utilise un jeton de session. CashPilot connecte URnetwork avec votre e-mail et votre mot de passe. |
| `grass` | Grass fonctionne comme une extension de navigateur. CashPilot ne fait que le suivre, avec le jeton d'accès du tableau de bord de Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot les suit, mais il n'y a pas de conteneur à déployer. |
| `peer2profit` | Plus disponible. |

Les réglages des apps que CashPilot n'a pas (antGain, Adnade et d'autres) sont
listés par leur nom comme non lus.

## Ce qui n'est jamais repris { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot nomme chaque appareil d'après le worker sur lequel il tourne, pour que
  deux workers ne signalent jamais le même nom. Vos anciens appareils restent listés comme
  hors ligne dans le tableau de bord de chaque fournisseur jusqu'à ce que vous les y supprimiez.
- **Les proxys** (`USE_PROXIES`, `proxies.txt`). Ajoutez chacun d'eux dans la section **Proxies** (Proxys)
  de la page **Fleet** (Parc), puis faites passer des copies de vos services par ce proxy ; ajouter
  un proxy ne démarre rien à lui seul. Avec `USE_PROXIES=true`, InternetIncome faisait tourner
  vos services uniquement via des proxys. Enregistrer un import ne démarre rien non plus. Une
  copie via proxy nécessite que le même service soit d'abord déployé sur le worker, et
  ce déploiement le fait tourner sur la connexion propre du worker, donc un service qui ne doit
  jamais utiliser cette connexion doit rester non coché. Consultez [Copies via
  proxy](../proxies.md).
- **`BROWSER_USERNAME` et `BROWSER_PASSWORD`**, l'identifiant de connexion du navigateur propre à
  InternetIncome.

## Suivi des gains { #earnings-tracking }

Pour Honeygain, IPRoyal Pawns et Bitping, l'identifiant du conteneur est aussi celui du
compte, donc CashPilot remplit également leurs identifiants de collecte des gains, sauf si vous
les avez déjà définis dans **Settings** (Paramètres). Pour tous les autres services, ajoutez l'identifiant de collecte des gains
dans **Settings > Earnings collection** (Paramètres > Collecte des gains).

## Mysterium { #mysterium }

L'import active Mysterium, mais CashPilot démarre un nouveau nœud avec une nouvelle
identité. Le keystore de l'ancien nœud et tous les gains non réglés restent dans le dossier
`mysterium-data` d'InternetIncome. Réglez-les d'abord, ou suivez le
[guide Mysterium](../guides/mysterium.md) pour transférer l'identité.

## Sécurité { #safety }

- Rien dans les fichiers n'est exécuté ni développé, et aucune adresse qu'ils contiennent n'est consultée.
- Les fichiers sont lus une fois et ne sont pas conservés. Ce que vous enregistrez est stocké chiffré, comme
  tous les autres identifiants dans CashPilot.
- Les secrets n'apparaissent sur la page que sous la forme **set** (défini).
- Les imports enregistrés restent sur la page d'import jusqu'à ce que vous appuyiez sur **Forget** (Oublier), pour que vous puissiez
  les déployer plus tard sur d'autres workers.
