---
source_hash: b4ae1a3ae496
---
# Soldi in attesa: promemoria prima di perdere guadagni { #money-waiting-reminders-before-you-lose-earnings }

Alcuni fornitori si riprendono i soldi che restano fermi troppo a lungo. Un saldo può scadere dopo
mesi senza attività. Una finestra per riscuotere può chiudersi. Un fornitore può bannare un
account, smettere di pagare o chiudere mentre il tuo saldo è ancora lì.
CashPilot legge già quasi tutto ciò che gli serve per vederli arrivare. Il
pannello **Money waiting** (Soldi in attesa) sulla dashboard mostra cosa fare ed entro quando, e
i tuoi canali di notifica ricevono una notifica push prima di ogni scadenza.

CashPilot non riscuote né preleva mai nulla al posto tuo. Ogni promemoria porta
alla pagina del fornitore, e sei tu ad agire lì.

## Di cosa ti avvisa { #what-it-reminds-you-about }

**Regole prese dai termini del fornitore.** Ogni regola cita i termini o la pagina di aiuto
del fornitore, e la data in cui qualcuno li ha letti l'ultima volta. Il link **Source** (Fonte) nel
menu **More** (Altro) della riga la apre.

| Servizio | Promemoria | Quando |
|---|---|---|
| Grass | Riscuoti i tuoi USDC della Stage 2 | Entro il 22 gen 2027. Grass tiene ciò che non viene riscosso. |
| MystNodes | Riscuoti le ricompense del mese scorso | Entro 30 giorni da ogni distribuzione mensile |
| Honeygain | Preleva il tuo saldo | 24 mesi dopo che ha raggiunto per la prima volta 20 $ |
| Honeygain | Tieni un dispositivo in condivisione, o fai un pagamento | 6 mesi dopo l'ultima attività o l'ultimo pagamento |
| Repocket | Tieni un dispositivo in condivisione, o preleva | 12 mesi dopo l'ultima attività o l'ultimo pagamento |
| Bitping | Preleva il tuo saldo | 12 mesi dopo l'ultimo prelievo |
| Salad | Guadagna qualche Reward Point, o spendi il tuo saldo | 12 mesi dopo l'ultima volta che il saldo è cresciuto. Spenderne una parte non azzera il conteggio. |

**Prelievo.** CashPilot ti avvisa quando un saldo raggiunge il minimo del
fornitore. Questo vale per ogni servizio da cui raccoglie, tranne i servizi che
pagano da soli. Un saldo deve anche valere almeno 5 $, così un fornitore
con un minimo di 5 centesimi non ti assilla al primo centesimo. Quando il minimo del
fornitore è più alto, vale il minimo del fornitore. Quando CashPilot non riesce a
convertire il minimo o il saldo, non mostra nulla. Non presume mai che
tu possa prelevare.

**Scadenza delle credenziali.** Ricevi una notifica push prima che un token o un cookie salvato scada.
CashPilot usa la data di scadenza indicata dalla credenziale stessa. Quando non ne indica
nessuna, CashPilot usa la durata abituale di quel tipo di credenziale, contata
dal giorno in cui l'hai salvata. I proprietari la vedono già sotto **Needs attention** (Richiede attenzione),
con un pulsante **Renew** (Rinnova), quindi il pannello non la ripete. Solo i proprietari ricevono
dall'API i promemoria sulle credenziali, come per il controllo di integrità delle credenziali.
Una credenziale che il fornitore ha rifiutato è già nella campanella e ha già avuto la sua notifica push,
quindi non viene notificata di nuovo.

## Quali servizi copre { #which-services-it-covers }

Un promemoria vale per un servizio che usi: uno distribuito, uno che hai impostato
come esterno nelle impostazioni, o un'app che un telefono segnala. Un servizio che hai rimosso
conta ancora finché ha un saldo, perché i conteggi di inattività partono
quando si ferma. I servizi personalizzati e i servizi dismessi non ricevono promemoria.

## Date e "o prima" { #dates-and-or-earlier }

I conteggi di attività partono da ciò che CashPilot ha registrato:

- l'ultima volta che il saldo è cresciuto,
- l'ultimo pagamento,
- oppure la prima lettura pari o superiore al minimo.

