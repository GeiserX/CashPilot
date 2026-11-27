---
source_hash: b4ae1a3ae496
---
# Argent en attente : des rappels avant de perdre des gains { #money-waiting-reminders-before-you-lose-earnings }

Certains fournisseurs reprennent l'argent qui attend trop longtemps. Un solde peut expirer après
des mois sans activité. Une fenêtre pour réclamer peut se fermer. Un fournisseur peut bannir un
compte, arrêter de payer ou fermer alors que votre solde est encore là.
CashPilot lit déjà presque tout ce dont il a besoin pour voir venir ces situations. Le
panneau **Money waiting** (Argent en attente) du tableau de bord indique quoi faire et avant quand, et
vos canaux de notification reçoivent une notification push avant chaque échéance.

CashPilot ne réclame et ne retire jamais rien à votre place. Chaque rappel renvoie
vers la page du fournisseur lui-même, et c'est là que vous agissez.

## Ce qu'il vous rappelle { #what-it-reminds-you-about }

**Les règles tirées des conditions du fournisseur.** Chaque règle cite les conditions ou la page d'aide
du fournisseur, et la date à laquelle quelqu'un l'a lue pour la dernière fois. Le lien **Source** (Source) du
menu **More** (Plus) de la ligne l'ouvre.

| Service | Rappel | Quand |
|---|---|---|
| Grass | Réclamez vos USDC de la Stage 2 | Avant le 22 janv. 2027. Grass garde ce qui n'est pas réclamé. |
| MystNodes | Réclamez les récompenses du mois dernier | Dans les 30 jours suivant chaque distribution mensuelle |
| Honeygain | Retirez votre solde | 24 mois après qu'il a atteint 20 $ pour la première fois |
| Honeygain | Gardez un appareil en partage, ou demandez un paiement | 6 mois après la dernière activité ou le dernier paiement |
| Repocket | Gardez un appareil en partage, ou retirez | 12 mois après la dernière activité ou le dernier paiement |
| Bitping | Retirez votre solde | 12 mois après le dernier retrait |
| Salad | Gagnez quelques Reward Points, ou dépensez votre solde | 12 mois après la dernière hausse du solde. En dépenser une partie ne remet pas ce délai à zéro. |

**Retrait.** CashPilot vous prévient quand un solde atteint le minimum du
fournisseur. Cela vaut pour chaque service dont il collecte les gains, sauf les services qui
paient d'eux-mêmes. Un solde doit aussi valoir au moins 5 $, pour qu'un fournisseur
avec un minimum de 5 centimes ne vous relance pas dès le premier centime. Quand le minimum du
fournisseur est plus élevé, c'est ce minimum qui s'applique. Quand CashPilot ne peut pas
convertir le minimum ou le solde, il n'affiche rien. Il ne suppose jamais que
vous pouvez retirer.

**Expiration des identifiants.** Vous recevez une notification push avant qu'un jeton ou un cookie enregistré n'expire.
CashPilot utilise la date d'expiration que l'identifiant indique lui-même. Quand il n'en indique
aucune, CashPilot utilise la durée de vie habituelle de ce type d'identifiant, comptée
à partir du jour où vous l'avez enregistré. Les propriétaires le voient déjà sous **Needs attention** (À traiter),
avec un bouton **Renew** (Renouveler), donc le panneau ne le répète pas. Seuls les propriétaires reçoivent
les rappels d'identifiants depuis l'API, comme pour le contrôle de santé des identifiants.
Un identifiant que le fournisseur a refusé figure déjà dans la cloche et a déjà été notifié,
donc il n'est pas notifié une seconde fois.

## Les services concernés { #which-services-it-covers }

Un rappel s'applique à un service que vous utilisez : un service déployé, un service que vous avez configuré
comme externe dans **Settings** (Paramètres), ou une app qu'un téléphone signale. Un service que vous avez supprimé
compte encore tant qu'il détient un solde, car les compteurs d'inactivité démarrent
quand il s'arrête. Les services personnalisés et les services abandonnés n'ont pas de rappels.

## Les dates et « ou plus tôt » { #dates-and-or-earlier }

Les compteurs d'activité partent de ce que CashPilot a enregistré :

- la dernière fois que le solde a augmenté,
- le dernier paiement,
- ou le premier relevé égal ou supérieur au minimum.

