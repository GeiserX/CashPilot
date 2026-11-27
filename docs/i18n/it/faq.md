---
source_hash: 915470497dbc
---
# Domande frequenti { #faq }

**La condivisione di banda è sicura?**

I servizi di condivisione di banda in genere fanno passare dalla tua connessione traffico legittimo (ricerche di mercato, verifica degli annunci, confronto dei prezzi, distribuzione di contenuti). Detto questo, stai condividendo il tuo indirizzo IP, quindi leggi con attenzione i termini di servizio e l'informativa sulla privacy di ogni servizio prima di registrarti. Per alcuni servizi è possibile eseguirli su un VPS invece che su un IP residenziale. **Questa non è una consulenza legale: informati presso i singoli servizi che intendi usare e, se serve, chiedi un parere legale indipendente sulla tua giurisdizione.**

**Quanto posso guadagnare?**

I guadagni variano molto in base alla posizione, al provider internet, al numero di dispositivi e ai servizi che esegui. La dashboard segue i tuoi guadagni reali nel tempo, così puoi ottimizzare la tua configurazione. Come indicazione di massima, e non come promessa, un server di casa che esegue da 10 a 15 servizi rende circa 30-100 $ al mese, e può rendere meno, fino a zero. Più server, o il calcolo su GPU, si aggiungono a questo.

**Posso eseguirlo su un VPS o un server cloud?**

Alcuni servizi richiedono un IP residenziale e non pagano (o bannano) gli IP di VPS/datacenter. Il catalogo indica "IP residenziale" tra ciò che richiedono. I servizi che funzionano su VPS sono un buon modo per crescere senza altro hardware in casa.

**Come vengono salvate le credenziali?**

Tutte le credenziali dei servizi sono cifrate a riposo nel database SQLite con una chiave Fernet salvata in `/data/.fernet_key`, che viene generata automaticamente al primo avvio. Il file del database sta nel volume Docker montato (`cashpilot_data:/data`). Le credenziali non vengono mai inviate da nessuna parte, se non ai container dei servizi stessi.

Nota che questa chiave è diversa da `CASHPILOT_SECRET_KEY`, che firma solo le sessioni di accesso.

### Fare il backup della chiave di cifratura { #backing-up-the-encryption-key }

Le tue credenziali si possono recuperare solo finché hai `/data/.fernet_key`. Se perdi quel file dovrai inserire di nuovo ogni credenziale, perché senza di esso non c'è modo di decifrare i valori salvati.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Il file ha sempre la precedenza sulla variabile d'ambiente, quindi impostare `CASHPILOT_ENCRYPTION_KEY` su un'istanza che ha già una chiave non cambia nulla ed è sicuro. Viene adottata solo quando non esiste un file della chiave, che è esattamente il caso del ripristino.

Se CashPilot non riesce proprio a scrivere la chiave su disco, perché `/data` non è scrivibile o non è montata, si rifiuta di avviarsi piuttosto che cifrare le tue credenziali con una chiave che sparisce al riavvio successivo. Imposta `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` se è davvero ciò che vuoi.

<a id="forgot-password"></a>

### Password o nome utente dimenticati { #forgot-password-or-username }

CashPilot non ha un ripristino via e-mail. Chi gestisce il server reimposta la password dalla console del container della UI di CashPilot. I tuoi servizi, i guadagni e le credenziali salvate non ne risentono: sono cifrati con `/data/.fernet_key`, non con la tua password.

