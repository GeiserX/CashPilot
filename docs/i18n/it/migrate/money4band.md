---
source_hash: 374e39e6eac9
---
# Passare da money4band { #moving-from-money4band }

CashPilot può leggere la configurazione di money4band e portare con sé i tuoi accessi ai servizi, così
non devi digitarli di nuovo. Controlli tutto prima che CashPilot lo salvi.

## Prima di iniziare { #before-you-start }

Ti servono l'account proprietario di CashPilot e almeno un worker di CashPilot sulla
macchina dove ora gira money4band, o su un'altra macchina.

Ferma money4band su una macchina prima di distribuire lì gli stessi servizi da
CashPilot. Due copie dietro un'unica connessione guadagnano come una sola, e lo stesso id del dispositivo
di EarnApp o ProxyRack non deve girare due volte. Usa **Stop apps stack** nel
menu di money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
oppure esegui `docker compose down` nella sua cartella. Se hai configurato istanze
proxy aggiuntive, ferma anche ognuna di esse.

## Quale file usare { #which-file-to-use }

Usa `config/user-config.json` nella tua cartella di money4band. money4band lo scrive
quando esegui **Setup Apps**, e contiene esattamente ciò che hai digitato. Il `.env`
accanto a esso viene generato da quel file e funziona anche lui, così come il `.env`
modificato a mano di money4band 3.x. Entrambi restano solo sul tuo disco: il
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
di money4band li elenca.

Preferisci il file JSON. In un `.env`, Docker Compose espande `$` nei valori
senza virgolette, quindi una password che contiene `$` non è quella che mostra il file. CashPilot non
tira a indovinare: ti chiede di digitare di nuovo quel valore.

## Come importare { #how-to-import }

1. Apri **Settings** (Impostazioni), poi **Import from another tool** (Importa da un altro strumento) (oppure vai a `/import`).
2. Aggiungi `user-config.json`, o incollane il testo. Lascia lo strumento su "Riconosci dai
   file", oppure scegli money4band.
3. Controlla la tabella. Spunta i servizi che vuoi e compila ogni valore segnato
   come mancante.
4. Premi **Save the ticked services** (Salva i servizi spuntati), poi distribuiscili sui tuoi worker dalla
   stessa pagina.

## Cosa viene importato { #what-comes-over }

I nomi dei campi vengono dal
[template user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
di money4band e i nomi del `.env` sono quelli che scrive il suo
[generatore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, per esempio `REPOCKET_APIKEY`).

| App di money4band | Servizio di CashPilot | Cosa viene importato |
|---|---|---|
| `earnapp` | EarnApp | id del dispositivo (`uuid`), così il tuo dispositivo collegato continua a guadagnare |
| `honeygain` | Honeygain | email, password |
| `iproyalpawns` | IPRoyal Pawns | email, password |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | email, chiave API |
| `earnfm` | Earn.fm | chiave API |
| `proxyrack` | ProxyRack | chiave API, UUID del dispositivo |
| `proxylite` | ProxyLite | id utente |
| `bitping` | Bitping | email, password |
| `mystnode` | Mysterium | attivato; vedi la nota su Mysterium più sotto |

Un'app che avevi disattivato in money4band compare senza spunta. Un'app disattivata che
contiene solo i segnaposto del template (`yourHONEYGAINMail`) ed elenchi di porte
viene esclusa, quindi un `user-config.json` mai toccato dà una tabella vuota.

Queste app sono elencate ma non vengono importate:

| App di money4band | Perché |
|---|---|
| `proxybase` | money4band esegue il vecchio client di ProxyBase con un id utente. CashPilot esegue quello attuale, che richiede l'Access Token di proxybase.org. |
| `urnetwork` | money4band conserva un token di sessione. CashPilot fa accedere URnetwork con la tua email e la tua password. |
| `grass` | Grass gira come estensione del browser. CashPilot si limita a seguirlo, con l'access token della dashboard di Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot li segue, ma non c'è nessun container da distribuire. |
| `packetshare`, `peer2profit`, `speedshare` | Non più disponibili. |

Qualsiasi altra app viene elencata come "CashPilot non ha questo servizio".

## Cosa non viene mai importato { #what-never-comes-over }

- **Nome del dispositivo.** CashPilot dà a ogni dispositivo il nome del worker su cui gira, così
  due worker non riportano mai lo stesso nome. I tuoi vecchi dispositivi restano elencati come
  offline nella dashboard di ogni fornitore finché non li rimuovi lì.
- **Proxy.** Aggiungi ciascuno nella sezione Proxies della pagina della flotta, poi esegui
  copie dei tuoi servizi tramite di esso; aggiungere un proxy da solo non avvia nulla.
  Neanche salvare un'importazione avvia nulla. Una copia via proxy richiede che lo stesso servizio
  sia prima distribuito sul worker, e distribuirlo lo esegue sulla connessione del worker stesso,
  quindi un servizio che non deve mai usare quella connessione va lasciato
  senza spunta. Vedi [Copie via proxy](../proxies.md).
- **Watchtower e notifiche.** CashPilot aggiorna i propri container.
- **La dashboard di money4band e le sue porte.**

## Monitoraggio dei guadagni { #earnings-tracking }

Per Honeygain, IPRoyal Pawns e Bitping l'accesso del container è anche l'accesso
all'account, quindi CashPilot compila anche le loro credenziali per i guadagni, a meno che tu
non le abbia già impostate nelle impostazioni. Per ogni altro servizio, aggiungi l'accesso per i guadagni
in **Settings > Earnings collection** (Impostazioni > Raccolta dei guadagni).

## Mysterium { #mysterium }

L'importazione attiva Mysterium, ma CashPilot avvia un nuovo nodo con una nuova
identità. Il keystore del vecchio nodo e gli eventuali guadagni non ancora liquidati restano nella cartella
`.data/mysterium-node` di money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Liquidali prima, oppure segui la
[guida di Mysterium](../guides/mysterium.md) per portare con te l'identità.

Un `.env` 3.x non può dire se eseguivi Mysterium: il suo template elenca sempre
la porta della dashboard. Da un file 3.x Mysterium non viene importato, quindi aggiungilo
dal catalogo se lo eseguivi.

## Sicurezza { #safety }

- Nulla nel file viene eseguito o espanso, e nessun indirizzo che contiene viene contattato.
- Il file viene letto una volta e non viene conservato. Ciò che salvi viene archiviato cifrato, come
  ogni altra credenziale in CashPilot.
- Nella pagina i segreti compaiono solo come "impostato".
- Le importazioni salvate restano nella pagina di importazione finché non premi **Forget** (Dimentica), così puoi
  distribuirle su altri worker in seguito.
