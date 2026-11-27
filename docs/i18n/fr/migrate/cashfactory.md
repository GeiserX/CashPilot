---
source_hash: 7f8476aeb8b6
---
# Migrer depuis CashFactory { #moving-from-cashfactory }

CashPilot peut lire le `.env` de CashFactory et reprendre vos identifiants de services, pour que
vous n'ayez pas à les saisir à nouveau. Vous vérifiez tout avant que CashPilot ne l'enregistre.

## Avant de commencer { #before-you-start }

Il vous faut le compte propriétaire de CashPilot et au moins un worker CashPilot.

Arrêtez CashFactory sur une machine avant d'y déployer les mêmes services depuis
CashPilot. Deux copies derrière une même connexion gagnent comme une seule, et un même identifiant d'appareil
EarnApp ne doit pas tourner deux fois. Exécutez `docker compose down` dans le dossier
de CashFactory. Son
[fichier compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
démarre aussi trois conteneurs qui montent le socket Docker : Portainer (ligne 31)
et deux conteneurs Watchtower (lignes 141 et 264). Vérifiez qu'ils ont aussi disparu : `docker ps` ne doit
en lister aucun.

## Quel fichier utiliser { #which-file-to-use }

Utilisez le fichier `.env` de votre dossier CashFactory, celui que vous avez rempli à partir de
l'[exemple](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose lit ce fichier, et il développe `$` dans les valeurs qui ne sont pas entre
guillemets simples. Une telle valeur n'est pas ce que le fichier affiche, donc CashPilot vous demande
de la ressaisir plutôt que de deviner.

## Comment importer { #how-to-import }

1. Ouvrez **Settings** (Paramètres), puis **Import from another tool** (Importer depuis un autre outil) (ou allez sur `/import`).
2. Ajoutez le fichier `.env`, ou collez son texte. Laissez l'outil sur **Tell from the
   files** (Déduire des fichiers), ou choisissez CashFactory.
3. Vérifiez le tableau. Cochez les services que vous voulez et remplissez toute valeur signalée
   comme manquante.
4. Appuyez sur **Save the ticked services** (Enregistrer les services cochés), puis déployez-les sur vos workers depuis la
   même page.

## Ce qui est repris { #what-comes-over }

| App CashFactory | Clés lues | Service CashPilot | Ce qui est repris |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | identifiant d'appareil, pour que votre appareil lié continue de gagner |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | e-mail, mot de passe |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | e-mail, mot de passe |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | jeton |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | e-mail, clé d'API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | identifiant utilisateur |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID de l'appareil |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | clé d'API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | rien : plus disponible |

Une valeur qui affiche encore la valeur d'exemple du fichier (`<email>`, `sdk-node-<md5sum>`)
compte comme non définie, et un service qui ne contient que des valeurs d'exemple est laissé hors
du tableau.

## Ce qui n'est jamais repris { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot nomme chaque appareil d'après le worker sur lequel il tourne, pour que
  deux workers ne signalent jamais le même nom. Vos anciens appareils restent listés comme
  hors ligne dans le tableau de bord de chaque fournisseur jusqu'à ce que vous les y supprimiez.
- **Bitping.** CashFactory conserve l'identifiant Bitping dans un volume Docker, pas dans
  `.env`, donc l'import n'a rien à lire et n'affiche aucune ligne Bitping. Saisissez
  l'identifiant dans le formulaire de déploiement de Bitping.
- **Portainer et Watchtower.** CashPilot gère et met à jour ses propres
  conteneurs.

## Suivi des gains { #earnings-tracking }

Pour Honeygain et IPRoyal Pawns, l'identifiant du conteneur est aussi celui du compte,
donc CashPilot remplit également leurs identifiants de collecte des gains, sauf si vous les avez déjà
définis dans **Settings** (Paramètres). Pour tous les autres services, ajoutez l'identifiant de collecte des gains dans
**Settings > Earnings collection** (Paramètres > Collecte des gains).

## Sécurité { #safety }

- Rien dans le fichier n'est exécuté ni développé, et aucune adresse qu'il contient n'est consultée.
- Le fichier est lu une fois et n'est pas conservé. Ce que vous enregistrez est stocké chiffré, comme
  tous les autres identifiants dans CashPilot.
- Les secrets n'apparaissent sur la page que sous la forme **set** (défini).
- Les imports enregistrés restent sur la page d'import jusqu'à ce que vous appuyiez sur **Forget** (Oublier), pour que vous puissiez
  les déployer plus tard sur d'autres workers.