A volte il conteggio è partito prima della prima lettura di CashPilot. Allora la vera
scadenza può essere precedente a quella che CashPilot riesce a vedere, e la riga dice
"entro il 3 ott 2027 o prima".

CashPilot elimina lo storico dei guadagni dopo 400 giorni, e il conteggio di Honeygain
dura 730 giorni. Per questo CashPilot salva l'inizio di ogni conteggio la prima volta che
lo vede, e lo conserva anche quando lo storico che c'era dietro è sparito. Un pagamento azzera
il conteggio, tranne dove il fornitore conta solo i guadagni. Salad è uno di questi: un
pagamento che lascia un saldo non azzera i suoi 12 mesi.

Una data fissa scompare il giorno dopo che è passata, perché i soldi sono persi.
Un conteggio scaduto resta e dice che il fornitore potrebbe aver già cancellato
quei soldi. Resta finché non lo segni come fatto o lo silenzi, o finché un pagamento
non lo azzera.

## Cosa puoi fare con un promemoria { #what-you-can-do-with-a-reminder }

I proprietari e gli editor vedono i pulsanti. I visualizzatori vedono solo i promemoria. Solo i proprietari
possono agire su un promemoria sulle credenziali.

- **Done** (Fatto), oppure **Requested** (Richiesto) per un prelievo, nasconde questo promemoria. Una
  finestra mensile torna il mese dopo. Un prelievo torna una volta dopo 14 giorni se
  il saldo è ancora lì, e chiede se il pagamento è arrivato. Questo cade
  dentro la finestra di contestazione di 60 giorni che offre la maggior parte dei fornitori.
- **Snooze** (Posticipa) lo nasconde per un giorno o una settimana e trattiene le sue notifiche push. Un rinvio non
  va mai oltre l'ultimo avviso prima di una scadenza.
- **Not for me** (Non fa per me), nel menu **More** (Altro), silenzia un promemoria, o tutti i promemoria
  di un servizio. Un esempio: Honeygain in modalità JumpTask, dove un saldo fermo
  è normale. I promemoria silenziati sono elencati in fondo al pannello, con
  **Unmute** (Riattiva).

La famiglia condivide queste scelte. Quando una persona segna un promemoria come fatto, è
fatto per tutti. Ogni scelta viene registrata nel registro di controllo con il nome
della persona che l'ha fatta.

## Notifiche push { #pushes }

I promemoria vanno ai canali che hai impostato per gli avvisi: ntfy, un webhook o Telegram
([configurazione](configuration.md)). Senza un canale impostato, il pannello è l'unico
posto in cui compaiono.

- Una notifica push per ogni avviso. Per esempio, Grass invia notifiche 60, 30, 7 e 1 giorno prima
  della sua data. Un promemoria visto per la prima volta 5 giorni prima della sua data invia una sola notifica, con 5
  giorni rimasti.
- Le notifiche push partono solo tra le 09:00 e le 21:00. CashPilot usa il fuso orario del primo
  proprietario dalle impostazioni, poi il `TZ` del container, poi UTC. Un avviso
  raggiunto durante la notte parte al primo controllo dopo le 09:00.
- Quando più di 3 notifiche push sono dovute nello stesso momento, ricevi invece un solo riepilogo. Questo
  succede il giorno in cui aggiorni, quando ogni saldo oltre il suo minimo compare
  tutto insieme.
- Una notifica push riporta il servizio, cosa fare, cosa perderesti, la data e il
  link del fornitore. Non riporta mai un saldo, un indirizzo, un id del dispositivo o il
  nome di un worker. I topic di ntfy possono essere pubblici.
- I payload dei webhook riportano `kind: "obligation"`, così Home Assistant e strumenti
  simili possono instradarli.

## Per chi contribuisce al catalogo { #for-catalog-contributors }

Le regole stanno nel file YAML di ogni servizio, sotto `obligations:`.
`services/_schema.yml` documenta i campi. Aggiungi una regola solo quando i
termini o la documentazione del fornitore la dichiarano, e quando CashPilot può vedere il segnale da cui
dipende. Il link di una regola deve stare sul dominio del servizio stesso, perché esistono siti di
riscossione falsi proprio per questi servizi. La CI fallisce su una regola non valida, e
su una regola con data scaduta da più di 30 giorni.