Il comando `python -m app.users` richiede CashPilot 2.3 o successivo. Sulla 2.2 o precedenti fallisce con `No module named app.users`. Aggiorna prima: con Docker Compose, cambia i tag `drumsergio/cashpilot` e `drumsergio/cashpilot-worker` in `2.3` o successivo (un tag fissato come `2.2` o `2.2.9` resta su quella release), poi esegui `docker compose up -d` ([Aggiornare CashPilot](getting-started.md#updating-cashpilot)). Su Unraid, aggiorna il container.

1. Elenca gli account. Questo mostra anche un nome utente che hai dimenticato. I nomi utente distinguono maiuscole e minuscole.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Imposta una nuova password casuale per l'account. Sostituisci `alice` con il nome utente del passaggio 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Se c'è esattamente un proprietario puoi omettere il nome utente, e il comando reimposta quel proprietario. Se il nome utente inizia con `-`, mettici davanti `--`: `reset-password -- -alice`.

    Il comando stampa la nuova password una sola volta.

3. Se qualcun altro potrebbe aver avuto accesso all'account, riavvia subito il container della UI (`docker restart cashpilot-ui`). I browser ancora connessi come quell'utente vengono disconnessi solo dopo un riavvio. Se hai solo dimenticato la password, il riavvio è facoltativo.
4. Accedi con la nuova password, poi cambiala dal menu dell'avatar (in alto a destra), **Change password** (Cambia password).

Il nome del container dipende da come hai installato CashPilot:

| Installazione | Container della UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | un nome generato; lo mostra `docker ps` |

Anche Portainer, Unraid e CasaOS hanno un pulsante console per un container. Il comando non richiede input dal terminale, quindi funziona anche lì.

Per cambiare un nome utente:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Il nuovo nome segue la regola della registrazione: da 3 a 32 lettere, cifre, `_` o `-`. Esci e accedi di nuovo per vederlo.

**Dopo una sospetta compromissione**, per esempio un backup perso che contiene `/data/.secret_key`, reimpostare la password da solo non basta. Chi ha quella chiave può firmare un cookie di accesso valido, e un ripristino della password non lo ferma. Sostituisci la chiave, poi riavvia il container della UI. Il `&&` lo riavvia solo quando la nuova chiave è al suo posto; se il comando stampa un errore, risolvi prima quello:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Dopo il riavvio ogni browser viene disconnesso, e tutti accedono di nuovo con la loro password. Le credenziali salvate non ne risentono. Se hai impostato tu `CASHPILOT_SECRET_KEY`, il comando si rifiuta: metti invece un nuovo valore casuale in quella variabile e ricrea il container. Un `docker run` dall'immagine non vede quella variabile e non può rifiutarsi, quindi usa `docker exec` sul container della UI.

Una nuova chiave mette fine ai cookie falsificati, ma non a ciò che l'attaccante ha fatto mentre era dentro. Altri due passaggi:

1. Esegui `docker exec cashpilot-ui python -m app.users list`. Elimina dalla dashboard ogni account che non riconosci.
2. Se la copia persa conteneva tutta `/data`, cambia le password dei tuoi account presso i fornitori. `.fernet_key` e `cashpilot.db` insieme decifrano ogni credenziale salvata.

Se in seguito ripristini un backup fatto prima della rotazione, escludi il suo `.secret_key` ([Backup e ripristino](backup-restore.md#restore)), oppure ruota e riavvia di nuovo. Altrimenti la vecchia chiave ritorna. Il database ripristinato riporta anche gli account e le password che conteneva, quindi ripeti il controllo degli account e l'eventuale reimpostazione delle password.

**Se il container della UI non si avvia**, esegui il comando dalla stessa immagine sugli stessi dati. Prima trova la cartella dell'host che contiene la `/data` della UI. Funziona per un container fermo, e sia per un volume con nome sia per un bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Poi monta quella cartella e usa il tag d'immagine che esegui:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Controlla che l'elenco mostri i tuoi account, poi esegui la stessa riga con `reset-password alice` al posto di `list`.

Un percorso senza database dà un errore "no database", e lì il comando non crea né cambia nulla. Docker potrebbe comunque lasciare una cartella o un volume vuoto con quel nome; rimuovilo.

**Non** eliminare il volume dei dati: cancelleresti `/data/.fernet_key` e con essa ogni credenziale salvata. **Non** eliminare nemmeno righe dalla tabella `users`.

**Come rimuovo completamente CashPilot?**

`docker compose down -v` rimuove solo i container di CashPilot. I servizi che ha distribuito continuano a girare, e i loro dati, la rete con la barriera e una tabella del firewall restano. [Rimuovere completamente CashPilot](uninstall.md) rimuove tutto, dice cosa si perde per sempre e mostra come controllare che non sia rimasto nulla.

**E la sicurezza?**

Ogni servizio che CashPilot distribuisce gira nel proprio container con tutte le capability di Linux rimosse (alcuni servizi ne riaggiungono solo quelle che dichiarano) e con `--security-opt no-new-privileges` impostato, così un processo all'interno non può ottenere privilegi. I container non vedono il filesystem del tuo host oltre i volumi che un servizio dichiara. Su una nuova installazione il worker li separa anche con una barriera dalla tua LAN, dall'host, dalla tua tailnet e dai metadati del cloud, così raggiungono internet e nulla di locale ([Isolamento di rete](isolation.md)). Su Podman la barriera non è disponibile: le app di guadagno girano sulla rete predefinita di Podman, che può raggiungere la tua LAN, e la pagina della flotta lo segnala ([Isolamento di rete](isolation.md) elenca le opzioni). Un'installazione aggiornata da una release precedente alla 1.70 tiene le sue app di guadagno sul bridge predefinito di Docker, che può raggiungere la tua LAN, finché non fai clic su **Turn on isolation** (Attiva l'isolamento) nella pagina della flotta. Dalla 2.0.7 anche Mysterium gira dietro la barriera; un nodo distribuito fino alla 2.0.6 resta sulla rete dell'host finché non lo ridistribuisci ([Spostare il tuo nodo Mysterium dietro la barriera](mysterium-fence.md)). [Proteggere la rete di casa](home-network-security.md) spiega invece come mettere un firewall sul tuo bridge. Le credenziali dei servizi sono cifrate a riposo con la cifratura simmetrica Fernet. La UI non ha accesso a Docker. Con i file compose forniti il worker non riceve mai il socket Docker grezzo: raggiunge Docker tramite `cashpilot-socket-proxy`, che rifiuta i container privilegiati e i bind di `/` o del socket (a meno che tu non metta uno di questi, o una cartella sopra il socket, in `CASHPILOT_PROXY_BIND_MOUNTS` o `CASHPILOT_COMPOSE_DIR`: il proxy li accetta così come sono), e limita il worker ai container, ai volumi e alle reti con la sua etichetta di proprietario ([impostazioni di sicurezza predefinite](security-defaults.md)). I template di Unraid e l'app di TrueNAS montano ancora il socket grezzo nel worker, il che equivale a root sull'host ([app store](app-stores.md)).

Detto questo, nessuna configurazione è a prova di proiettile. Stai comunque eseguendo software di terzi che fa passare traffico esterno dalla tua rete. L'isolamento di Docker riduce molto la superficie di attacco rispetto a eseguire questi servizi direttamente sul tuo host, ma non elimina ogni rischio. Ti consigliamo di eseguire CashPilot su una macchina o una VLAN dedicata, di tenere aggiornati Docker e il sistema operativo dell'host, e di esaminare il codice open source di ogni servizio prima di distribuirlo.

**Cosa succede se il container di un servizio va in crash?**

CashPilot monitora di continuo l'integrità dei container. Se il container di un servizio esce in modo imprevisto, viene riavviato automaticamente. La dashboard mostra il tempo di attività e lo stato di integrità di ogni servizio in esecuzione.

**Il mio nodo Mysterium non si avvia dopo una ridistribuzione. Perché?**

La causa più comune è una porta del suo intervallo UDP già occupata da un altro programma sull'host. Docker deve riservare ogni porta dell'intervallo, quindi una sola porta occupata blocca l'avvio. [Scegliere l'intervallo di porte UDP](mysterium-fence.md#choosing-the-udp-port-range) spiega come scegliere un intervallo che resti libero.

**La mia copia via proxy è in esecuzione ma non guadagna nulla. Perché?**

Il proxy potrebbe rifiutarsi di connettersi ai server di quella app di guadagno, o permettere solo le porte 80 e 443. Il **Test** (Prova) di CashPilot controlla solo che il proxy raggiunga internet. [Sondare i server di un'app di guadagno attraverso il proxy](proxies.md#probe-an-earners-servers-through-the-proxy) mostra come controllare l'host e la porta dell'app di guadagno.

**Quali servizi sono pesanti, e dove dovrebbero girare?**

I nodi di archiviazione, i relay e le uscite VPN, e il lavoro su GPU consumano di più. [Dimensionare una macchina piccola](fleet.md#budgeting-a-small-box) li elenca e mostra come misurare ogni container prima di decidere.

<a id="worker-lost-docker"></a>

### Il worker ha perso Docker dopo un aggiornamento di Docker { #the-worker-lost-docker-after-a-docker-update }

**Cosa vedi.** Il worker resta online nella pagina della flotta, ma CashPilot non riesce ad avviare, fermare o aggiornare i suoi container. La pagina della flotta mostra **Docker unreachable** (Docker non raggiungibile) accanto al worker. Dopo 10 minuti il controllo di integrità del worker fallisce (`docker ps` mostra il worker come `unhealthy`). Dopo 30 minuti la campanella e le tue notifiche dicono che il worker non riesce a raggiungere Docker. `docker logs cashpilot-socket-proxy` mostra `upstream Docker socket unreachable`, e con un file compose attuale `docker ps` mostra il proxy come `unhealthy` entro circa 3 minuti. Le tue app di guadagno continuano a girare.

**Causa.** I file compose forniti montano il file del socket `/var/run/docker.sock` in `cashpilot-socket-proxy`. Un bind di un file tiene quel singolo file. Un aggiornamento di Docker (per esempio `unattended-upgrades` che installa un nuovo `docker-ce`) riavvia Docker, e Docker crea un nuovo file del socket nello stesso percorso. Con il live-restore di Docker attivo, il proxy continua a girare durante quel riavvio e tiene il vecchio file. Sul vecchio file non risponde più nessuno.

**Soluzione rapida.** Su quella macchina, riavvia il proxy:

```bash
docker restart cashpilot-socket-proxy
```

Il riavvio monta il nuovo socket, e il worker ritrova Docker al suo segnale di vita successivo. Non devi riavviare il worker. Su Unraid e TrueNAS è il worker stesso a tenere il socket, quindi riavvia il worker.

**Soluzione duratura.** Monta la cartella del socket, non il file del socket. Un bind di una cartella mostra subito un socket sostituito. Nel servizio `cashpilot-socket-proxy` del tuo file compose, sostituisci la riga `- /var/run/docker.sock:/var/run/docker.sock:ro` con il bind qui sotto, e aggiungi la riga `SOCKGUARD_UPSTREAM_SOCKET` al suo `environment`:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Poi esegui `docker compose up -d`. La stessa modifica funziona in `docker-compose.worker.yml` e `docker-compose.fleet.yml`. Compose legge quei file solo quando li nomini, quindi esegui `docker compose -f docker-compose.worker.yml up -d` o `docker compose -f docker-compose.fleet.yml up -d`, a meno che `COMPOSE_FILE` non nomini già il file.

- `recursive: disabled` è necessario. `/var/run` contiene altri mount, per esempio i namespace di rete di Docker sotto `/run/docker/netns` e `/run/user/...`. Un bind ricorsivo li porta tutti nel proxy. Un bind non ricorsivo mostra solo la cartella stessa.
- `SOCKGUARD_UPSTREAM_SOCKET` indirizza il proxy al nuovo percorso. Il blocco della policy e la sua impronta restano come sono, perché la variabile d'ambiente sovrascrive `upstream.socket` nella policy. Senza la variabile il proxy non si avvia (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` può tenere il suo bind del file. Si riavvia a ogni `docker compose up`, quindi riceve sempre il socket attuale. Se gli dai lo stesso bind della cartella, aggiungi `DOCKER_HOST=unix:///host-run/docker.sock` al suo `environment`. Il worker 2.8.4 e successivi leggono quella variabile. Non puntarla mai al socket del proxy: il migratore ha bisogno di quello dell'host.
- Il bind della cartella dà al proxy ogni socket in `/var/run`, non solo quello di Docker. Su un server tipico questo include il socket di systemd, D-Bus e i socket di strumenti come Tailscale o snapd. `read_only` non impedisce a un programma di connettersi a un socket, e il proxy gira come root. L'accesso al socket Docker dà già root sull'host, quindi un proxy compromesso guadagna poco che non avesse già. Se vuoi che il proxy tenga solo il socket Docker, mantieni il bind del file e riavvia il proxy dopo un aggiornamento di Docker: l'avviso descritto sopra ti dice quando.
- Richiede Docker Compose 2.30.0 o successivo. Le release più vecchie rifiutano l'intero file con `Additional property recursive is not allowed`. Esegui `docker compose version` per controllare. Debian 13 include Compose 2.26.1, quindi su Debian installa Compose dal repository di Docker. L'aggiornamento dall'app usa il proprio Compose 2.33, quindi legge il file modificato.
- Funziona solo su Linux. Docker Desktop su macOS e Windows mappa nella sua macchina virtuale solo `/var/run/docker.sock`. Lì, `/var/run` è una cartella del tuo Mac o PC, senza alcun socket Docker.
- Con Docker rootless il socket sta in `/run/user/<your uid>`, che è un mount separato. Usa quella cartella come `source`.
- Su Podman, mantieni il bind del file. Non abbiamo testato lì il bind della cartella.

I file distribuiti mantengono il bind del file, perché il bind della cartella richiede Compose 2.30 e Linux, e CashPilot supporta anche release di Compose più vecchie e Docker Desktop. Un file compose più recente che scarichi non contiene la tua modifica, quindi rifalla dopo aver sostituito il file.
