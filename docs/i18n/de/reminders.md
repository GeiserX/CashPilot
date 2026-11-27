---
source_hash: b4ae1a3ae496
---
# Wartendes Geld: Erinnerungen, bevor du Einnahmen verlierst { #money-waiting-reminders-before-you-lose-earnings }

Manche Anbieter nehmen Geld zurück, das zu lange liegt. Ein Guthaben kann nach
Monaten ohne Aktivität verfallen. Ein Zeitfenster zum Abholen kann sich schließen. Ein Anbieter kann ein
Konto sperren, nicht mehr zahlen oder den Betrieb einstellen, während dein Guthaben noch dort liegt.
CashPilot liest bereits das meiste, was es braucht, um das kommen zu sehen. Das
Panel **Money waiting** (Wartendes Geld) auf dem Dashboard zeigt, was zu tun ist und bis wann, und
deine Benachrichtigungskanäle bekommen vor jeder Frist eine Push-Nachricht.

CashPilot holt oder zahlt nie etwas für dich ab oder aus. Jede Erinnerung verlinkt auf
die eigene Seite des Anbieters, und dort handelst du.

## Woran es dich erinnert { #what-it-reminds-you-about }

**Regeln aus den eigenen Bedingungen des Anbieters.** Jede Regel zitiert die Bedingungen oder
die Hilfeseite des Anbieters und das Datum, an dem sie zuletzt jemand gelesen hat. Der Link **Source** (Quelle) im
Menü **More** (Mehr) der Zeile öffnet sie.

| Dienst | Erinnerung | Wann |
|---|---|---|
| Grass | Hol deine Stage-2-USDC ab | Bis 22. Jan. 2027. Grass behält, was nicht abgeholt wird. |
| MystNodes | Hol die Belohnungen des letzten Monats ab | Innerhalb von 30 Tagen nach jeder monatlichen Verteilung |
| Honeygain | Zahl dein Guthaben aus | 24 Monate, nachdem es erstmals $20 erreicht hat |
| Honeygain | Lass ein Gerät weiter teilen oder mach eine Auszahlung | 6 Monate nach der letzten Aktivität oder Auszahlung |
| Repocket | Lass ein Gerät weiter teilen oder zahl aus | 12 Monate nach der letzten Aktivität oder Auszahlung |
| Bitping | Zahl dein Guthaben aus | 12 Monate nach der letzten Auszahlung |
| Salad | Verdien ein paar Reward Points oder gib dein Guthaben aus | 12 Monate, nachdem das Guthaben zuletzt gewachsen ist. Wenn du einen Teil davon ausgibst, setzt das die Frist nicht zurück. |

**Auszahlung.** CashPilot sagt dir, wenn ein Guthaben die Mindestauszahlung des Anbieters
erreicht. Das gilt für jeden Dienst, von dem es erfasst, außer für Dienste, die
von sich aus auszahlen. Ein Guthaben muss außerdem mindestens $5 wert sein, damit ein Anbieter
mit 5 Cent Minimum nicht schon beim ersten Cent nervt. Ist die Mindestauszahlung des Anbieters
höher, gilt die des Anbieters. Kann CashPilot das Minimum oder das Guthaben nicht
umrechnen, zeigt es nichts an. Es rät nie, dass du auszahlen kannst.

**Ablauf von Zugangsdaten.** Du bekommst eine Push-Nachricht, bevor ein gespeichertes Token oder Cookie abläuft.
CashPilot verwendet das Ablaufdatum, das die Zugangsdaten selbst angeben. Geben sie
keines an, verwendet CashPilot die übliche Lebensdauer dieser Art von Zugangsdaten, gezählt
ab dem Tag, an dem du sie gespeichert hast. Eigentümer sehen das bereits unter **Needs attention** (Braucht Aufmerksamkeit),
mit einer Schaltfläche **Renew** (Erneuern), daher wiederholt das Panel es nicht. Nur Eigentümer bekommen
Erinnerungen zu Zugangsdaten von der API, genau wie bei der Prüfung der Zugangsdaten.
Zugangsdaten, die der Anbieter abgelehnt hat, stehen bereits in der Glocke und wurden bereits per Push gemeldet,
daher kommt keine weitere Push-Nachricht.

## Welche Dienste es abdeckt { #which-services-it-covers }

Eine Erinnerung gilt für einen Dienst, den du nutzt: einen bereitgestellten, einen, den du
in **Settings** (Einstellungen) als extern eingerichtet hast, oder eine App, die ein Telefon meldet. Ein Dienst, den du entfernt hast,
zählt weiter, solange er ein Guthaben hält, denn die Inaktivitätsfristen beginnen,
wenn er aufhört. Eigene Dienste und eingestellte Dienste bekommen keine Erinnerungen.

## Daten und „oder früher“ { #dates-and-or-earlier }

Die Aktivitätsfristen zählen ab dem, was CashPilot aufgezeichnet hat:

- dem letzten Mal, als das Guthaben gewachsen ist,
- der letzten Auszahlung,
- oder dem ersten Messwert auf oder über dem Minimum.

