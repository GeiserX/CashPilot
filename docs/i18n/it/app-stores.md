---
source_hash: e99e2c0c80bb
---
# App store { #app-stores }

Puoi installare CashPilot dall'app store di diversi sistemi per server domestici.
Ogni scheda installa la dashboard (`drumsergio/cashpilot`) e il worker
(`drumsergio/cashpilot-worker`), che avvia e ferma i container dei
servizi. Solo i pacchetti CasaOS e Runtipi di questo repository installano
anche il socket proxy di Docker da `docker-compose.yml`, quindi il loro worker
non tiene mai il socket Docker grezzo. I template di Unraid, l'app di TrueNAS e
il pacchetto nella pull request aperta sull'app store di CasaOS montano ancora il
socket Docker direttamente nel worker.

Qualunque store usi, tieni la dashboard sulla tua LAN o VPN. Può comandare
il worker, e il worker pilota Docker sull'host. Dove il worker tiene
lui stesso il socket, questo equivale a root sull'host.

## Già pubblicato { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Cerca **CashPilot** nella scheda Apps e installa entrambi i template:
`cashpilot` (la dashboard) e `cashpilot-worker`. Imposta lo stesso
`CASHPILOT_API_KEY` su entrambi.

I template provengono da https://github.com/GeiserX/docker-templates e seguono
il tag d'immagine `latest`, quindi gli utenti di Community Applications ricevono ogni release
senza modifiche al template.

### TrueNAS SCALE { #truenas-scale }

CashPilot è nel train **community** di TrueNAS. Apri Apps, poi Discover Apps,
e cerca **CashPilot**.

La definizione dell'app è mantenuta in
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot e fissa
un digest d'immagine esatto. Sono i bot di TrueNAS a spostarla sulle nuove release, quindi può essere
qualche release indietro rispetto al CashPilot più recente.

## In attesa di revisione { #waiting-for-review }

### CasaOS { #casaos }

È aperta una pull request sull'app store di CasaOS:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Finché non viene accettata, installalo come app personalizzata: in CasaOS scegli App Store,
poi Custom Install, poi Import, e incolla il contenuto di
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Richiede CasaOS 0.4.5 o successivo: da quella release il suo gestore di app si basa su
Docker Compose 2.23, che legge dal file la policy del socket proxy.
Le versioni più vecchie la scartano, e allora il worker non riesce a raggiungere Docker.

Quel file fissa una release esatta. Prima di importarlo, imposta entrambi i tag d'immagine
(`drumsergio/cashpilot` e `drumsergio/cashpilot-worker`) sulla release più
recente da https://github.com/GeiserX/CashPilot/releases. La policy del proxy
nel file segue `main`; se la pagina di stato del worker dice che la sua policy è
superata, importa di nuovo il file.

## Pronto, non ancora inviato { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Il pacchetto è pronto in
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
ma non è ancora nell'app store di Runtipi. Per usarlo subito, aggiungilo a un app
store personalizzato che controlli tu, seguendo la documentazione di Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Non disponibile { #not-offered }

Umbrel richiede un design diverso del worker, perché le app di Umbrel raggiungono Docker
tramite un container Docker-in-Docker invece che con il socket dell'host. Non l'abbiamo
testato, quindi per ora non esiste un pacchetto per Umbrel.

Per qualsiasi altro sistema, usa `docker-compose.yml` dal repository, come in
[Primi passi](getting-started.md).
