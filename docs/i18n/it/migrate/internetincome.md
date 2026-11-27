---
source_hash: ca9dd25d45ca
---
# Passare da InternetIncome { #moving-from-internetincome }

CashPilot può leggere il `properties.conf` di InternetIncome, e i file in cui
conserva gli id dei tuoi dispositivi EarnApp e ProxyRack, e portarli con sé. Controlli
tutto prima che CashPilot lo salvi.

## Prima di iniziare { #before-you-start }

Ti servono l'account proprietario di CashPilot e almeno un worker di CashPilot.

Ferma InternetIncome su una macchina prima di distribuire lì gli stessi servizi da
CashPilot. Due copie dietro un'unica connessione guadagnano come una sola, e lo stesso id del dispositivo
non deve girare due volte. Nella cartella di InternetIncome, esegui:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` rimuove i container e conserva `earnapp.txt`, `proxyrack.txt` e
la cartella dei dati di Mysterium. `--deleteBackup` rimuove anche quelli
([internetIncome.sh, righe da 61 a 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
e [riga 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
quindi importa prima.

## Quali file usare { #which-files-to-use }

Dalla cartella di InternetIncome:

- `properties.conf`, le tue impostazioni.
- `earnapp.txt`, se eseguivi EarnApp. Ogni riga contiene il link di un dispositivo
  ([righe da 1250 a 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, se eseguivi ProxyRack. Un UUID di dispositivo per riga
  ([righe da 817 a 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot prende il primo dispositivo di ogni file: quello che usava il tuo container
principale e quello che hai collegato al tuo account. Le altre righe appartenevano a copie
via proxy, e la pagina ti dice quante ne ha escluse.

InternetIncome fa passare ogni valore dalla shell
([riga 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Un valore tra virgolette singole viene preso così com'è scritto, come consigliano i commenti in
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Un valore fuori dalle virgolette singole che contiene `$`, un backtick, uno spazio o
un altro carattere che la shell cambierebbe non è quello che mostra il file, quindi
CashPilot ti chiede di digitarlo di nuovo invece di eseguire una shell per scoprirlo.

## Come importare { #how-to-import }

1. Apri **Settings** (Impostazioni), poi **Import from another tool** (Importa da un altro strumento) (oppure vai a `/import`).
2. Aggiungi `properties.conf`, più `earnapp.txt` e `proxyrack.txt` se li
   hai. Lascia lo strumento su "Riconosci dai file", oppure scegli InternetIncome.
3. Controlla la tabella. Spunta i servizi che vuoi e compila ogni valore segnato
   come mancante. Repocket richiede l'email del tuo account, che InternetIncome non ha mai
   chiesto.
4. Premi **Save the ticked services** (Salva i servizi spuntati), poi distribuiscili sui tuoi worker dalla
   stessa pagina.

## Cosa viene importato { #what-comes-over }

| App di InternetIncome | Chiavi lette | Servizio di CashPilot | Cosa viene importato |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | chiave API (aggiungi la tua email) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | chiave API, UUID del dispositivo |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, password |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, password |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id utente |
| `earnfm` | `EARN_FM_API` | Earn.fm | chiave API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id del dispositivo |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, password |
| `mysterium` | `MYSTERIUM=true` | Mysterium | attivato; vedi la nota su Mysterium più sotto |

Un valore vuoto significa che l'app era disattivata, e non viene elencata.

Queste app sono elencate ma non vengono importate:

| App di InternetIncome | Perché |
|---|---|
| `urnetwork` | InternetIncome usa un token di sessione. CashPilot fa accedere URnetwork con la tua email e la tua password. |
| `grass` | Grass gira come estensione del browser. CashPilot si limita a seguirlo, con l'access token della dashboard di Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot li segue, ma non c'è nessun container da distribuire. |
| `peer2profit` | Non più disponibile. |

Le impostazioni delle app che CashPilot non ha (antGain, Adnade e altre) vengono
elencate per nome come non lette.

## Cosa non viene mai importato { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot dà a ogni dispositivo il nome del worker su cui gira, così
  due worker non riportano mai lo stesso nome. I tuoi vecchi dispositivi restano elencati come
  offline nella dashboard di ogni fornitore finché non li rimuovi lì.
- **Proxy** (`USE_PROXIES`, `proxies.txt`). Aggiungi ciascuno nella sezione Proxies
  della pagina della flotta, poi esegui copie dei tuoi servizi tramite di esso; aggiungere
  un proxy da solo non avvia nulla. Con `USE_PROXIES=true` InternetIncome eseguiva
  i tuoi servizi solo tramite proxy. Neanche salvare un'importazione avvia nulla. Una
  copia via proxy richiede che lo stesso servizio sia prima distribuito sul worker, e
  distribuirlo lo esegue sulla connessione del worker stesso, quindi un servizio che non deve
  mai usare quella connessione va lasciato senza spunta. Vedi [Copie via
  proxy](../proxies.md).
- **`BROWSER_USERNAME` e `BROWSER_PASSWORD`**, l'accesso al browser proprio di
  InternetIncome.

## Monitoraggio dei guadagni { #earnings-tracking }

Per Honeygain, IPRoyal Pawns e Bitping l'accesso del container è anche l'accesso
all'account, quindi CashPilot compila anche le loro credenziali per i guadagni, a meno che tu
non le abbia già impostate nelle impostazioni. Per ogni altro servizio, aggiungi l'accesso per i guadagni
in **Settings > Earnings collection** (Impostazioni > Raccolta dei guadagni).

## Mysterium { #mysterium }

L'importazione attiva Mysterium, ma CashPilot avvia un nuovo nodo con una nuova
identità. Il keystore del vecchio nodo e gli eventuali guadagni non ancora liquidati restano nella cartella
`mysterium-data` di InternetIncome. Liquidali prima, oppure segui la
[guida di Mysterium](../guides/mysterium.md) per portare con te l'identità.

## Sicurezza { #safety }

- Nulla nei file viene eseguito o espanso, e nessun indirizzo che contengono viene contattato.
- I file vengono letti una volta e non vengono conservati. Ciò che salvi viene archiviato cifrato, come
  ogni altra credenziale in CashPilot.
- Nella pagina i segreti compaiono solo come "impostato".
- Le importazioni salvate restano nella pagina di importazione finché non premi **Forget** (Dimentica), così puoi
  distribuirle su altri worker in seguito.
