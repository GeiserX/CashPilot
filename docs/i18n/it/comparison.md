---
source_hash: 1a93abea95d7
---
# Come si confronta CashPilot { #how-cashpilot-compares }

Questa pagina confronta CashPilot con gli altri progetti aperti che eseguono diverse app di reddito passivo in Docker. Abbiamo controllato ogni progetto il 2026-11-04. Ogni cella su un altro progetto porta al file da cui proviene, a un commit fisso, così puoi verificarla tu stesso. Se una cella è sbagliata o non aggiornata, [apri una issue](https://github.com/GeiserX/CashPilot/issues).

## Progetti confrontati { #projects-compared }

| Progetto | Cosa abbiamo controllato | Stelle al 2026-11-04 | Licenza |
|---|---|---|---|
| [money4band][m4b-tree] | Release 5.0.0, commit del tag `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` a `65e900d` (2026-10-20), più ciò che il README afferma sul suo binario 3.0.0-beta.9 | 238 | Proprietaria, [licenza propria v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` a `db9338a` (2026-11-03) | 257 | Nessun file LICENSE. Il [README][ii-license] permette di copiare l'originale e vieta di distribuire copie modificate |
| [CashFactory][cf-tree] | `main` a `0ff4bd0` (2025-04-08) | 410 | Il file [LICENSE][cf-license-file] è GPL-3.0, ma il [README][cf-license] vieta di distribuire copie modificate |
| [home-assistant-passive-income][ha-tree] (add-on di HA) | Release 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Release v1.64.0, `main` a `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band ha due linee di codice. Il suo branch predefinito `main` (`3bfafb1`) contiene ancora il codice 4.x, e la sua ultima modifica al codice lì risale al 2026-03-03. La release 5.0.0 è costruita da una storia separata. Confrontiamo la 5.0.0 perché è ciò che distribuisce la sua ultima release.

La UI web, la gestione della flotta e il binario di installazione di IGM sono a codice chiuso e non sono nel suo repository. Dove una cella dipende da loro, dice "il README afferma" e porta alla riga del README. Tutto il resto della colonna di IGM viene dagli script shell e dai file compose del repo.

Esclusi: [earning-machine](https://github.com/jf-m/earning-machine) e [passiveMachine](https://github.com/Xpl0itU/passiveMachine) non hanno commit dal 2024. Una ricerca su GitHub non ha trovato nient'altro di mantenuto che esegua più di un'app, solo immagini per una singola app.

## In breve { #short-version }

- **InternetIncome, money4band, IGM e, dalla v1.69.0, CashPilot possono guadagnare su molti IP tramite proxy.** I primi tre eseguono ogni app una volta per proxy, e i proxy sono la funzione principale di InternetIncome. CashPilot esegue copie aggiuntive di un servizio già distribuito su un worker, ciascuna tramite un proxy SOCKS5, HTTP CONNECT o exit node di Tailscale ([copie via proxy](proxies.md)).
- **InternetIncome (23) avvia più app del worker di CashPilot (<!-- n:docker -->21<!-- /n -->); IGM ne avvia 20.** CashPilot segue più servizi in totale (<!-- n:live -->50<!-- /n -->) perché segue anche servizi come estensioni del browser, app desktop e GPU che non esegue. Dalla v1.64.0 può anche eseguire qualsiasi immagine che indichi come [servizio personalizzato](custom-services.md).
- **money4band e IGM riscuotono le ricompense giornaliere al posto tuo, e tengono aggiornate le immagini delle app con Watchtower.** CashPilot non fa né l'una né l'altra cosa. Scarica di nuovo un'immagine solo quando distribuisci o ridistribuisci.
- **CashPilot è l'unico qui che legge i saldi dai tuoi account presso i fornitori e ne tiene uno storico.** money4band 5.0.0 mostra stime dal proprio catalogo, non dai tuoi account. Gli altri portano alla dashboard di ogni fornitore.
- **CashPilot è l'unico open source qui con una sola UI per molti server.** Il README di IGM afferma di gestire una flotta, ma quel codice è nel suo binario chiuso.
- **Dalla v1.70.0, CashPilot è l'unico qui che tiene i container delle app di guadagno fuori dalla tua LAN per impostazione predefinita, con dei limiti.** È attivo per le nuove installazioni e per le installazioni aggiornate senza app di guadagno sul bridge predefinito di Docker. Un'installazione aggiornata le cui app di guadagno stanno già su quel bridge le lascia lì finché non attivi l'isolamento, e una rete che indichi in `CASHPILOT_CONTAINER_NETWORK` non riceve nessuna barriera da CashPilot ([isolamento](isolation.md#modes)). Dalla 2.0.7 anche Mysterium gira dietro la barriera; un nodo distribuito fino alla 2.0.6 resta sulla rete dell'host, senza barriera, finché non lo ridistribuisci ([Mysterium dietro la barriera](mysterium-fence.md)).

## Fianco a fianco { #side-by-side }

La colonna di CashPilot descrive la v1.64.0, tranne le righe sul proxy, sul socket Docker e sull'isolamento dalla LAN, che descrivono la v1.71.1 (`0170dee`, 2026-11-06), e la rete di Mysterium nelle righe sulle impostazioni dei container e sull'isolamento dalla LAN, che descrive la release successiva alla 2.0.6 (`01e7310`). La riga sulle chiamate in uscita include le chiamate agli explorer della [guida on-chain attuale](onchain.md). Le altre colonne descrivono i commit della tabella qui sopra.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Add-on di HA |
|---|---|---|---|---|---|---|
| App che può avviare (vedi [come abbiamo contato](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> eseguite dal worker, più [immagini personalizzate](custom-services.md); <!-- n:live -->50<!-- /n --> seguite in totale | 15 ([catalogo][m4b-catalog]). Il README dice 35, che [include][m4b-readme-35] app della community e app abbandonate | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([file compose][cf-compose]) | 10 ([cartelle degli add-on][ha-tree]) |
| Come si installa | Docker Compose: una UI più un worker su ogni server; il worker avvia le app di guadagno tramite l'API di Docker ([flotta](fleet.md)) | CLI Python o un binario precompilato che scrive un file compose ([release][m4b-tree]) | Installatore `curl \| sh` ([README][igm-install]) che scarica un binario chiuso, verificato solo con un file SHA256SUMS della stessa release ([installatore][igm-installer-sums]) | Un solo script bash di 1.608 righe che chiama `sudo docker run` ([script][ii-script]) | Un file compose statico più `setup.sh` eseguito con sudo ([setup][cf-setup]) | Un repository di add-on di Home Assistant; richiede Home Assistant OS o Supervised |
| Molti server, una sola vista | Sì ([flotta](fleet.md)) | No, uno stack per dispositivo | Il README afferma di sì, nel binario chiuso ([README][igm-features]) | No | No | No |
| Molti proxy o IP | Sì, dalla v1.69.0: copie aggiuntive di un servizio distribuito, ciascuna tramite un proxy SOCKS5, HTTP CONNECT o exit node di Tailscale. SOCKS5 e HTTP CONNECT trasportano solo TCP (il tunnel fa uscire solo TCP verso la porta del proxy, quindi i relay UDP di SOCKS5 vengono scartati); un exit node di Tailscale trasporta anche UDP. L'app di guadagno condivide il namespace di rete di un container tunnel il cui firewall fa uscire solo il loopback, il tunnel e la connessione del tunnel stesso al proxy (TCP verso il suo indirizzo e la sua porta, o i pacchetti marcati di tailscaled), così un proxy morto la ferma invece di farla trapelare ([copie via proxy](proxies.md#how-it-works), [codice][cp-proxy-deploy], [firewall del tunnel][cp-tunnel-fw]). I servizi che richiedono la rete dell'host, porte pubblicate, volumi, dispositivi o `NET_ADMIN`, `NET_RAW` o `SYS_ADMIN` non possono girare tramite un proxy ([copie via proxy](proxies.md#what-cannot-run-through-a-proxy)) | Sì ([README][m4b-features], [codice][m4b-multiproxy]) | Sì ([README][igm-features], [compose][igm-proxy]) | Sì, è la sua funzione principale ([README][ii-readme-top]) | No | No |
| Guadagni | <!-- n:collectors -->20<!-- /n --> collettori leggono i saldi dagli account presso i fornitori e ne tengono uno storico. Alcuni richiedono un cookie o un token copiato dal browser, e alcuni di questi scadono (vedi la guida di ogni servizio) | Stime da intervalli del catalogo, non dati degli account ([codice][m4b-earnings]) | Nessuno trovato negli script | Nessuno | Nessuno | Nessuno |
| Pagamenti | Propone un pagamento quando un saldo scende, e lo registra quando confermi ([schema][cp-payouts]) | Nessuno | Nessuno | Nessuno | Nessuno | Nessuno |
| Riscossione delle ricompense giornaliere | No | Sì, con sidecar ([README][m4b-features]) | Sì ([README][igm-features], [compose][igm-sidecars]) | No | No | No |
| Credenziali a riposo | Cifrate (Fernet) nel database della UI; il file della chiave sta nello stesso volume dei dati ([codice][cp-fernet]). Le credenziali delle app di guadagno arrivano a ogni worker come variabili d'ambiente del container, quindi sono in chiaro nella configurazione Docker di quel worker (`docker inspect`) | Cifrate (Fernet); il file della chiave sta nella directory dei dati ([codice][m4b-crypto]) | Cifrate (AES-256 con openssl); il file della chiave sta accanto al vault ([codice][igm-encryptor]) | In chiaro in `properties.conf`; alcune password vengono passate come argomenti di `docker run` ([script][ii-password-arg]) | In chiaro in `.env` ([file][cf-env]) | Opzioni dell'add-on, salvate dal Supervisor in `/data/options.json` ([documentazione di HA][ha-options]) |
| Impostazioni dei container delle app di guadagno | Tutte le capability rimosse, poi il catalogo riaggiunge ciò che serve a un servizio; `no-new-privileges`; un limite di pid; privilegiati rifiutati ([codice][cp-hardening], [codice][cp-privileged]). Mysterium gira nel proprio namespace di rete sul bridge con la barriera, con `NET_ADMIN`, `SETUID` e `SETGID`, su un'immagine fissata per digest ([catalogo][cp-myst]) | `no-new-privileges` su ogni servizio non privilegiato ([codice][m4b-nnp]); il container del proxy è privilegiato con `NET_ADMIN` ([template][m4b-tun]) | Niente impostato sui servizi delle app; Mysterium riceve `NET_ADMIN` ([compose][igm-hosting-myst]); il container del proxy riceve `NET_ADMIN`, con `no-new-privileges` e un limite di pid ([compose][igm-proxy]) | Ebesucher gira con `seccomp=unconfined` ([script][ii-seccomp]); i container dei proxy e Mysterium ricevono `NET_ADMIN` | Niente impostato | Nessun add-on chiede modalità privilegiata, rete dell'host o accesso all'API di Docker ([configurazione di esempio][ha-config]) |
| Socket Docker montato in | Dalla v1.71.0, un socket proxy (sockguard 2.4.5, fissato per digest), in sola lettura. Il worker riceve una copia filtrata che rifiuta i container privilegiati, i bind di `/` o del socket, e le capability o i dispositivi fuori da quelli del catalogo ([compose][cp-sock], [dettagli](security-defaults.md)); mai un'app di guadagno ([codice][cp-mounts]) | Watchtower ([template][m4b-watchtower]) | Watchtower, che è in sola lettura con `no-new-privileges` ([compose][igm-watchtower]) | Cinque container di supporto per i riavvii ([script][ii-sock-helper]) e Watchtower ([script][ii-watchtower]) | Portainer, pubblicato sulle porte 8000, 9000 e 9443 su tutte le interfacce ([compose][cf-portainer]), e due Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Nessuno |
| Tag delle immagini | 9 delle <!-- n:docker -->21<!-- /n --> immagini delle app di guadagno sono fissate a una versione o a un digest; le altre sono mobili | Tutte le 15 immagini delle app usano `:latest` ([esempio][m4b-image]); container del proxy fissato alla v2.6.0, Watchtower a `:1` | Nessun tag, quindi Docker usa `latest` ([compose][igm-hosting]); un tag è impostato solo per alcune build ARM | Per lo più `:latest` ([esempio][ii-seccomp]); EarnApp `:lite`, Honeygain fissato alla 0.6.6 quando passa da proxy su amd64 ([script][ii-honeygain]), tag per architettura di Traffmonetizer su ARM; Watchtower `:nightly` | `:latest` o nessun tag, tranne EarnApp `:lite` ([compose][cf-compose]) | Una versione per add-on, aggiornata da un job di CI giornaliero ([workflow][ha-bump], [esempio][ha-dockerfile]) |
| Aggiornamenti delle immagini delle app | Scaricate di nuovo a ogni distribuzione o ridistribuzione; nessun aggiornatore automatico | Watchtower ([template][m4b-watchtower]) | Watchtower ogni 4 ore ([compose][igm-watchtower]) | Watchtower una volta al giorno, se lo attivi ([script][ii-watchtower]) | Due Watchtower, ciascuno limitato a un'app, PacketStream ([compose][cf-watchtower-ps]) ed EarnFM ([compose][cf-watchtower-efm]); le altre 9 app non vengono aggiornate | Gli aggiornamenti degli add-on di Home Assistant |
| Isolamento dalla LAN | Attivo per impostazione predefinita dalla v1.70.0 per le nuove installazioni e per le installazioni aggiornate senza app di guadagno sul bridge predefinito di Docker: il worker mette le app di guadagno su un bridge proprio e scrive una tabella del firewall che scarta gli intervalli privati, l'intervallo della tailnet, i metadati del cloud, le sottoreti connesse dell'host, l'host stesso e, con il rilevamento dell'IP pubblico attivo, l'IP pubblico di casa ([isolamento](isolation.md#lan-isolation-by-default), [codice][cp-fence]). Un'installazione aggiornata le cui app di guadagno stanno già sul bridge predefinito resta lì finché non premi **Turn on isolation** (Attiva l'isolamento); `CASHPILOT_ISOLATION=off` lo disattiva; con `CASHPILOT_CONTAINER_NETWORK` impostato, CashPilot non scrive nessuna barriera per quella rete e le regole del firewall sono compito tuo ([isolamento](isolation.md#modes), [codice][cp-fence-mode]). Dalla 2.0.7 anche Mysterium ha la barriera; un nodo distribuito fino alla 2.0.6 resta sulla rete dell'host finché non lo ridistribuisci ([Mysterium dietro la barriera](mysterium-fence.md)). Un controllo mostra cosa possono raggiungere le app di guadagno ([controllo](isolation-check.md)) | Sottorete bridge propria ([config][m4b-subnet]), che non blocca la LAN | Nessuno integrato | Nessuno trovato | Nessuno trovato | Nessuno trovato |
| ARM | UI e worker arm64; controlla le piattaforme di ogni servizio prima di una distribuzione ([ARM](arm.md)) | Binari arm64 e armv7 ([release][m4b-release]) | Il README afferma amd64 e arm64, arm32 con limiti, e configura QEMU ([README][igm-arch]) | Richiede l'emulazione binfmt per le immagini solo amd64 ([README][ii-arm]) | Il README dice che non funziona su un Raspberry Pi ([README][cf-raspberry]) | Per add-on; ProxyRack è solo amd64 ([config][ha-proxyrack]) |
| UI | UI web, più client Desktop, Android, MCP e Home Assistant | CLI, menu e una dashboard web locale collegata a 127.0.0.1 per impostazione predefinita ([codice][m4b-bind]) | CLI, menu e, secondo il README, una UI web sulla porta 4747 raggiungibile dalla LAN ([README][igm-webui]) | Nessuna, è uno script | Una pagina di segnalibri sulla porta 80 più Portainer ([README][cf-ui]) | Il pannello degli add-on di Home Assistant |
| Commit sul branch predefinito, dal 2026-08-06 al 2026-11-04 | 286 | 6, tutti di documentazione (la 5.0.0 è su una storia separata) | 6 | 31 | 0 | 23 |
| Ultima release | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Nessuna release con versione | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Chiamate in uscita oltre alle app | Release di GitHub una volta al giorno (`CASHPILOT_UPDATE_CHECK=off` le ferma, [codice][cp-update]); `api.ipify.org`, `ifconfig.me` o `icanhazip.com` una volta all'ora da ogni worker, per il suo IP pubblico (`CASHPILOT_EGRESS_DETECT=off` le ferma, [codice][cp-egress]); CoinGecko e Frankfurter per i tassi di cambio ([codice][cp-rates]); mempool.space, api.kaspa.org e nodi RPC pubblici di Ethereum, Polygon e Solana per i [saldi on-chain](onchain.md); ogni fornitore, per i collettori. Il browser carica Google Fonts ([template][cp-cdn]) e Chart.js da jsDelivr ([template][cp-chartjs]) | Release di GitHub, per il suo controllo degli aggiornamenti ([codice][m4b-updater]); Docker Hub e ghcr.io, per controllare i tag delle immagini ([codice][m4b-registry]); quando esegui il controllo dell'IP, `api.ipify.org`, `ifconfig.me` o `icanhazip.com` per il tuo IP pubblico e `ip-api.com` su HTTP semplice per i punteggi degli IP ([codice][m4b-ipscore]) | Release di GitHub ([codice][igm-version]); `api.ipify.org`, `ifconfig.me` o `icanhazip.com` per il tuo IP pubblico ([codice][igm-ifconfig]); `ip-api.com` su HTTP semplice per i punteggi degli IP ([codice][igm-ipscore]). Il binario chiuso non è stato controllato | Nessuna trovata | Nessuna trovata | Nessuna trovata |

Nessuno dei progetti invia telemetria d'uso nel codice che abbiamo letto. Il binario chiuso di IGM non si è potuto leggere.

Ogni progetto qui passa le credenziali delle app ai container come variabili d'ambiente, e InternetIncome ne passa alcune anche come argomenti dei comandi, quindi sull'host che esegue le app sono in chiaro nella configurazione dei container di Docker (`Env` e `Args` in `docker inspect`), leggibili da chiunque abbia accesso a Docker. La riga "Credenziali a riposo" descrive solo la copia salvata.

## Come abbiamo contato { #how-we-counted }

- **CashPilot.** I servizi del catalogo con stato active o beta e un'immagine Docker, senza contare il calcolo su GPU e i pool di mining. Il numero in questa pagina viene da `scripts/generate_readme_tables.py`, e la CI fallisce se si discosta.
- **money4band 5.0.0.** Un file JSON per app in `config/catalog/supported/`: 15. Le "35 app" del README contano anche il catalogo della community, che è disattivato per impostazione predefinita ([config][m4b-community]), app senza immagine Docker e app abbandonate.
- **IGM.** Voci in `apps.json`: 20, tutte attive. Il container del proxy, Watchtower e i sidecar di riscossione non sono contati.
- **InternetIncome.** Ogni blocco di commento `# Starting ... container` in `internetIncome.sh`, a parte i blocchi del proxy e di Watchtower: 24. I blocchi Chrome e Firefox di Ebesucher sono un'unica app, e lo stesso vale per EarnFM ed EarnFM Fleetshare, che usano lo stesso account EarnFM. Il blocco delle estensioni Depin avvia Grass e Gradient ([script][ii-depin]), due app. Totale 23. La tabella del README elenca 27 app, alcune solo con un link di registrazione.
- **CashFactory.** Servizi di guadagno in `docker-compose.yml`: 11. Portainer, il server web e i due Watchtower non sono contati. Un servizio è commentato.
- **Add-on di HA.** Cartelle di add-on con un file di configurazione: 10.

Non abbiamo controllato se ogni app di ogni elenco paga ancora.

## Dove CashPilot è indietro { #where-cashpilot-is-behind }

- I servizi che richiedono la rete dell'host, porte pubblicate, volumi, dispositivi o capability di rete extra non possono girare tramite un proxy, quindi 10 delle <!-- n:docker -->21<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi e Kryptex Pool (Pearl)) guadagnano solo dall'IP del server stesso ([copie via proxy](proxies.md#what-cannot-run-through-a-proxy)).
- Meno app avviate direttamente rispetto a InternetIncome.
- Nessuna riscossione delle ricompense giornaliere e nessun aggiornamento automatico delle immagini.
- 12 delle <!-- n:docker -->21<!-- /n --> immagini delle app di guadagno seguono il tag più recente del loro editore.
- Il socket proxy non è ancora un confine di root: un worker compromesso può ancora creare container entro la sua policy, e le evasioni in due passaggi (entrare nel namespace dei processi di un altro container, un link simbolico in una cartella consentita) non vengono rifiutate ([dettagli](security-defaults.md)).
- La chiave di cifratura delle credenziali salvate sta nello stesso volume dei dati, e su ogni worker le credenziali delle app di guadagno sono in chiaro nella configurazione dei container di Docker.
- Alcuni collettori richiedono un cookie o un token copiato dal browser, e alcuni di questi scadono, quindi il monitoraggio dei guadagni richiede manutenzione per quei servizi.
- La UI carica i font e Chart.js da CDN di terzi.
- L'isolamento dalla LAN resta disattivato su un'installazione aggiornata le cui app di guadagno stanno sul bridge predefinito di Docker finché non lo attivi, non dà nessuna barriera a una rete indicata in `CASHPILOT_CONTAINER_NETWORK` ([isolamento](isolation.md#modes)), e un nodo Mysterium distribuito fino alla 2.0.6 resta sulla rete dell'host, senza barriera, finché non lo ridistribuisci ([Mysterium dietro la barriera](mysterium-fence.md)).
- Una community molto più piccola di quella di money4band.
- Esce con nuove release spesso, a volte più volte al giorno.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