Parfois, le compteur a démarré avant le premier relevé de CashPilot. L'échéance réelle
peut alors être plus proche que ce que CashPilot peut voir, et la ligne indique
« avant le 3 oct. 2027 ou plus tôt ».

CashPilot supprime l'historique des gains après 400 jours, et le compteur de Honeygain
court sur 730 jours. CashPilot enregistre donc le début de chaque compteur la première fois qu'il
le voit, et le garde une fois l'historique correspondant supprimé. Un paiement remet
le compteur à zéro, sauf là où le fournisseur ne compte que les gains. C'est le cas de Salad : un
paiement qui laisse un solde ne remet pas ses 12 mois à zéro.

Une date fixe disparaît le lendemain de son passage, car l'argent est perdu.
Un compteur dépassé reste affiché et indique que le fournisseur a peut-être déjà annulé
cet argent. Il reste jusqu'à ce que vous le marquiez comme fait ou que vous le mettiez en sourdine, ou jusqu'à ce qu'un paiement
le remette à zéro.

## Ce que vous pouvez faire d'un rappel { #what-you-can-do-with-a-reminder }

Les propriétaires et les éditeurs voient les boutons. Les lecteurs voient seulement les rappels. Seuls les propriétaires
peuvent agir sur un rappel d'identifiant.

- **Done** (Fait), ou **Requested** (Demandé) pour un retrait, masque ce rappel. Une fenêtre
  mensuelle revient le mois suivant. Un retrait revient une fois après 14 jours si
  le solde est toujours là, et demande si le paiement est arrivé. Cela reste
  dans la fenêtre de contestation de 60 jours que la plupart des fournisseurs accordent.
- **Snooze** (Reporter) le masque pendant un jour ou une semaine et retient ses notifications push. Un report ne
  dépasse jamais le dernier avertissement avant une échéance.
- **Not for me** (Pas pour moi), dans le menu **More** (Plus), met en sourdine un rappel, ou tous les rappels
  d'un service. Un exemple : Honeygain en mode JumpTask, où un solde qui ne bouge pas
  est normal. Les rappels en sourdine sont listés au bas du panneau, avec
  **Unmute** (Réactiver).

Le foyer partage ces choix. Quand une personne marque un rappel comme fait, il
est fait pour tout le monde. Chaque choix est consigné dans le journal d'audit avec le nom de
la personne qui l'a fait.

## Notifications push { #pushes }

Les rappels vont vers les canaux que vous avez définis pour les alertes : ntfy, un webhook ou Telegram
([configuration](configuration.md)). Sans canal défini, le panneau est le seul
endroit où ils apparaissent.

- Une notification push par avertissement. Par exemple, Grass notifie 60, 30, 7 et 1 jour avant
  sa date. Un rappel vu pour la première fois 5 jours avant sa date notifie une seule fois, avec 5
  jours restants.
- Les notifications push ne partent qu'entre 09:00 et 21:00. CashPilot utilise le fuseau horaire
  du premier propriétaire défini dans **Settings** (Paramètres), puis le `TZ` du conteneur, puis UTC. Un avertissement
  atteint pendant la nuit part au premier contrôle après 09:00.
- Quand plus de 3 notifications push sont dues en même temps, vous recevez un seul résumé à la place. Cela
  arrive le jour de la mise à jour, quand tous les soldes au-dessus de leur minimum apparaissent
  ensemble.
- Une notification push contient le service, ce qu'il faut faire, ce que vous perdriez, la date et le
  lien du fournisseur. Elle ne contient jamais de solde, d'adresse, d'identifiant d'appareil ni de
  nom de worker. Les sujets ntfy peuvent être publics.
- Les charges utiles des webhooks contiennent `kind: "obligation"`, pour que Home Assistant et les outils
  similaires puissent les router.

## Pour les contributeurs du catalogue { #for-catalog-contributors }

Les règles se trouvent dans le fichier YAML de chaque service, sous `obligations:`.
`services/_schema.yml` documente les champs. N'ajoutez une règle que lorsque les
conditions ou la documentation du fournisseur l'énoncent elles-mêmes, et lorsque CashPilot peut voir le signal dont elle
dépend. Le lien d'une règle doit se trouver sur le domaine du service lui-même, car de faux
sites de réclamation existent précisément pour ces services. La CI échoue sur une règle invalide, et
sur une règle datée dépassée de plus de 30 jours.
