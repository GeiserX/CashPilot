---
source_hash: 7f8476aeb8b6
---
# Passare da CashFactory { #moving-from-cashfactory }

CashPilot può leggere il `.env` di CashFactory e portare con sé i tuoi accessi ai servizi, così
non devi digitarli di nuovo. Controlli tutto prima che CashPilot lo salvi.

## Prima di iniziare { #before-you-start }

Ti servono l'account proprietario di CashPilot e almeno un worker di CashPilot.

Ferma CashFactory su una macchina prima di distribuire lì gli stessi servizi da
CashPilot. Due copie dietro un'unica connessione guadagnano come una sola, e lo stesso id del dispositivo
di EarnApp non deve girare due volte. Esegui `docker compose down` nella cartella
di CashFactory. Il suo
[file compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
avvia anche tre container che montano il socket Docker: Portainer (riga 31)
e due container Watchtower (righe 141 e 264). Assicurati che siano spariti anche loro: `docker ps` non deve
elencarne nessuno.

## Quale file usare { #which-file-to-use }

Usa il file `.env` nella tua cartella di CashFactory, quello che hai compilato partendo
dall'[esempio](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose legge quel file, ed espande `$` nei valori che non sono tra
virgolette singole. Un valore così non è quello che mostra il file, quindi CashPilot ti chiede
di digitarlo di nuovo invece di tirare a indovinare.

## Come importare { #how-to-import }

1. Apri **Settings** (Impostazioni), poi **Import from another tool** (Importa da un altro strumento) (oppure vai a `/import`).
2. Aggiungi il file `.env`, o incollane il testo. Lascia lo strumento su "Riconosci dai
   file", oppure scegli CashFactory.
3. Controlla la tabella. Spunta i servizi che vuoi e compila ogni valore segnato
   come mancante.
4. Premi **Save the ticked services** (Salva i servizi spuntati), poi distribuiscili sui tuoi worker dalla
   stessa pagina.

## Cosa viene importato { #what-comes-over }

| App di CashFactory | Chiavi lette | Servizio di CashPilot | Cosa viene importato |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id del dispositivo, così il tuo dispositivo collegato continua a guadagnare |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, password |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, password |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, chiave API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id utente |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID del dispositivo |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | chiave API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | niente: non più disponibile |

Un valore che mostra ancora il segnaposto dell'esempio (`<email>`, `sdk-node-<md5sum>`)
conta come non impostato, e un servizio che ha solo segnaposto viene escluso dalla
tabella.

## Cosa non viene mai importato { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot dà a ogni dispositivo il nome del worker su cui gira, così
  due worker non riportano mai lo stesso nome. I tuoi vecchi dispositivi restano elencati come
  offline nella dashboard di ogni fornitore finché non li rimuovi lì.
- **Bitping.** CashFactory tiene l'accesso a Bitping in un volume Docker, non in
  `.env`, quindi l'importazione non ha nulla da leggere e non mostra nessuna riga per Bitping. Digita
  l'accesso nel modulo di distribuzione di Bitping.
- **Portainer e Watchtower.** CashPilot gestisce e aggiorna i propri
  container.

## Monitoraggio dei guadagni { #earnings-tracking }

Per Honeygain e IPRoyal Pawns l'accesso del container è anche l'accesso all'account,
quindi CashPilot compila anche le loro credenziali per i guadagni, a meno che tu non le abbia già impostate
nelle impostazioni. Per ogni altro servizio, aggiungi l'accesso per i guadagni in
**Settings > Earnings collection** (Impostazioni > Raccolta dei guadagni).

## Sicurezza { #safety }

- Nulla nel file viene eseguito o espanso, e nessun indirizzo che contiene viene contattato.
- Il file viene letto una volta e non viene conservato. Ciò che salvi viene archiviato cifrato, come
  ogni altra credenziale in CashPilot.
- Nella pagina i segreti compaiono solo come "impostato".
- Le importazioni salvate restano nella pagina di importazione finché non premi **Forget** (Dimentica), così puoi
  distribuirle su altri worker in seguito.