Manchmal hat die Frist vor dem ersten Messwert von CashPilot begonnen. Dann kann die echte
Frist früher enden, als CashPilot sehen kann, und die Zeile sagt
„bis 3. Okt. 2027 oder früher“.

CashPilot löscht die Einnahmenhistorie nach 400 Tagen, und die Frist bei Honeygain
läuft 730 Tage. Daher speichert CashPilot jeden Fristbeginn, sobald es ihn zum ersten Mal
sieht, und behält ihn, auch wenn die Historie dahinter weg ist. Eine Auszahlung setzt
die Frist zurück, außer wo der Anbieter nur Verdienen zählt. Salad ist so ein Fall: Eine
Auszahlung, die ein Guthaben übrig lässt, setzt seine 12 Monate nicht zurück.

Ein festes Datum verschwindet am Tag nach seinem Ablauf, denn das Geld ist weg.
Eine überfällige Frist bleibt und sagt, dass der Anbieter das Geld möglicherweise
schon abgeschrieben hat. Sie bleibt, bis du sie als erledigt markierst oder stummschaltest oder bis eine Auszahlung
sie zurücksetzt.

## Was du mit einer Erinnerung tun kannst { #what-you-can-do-with-a-reminder }

Eigentümer und Bearbeiter sehen die Schaltflächen. Betrachter sehen nur die Erinnerungen. Nur Eigentümer
können auf eine Erinnerung zu Zugangsdaten reagieren.

- **Done** (Erledigt), oder **Requested** (Angefordert) bei einer Auszahlung, blendet diese Erinnerung aus. Ein monatliches
  Zeitfenster kommt nächsten Monat wieder. Eine Auszahlung kommt nach 14 Tagen einmal wieder, wenn
  das Guthaben noch da ist, und fragt, ob die Auszahlung angekommen ist. Das liegt
  innerhalb der 60-tägigen Reklamationsfrist, die die meisten Anbieter gewähren.
- **Snooze** (Später erinnern) blendet sie für einen Tag oder eine Woche aus und hält ihre Push-Nachrichten zurück. Ein Snooze läuft nie
  über die letzte Warnung vor einer Frist hinaus.
- **Not for me** (Nicht für mich) im Menü **More** (Mehr) schaltet eine Erinnerung stumm oder jede Erinnerung
  eines Dienstes. Ein Beispiel: Honeygain im JumpTask-Modus, bei dem ein gleichbleibendes Guthaben
  normal ist. Stummgeschaltete Erinnerungen stehen unten im Panel, mit
  **Unmute** (Stummschaltung aufheben).

Der Haushalt teilt diese Entscheidungen. Markiert eine Person eine Erinnerung als erledigt, ist sie
für alle erledigt. Jede Entscheidung wird im Audit-Log mit dem Namen
der Person aufgezeichnet, die sie getroffen hat.

## Push-Nachrichten { #pushes }

Erinnerungen gehen an die Kanäle, die du für Warnungen eingestellt hast: ntfy, ein Webhook oder Telegram
([Konfiguration](configuration.md)). Ist kein Kanal eingestellt, ist das Panel der einzige
Ort, an dem sie erscheinen.

- Eine Push-Nachricht pro Warnung. Grass zum Beispiel meldet sich 60, 30, 7 und 1 Tag vor
  seinem Datum. Eine Erinnerung, die zum ersten Mal 5 Tage vor ihrem Datum auftaucht, meldet sich einmal, mit 5
  verbleibenden Tagen.
- Push-Nachrichten gehen nur zwischen 09:00 und 21:00 raus. CashPilot verwendet die Zeitzone des ersten Eigentümers
  aus **Settings** (Einstellungen), dann die `TZ` des Containers, dann UTC. Eine Warnung, die
  über Nacht fällig wird, geht bei der ersten Prüfung nach 09:00 raus.
- Sind mehr als 3 Push-Nachrichten auf einmal fällig, bekommst du stattdessen eine Zusammenfassung. Das
  passiert am Tag deines Upgrades, wenn jedes Guthaben über seinem Minimum
  gleichzeitig auftaucht.
- Eine Push-Nachricht enthält den Dienst, was zu tun ist, was du verlieren würdest, das Datum und den
  Link des Anbieters. Sie enthält nie ein Guthaben, eine Adresse, eine Geräte-ID oder einen
  Worker-Namen. ntfy-Topics können öffentlich sein.
- Webhook-Payloads enthalten `kind: "obligation"`, damit Home Assistant und ähnliche
  Werkzeuge sie weiterleiten können.

## Für Mitwirkende am Katalog { #for-catalog-contributors }

Regeln stehen in der YAML-Datei jedes Dienstes, unter `obligations:`.
`services/_schema.yml` dokumentiert die Felder. Füge eine Regel nur hinzu, wenn die
eigenen Bedingungen oder Dokumente des Anbieters sie nennen und wenn CashPilot das Signal sehen kann,
von dem sie abhängt. Der Link einer Regel muss auf der eigenen Domain des Dienstes liegen, denn es gibt gefälschte
Seiten zum Abholen genau für diese Dienste. CI schlägt bei einer ungültigen Regel fehl, und
bei einer datierten Regel, die mehr als 30 Tage abgelaufen ist.
