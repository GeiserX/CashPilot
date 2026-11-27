---
source_hash: 38029ca1a5d6
---
# Export des revenus pour les impôts { #income-export-for-taxes }

Ouvrez **Payouts** (Paiements), trouvez **Income for taxes** (Revenus pour les impôts), puis choisissez une période et une devise. **This year** (Cette année) va jusqu'à aujourd'hui, et **Last year** (L'année dernière) couvre l'année civile précédente. Laissez les dates vides pour exporter tout l'historique disponible jusqu'à aujourd'hui. CashPilot utilise des dates UTC et inclut les deux bornes de la période.

CashPilot supprime les relevés de gains 400 jours après leur enregistrement. Le CSV utilise l'historique qui reste, donc une année passée peut ne contenir qu'une partie de ses revenus gagnés ou acquis.

## Choisir une méthode comptable { #choose-an-accounting-basis }

- **Comptabilité de trésorerie.** Utilisez les lignes de paiement. Elles enregistrent l'argent que le service a versé. CashPilot n'inclut que les paiements confirmés.
- **Comptabilité d'engagement.** Utilisez les lignes gagnées et acquises. Les lignes gagnées montrent un crédit que vous pouvez retirer selon les conditions du service. Les lignes acquises montrent un crédit impayé d'un pool, que le pool risque de ne jamais payer.

Utilisez une seule méthode pour un même revenu. Ajouter les lignes de paiement aux lignes gagnées et acquises peut compter deux fois le même argent. Vérifiez quelle méthode s'applique à votre déclaration.

## Colonnes du CSV { #csv-columns }

| Colonne | Signification |
|---|---|
| date | Jour UTC du relevé le plus récent ou du paiement. Un paiement utilise la date que vous avez saisie ou le jour où CashPilot l'a détecté. |
| period_start | Jour UTC du relevé précédent pour ce service et cette source. Vide pour les paiements. Un écart entre deux relevés signifie que le montant couvre tout l'intervalle. |
| kind | earned, accrued ou payout. |
| service | Identifiant du service dans CashPilot. |
| coin | Code de la devise ou du jeton tel que CashPilot l'a enregistré. |
| amount | Montant dans cette devise ou ce jeton. |
| usd_rate | Nombre de dollars américains par unité de coin. |
| usd_value | Montant valorisé en dollars américains. |
| local_currency | Monnaie fiat que vous avez choisie pour l'export. |
| local_rate | Unités de la devise choisie par dollar américain. |
| local_value | Montant valorisé dans la devise choisie. |
| method | Méthode de paiement, si elle a été enregistrée. |

Une valorisation vide signifie que le taux n'était pas disponible. Le montant d'origine reste présent. CashPilot ignore les points internes, comme les points Grass, dans les relevés de gains. Le premier relevé de chaque source fournit un solde d'ouverture. Les lignes suivantes enregistrent les hausses, donc le CSV peut commencer après le relevé le plus ancien de la période choisie.

Si plusieurs sources lisent le même compte, le CSV peut compter ce revenu plusieurs fois.

Le taux en USD vient du relevé le plus récent ou de l'enregistrement du paiement. Quand CashPilot complète après coup le prix d'un relevé, il utilise le prix de CoinGecko à 00:00 UTC ce jour-là. CashPilot utilise le taux de référence de la BCE le plus récent publié le jour de la ligne ou avant pour convertir les USD dans la devise choisie. Cela couvre les week-ends, les jours fériés et les jours où la BCE n'a pas encore publié son taux. [Taux quotidiens de Frankfurter](https://frankfurter.dev/v1/)

Frankfurter propose ces devises pour l'export. [Devises prises en charge](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR et ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD et ZAR.

Choisissez USD si votre devise ne figure pas dans cette liste ou si Frankfurter n'est pas disponible.

## Importer dans un autre outil { #import-into-another-tool }

Convertissez le CSV au format de l'outil avant de l'importer. Choisissez d'abord les lignes qui correspondent à votre méthode comptable. Ignorez les lignes de paiement d'un portefeuille que l'outil synchronise déjà.

### rotki { #rotki }

Utilisez Generic Events avec ces en-têtes.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Mettez Type sur Income et Location sur external. rotki accepte aussi Deposit, Withdrawal, Loss, Spend et Staking quand ces types décrivent un événement. Associez coin à Currency, amount à Amount et service à Description. Utilisez l'identifiant d'actif de rotki là où il diffère du code de coin. Convertissez date en horodatage Unix UTC en millisecondes. Laissez les deux champs de frais vides. [Generic Events de rotki](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Utilisez les colonnes obligatoires du modèle Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Formatez Date en YYYY-MM-DD HH:mm:ss en UTC. Remplissez Received Amount à partir de amount et Received Currency à partir de coin. Laissez les deux champs Sent vides. Pour les valeurs connues, associez local_value et local_currency aux colonnes facultatives Net Worth Amount et Net Worth Currency. Utilisez la colonne Tag pour mining ou reward selon le cas. Description et TxHash sont facultatifs. [Modèle Universal de Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Pas encore de compte Koinly ? Vous pouvez vous inscrire ici : https://koinly.io/?via=FFF185D5. C'est un lien de parrainage, et il ne vous coûte rien.

### CoinTracking { #cointracking }

Convertissez les lignes de revenus au format CSV standard de CoinTracking. Le Custom Importer exige des champs de transaction des deux côtés, et une ligne de revenu n'a qu'un côté achat. [Exigences du Custom Importer de CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Mettez Type sur Income ou Mining selon le cas. Associez amount à Buy Amount, coin à Buy Currency et service à Comment. Laissez les champs Sell vides. Formatez Date en DD.MM.YYYY HH:MM:SS. L'export fournit le jour UTC, donc utilisez 00:00:00 pour l'heure. Utilisez les libellés de type correspondant à la langue de votre compte. [Format CSV standard de CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Pas encore de compte CoinTracking ? Ce lien d'inscription vous donne 10 % de réduction sur chaque formule payante : https://cointracking.info?ref=G962413. C'est un lien de parrainage. CoinTracking verse au projet CashPilot 20 % de ce que vous payez, et cela ne vous coûte pas plus cher.
