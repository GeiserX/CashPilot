---
source_hash: d88e40f8d9a6
---
# Soldes de paiement on-chain { #on-chain-payout-balances }

Ouvrez **Payouts** (Paiements) pour voir le solde d'une adresse de paiement publique. Bitcoin utilise
[mempool.space](https://mempool.space/docs/api/rest) et Kaspa utilise
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon et Solana utilisent
des nœuds RPC publics. CashPilot peut lire ces adresses sans clé.

| Ce que vous voyez | Ce que cela signifie |
|---|---|
| Un montant | L'explorateur a renvoyé un solde. Un zéro renvoyé s'affiche comme zéro. Survolez le montant pour voir la source. |
| **Pending** (En attente) | Sur Bitcoin, l'explorateur voit un changement non confirmé. Un plus signifie que des fonds arrivent. Un moins signifie que des fonds sont en train d'être dépensés. Le montant confirmé est affiché séparément. |
| **Could not check** (Vérification impossible) | L'explorateur n'a pas répondu ou a envoyé des données que CashPilot n'a pas pu lire. |
| **Address not valid** (Adresse non valide) | L'adresse n'a pas passé la vérification de format. CashPilot n'a pas envoyé la requête. |
| **Private chain** (Chaîne privée) | Lire un solde Monero nécessite votre clé de lecture privée (view key). Vérifiez le solde dans votre portefeuille. CashPilot ne vous demande jamais cette clé. |
| Un tiret | Il n'y a pas d'adresse ni de lecteur pour cette ligne, ou la consultation est désactivée. Quand un réglage désactive la consultation, survolez le tiret pour voir lequel. |

Le point d'accès public de Kaspa renvoie un seul solde. Il ne fournit pas de montant
en attente séparé.

La colonne on-chain affiche le solde actuel de l'adresse. Il peut inclure
des transferts venant d'autres sources. Le solde impayé du pool indique ce que le pool
détient encore pour vous. Un paiement OCEAN via Lightning n'apparaît pas dans le
solde on-chain. Le solde ne permet pas non plus de savoir quels transferts viennent de
votre pool.

## Choisir où part la consultation { #choose-where-the-lookup-goes }

Chaque consultation transmet à l'explorateur votre adresse de paiement publique et l'IP du serveur de l'interface.
L'explorateur peut relier les adresses que vous vérifiez depuis la même IP.

Définissez l'URL de base dans l'environnement du conteneur de l'interface si vous faites tourner votre propre nœud.
Ne définissez pas la variable pour utiliser la valeur par défaut. Donnez-lui une valeur vide pour désactiver
la consultation pour cette chaîne.

Par exemple, un fichier d'override Compose pour le service de l'interface pourrait contenir :

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Utilisez l'URL de base de l'API Esplora ou Kaspa pour configurer Bitcoin ou Kaspa.
Le point d'accès Bitcoin fournit aussi la difficulté du réseau et les récompenses de bloc pour les
[gains attendus](fleet.md#running-costs) d'un pool Bitcoin. Cette lecture nécessite un
backend mempool (son API `/v1/mining`) ; un simple serveur Esplora ne répond qu'à la
consultation du solde, et la ligne du pool n'affiche alors aucun montant attendu.
Pour Ethereum, Polygon et Solana, définissez les variables correspondantes
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` ou
`CASHPILOT_ONCHAIN_URL_SOLANA` sur l'URL RPC d'un nœud. Utilisez une URL HTTP ou HTTPS
sans identifiants, sans chaîne de requête et sans fragment. Appliquez le changement en
recréant le conteneur de l'interface avec le nouvel environnement.
