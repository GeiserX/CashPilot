---
source_hash: e99e2c0c80bb
---
# Boutiques d'applications { #app-stores }

Vous pouvez installer CashPilot depuis la boutique d'applications de plusieurs systèmes de serveur domestique.
Chaque fiche installe le tableau de bord (`drumsergio/cashpilot`) et le worker
(`drumsergio/cashpilot-worker`), qui démarre et arrête les conteneurs
des services. Seuls les paquets CasaOS et Runtipi de ce dépôt installent aussi
le proxy de socket Docker de `docker-compose.yml`, de sorte que leur worker
ne détient jamais le socket Docker brut. Les modèles Unraid, l'application TrueNAS et
le paquet de la pull request ouverte sur la boutique d'applications CasaOS montent encore le socket
Docker directement dans le worker.

Quelle que soit la boutique utilisée, gardez le tableau de bord sur votre réseau local ou votre VPN. Il peut commander
le worker, et le worker pilote Docker sur l'hôte. Là où le worker détient
lui-même le socket, cela équivaut à root sur l'hôte.

## Disponible aujourd'hui { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Cherchez **CashPilot** dans l'onglet Apps et installez les deux modèles :
`cashpilot` (le tableau de bord) et `cashpilot-worker`. Définissez la même
`CASHPILOT_API_KEY` sur les deux.

Les modèles viennent de https://github.com/GeiserX/docker-templates et suivent
le tag d'image `latest`, donc les utilisateurs de Community Applications reçoivent chaque version
sans changement de modèle.

### TrueNAS SCALE { #truenas-scale }

CashPilot fait partie du train **community** de TrueNAS. Ouvrez Apps, puis Discover Apps,
et cherchez **CashPilot**.

La définition de l'application est maintenue sur
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot et épingle
un digest d'image exact. Les bots de TrueNAS la font passer aux nouvelles versions, elle peut donc avoir
quelques versions de retard sur le CashPilot le plus récent.

## En attente de validation { #waiting-for-review }

### CasaOS { #casaos }

Une pull request vers la boutique d'applications CasaOS est ouverte :
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

En attendant sa fusion, installez-le comme application personnalisée : dans CasaOS, choisissez App Store,
puis Custom Install, puis Import, et collez le contenu de
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Il faut CasaOS 0.4.5 ou plus récent : depuis cette version, son gestionnaire d'applications repose sur
Docker Compose 2.23, qui lit dans le fichier la politique du proxy de socket.
Les versions plus anciennes l'ignorent, et le worker ne peut alors pas joindre Docker.

Ce fichier épingle une version exacte. Avant de l'importer, réglez les deux tags d'image
(`drumsergio/cashpilot` et `drumsergio/cashpilot-worker`) sur la version la plus récente
de https://github.com/GeiserX/CashPilot/releases. La politique du proxy
dans le fichier suit `main` ; si la page d'état du worker indique que sa politique n'est
plus à jour, importez à nouveau le fichier.

## Préparé, pas encore soumis { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Le paquet est prêt dans
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
mais pas encore dans la boutique d'applications Runtipi. Pour l'utiliser dès maintenant, ajoutez-le à une boutique
d'applications personnalisée que vous contrôlez, en suivant la documentation de Runtipi :
https://runtipi.io/docs/guides/create-your-own-app-store

## Non proposé { #not-offered }

Umbrel nécessite une autre conception du worker, car les applications Umbrel accèdent à Docker
via un conteneur Docker-in-Docker plutôt que par le socket de l'hôte. Nous ne l'avons pas
testé, il n'existe donc pas encore de paquet Umbrel.

Pour tout autre système, utilisez le `docker-compose.yml` du dépôt, comme dans
[Premiers pas](getting-started.md).
