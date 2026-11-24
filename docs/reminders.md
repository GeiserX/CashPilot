# Money waiting: reminders before you lose earnings

Some providers take back money that sits too long. A balance can expire after
months with no activity. A claim window can close. A provider can ban an
account, stop paying or shut down while your balance is still there.
CashPilot already reads most of what it needs to see these coming. The
**Money waiting** panel on the dashboard shows what to do and by when, and
your notification channels get a push before each deadline.

CashPilot never claims or withdraws anything for you. Each reminder links to
the provider's own page, and you act there.

## What it reminds you about

**Rules from the provider's own terms.** Each rule cites the provider's terms
or help page, and the date someone last read it. The **Source** link in the
row's **More** menu opens it.

| Service | Reminder | When |
|---|---|---|
| Grass | Claim your Stage 2 USDC | By 22 Jan 2027. Grass keeps what is not claimed. |
| MystNodes | Claim last month's rewards | Within 30 days of each monthly distribution |
| Honeygain | Withdraw your balance | 24 months after it first reached $20 |
| Honeygain | Keep a device sharing, or make a payout | 6 months after the last activity or payout |
| Repocket | Keep a device sharing, or withdraw | 12 months after the last activity or payout |
| Bitping | Withdraw your balance | 12 months after the last withdrawal |
| Salad | Earn some Reward Points, or spend your balance | 12 months after the balance last grew. Spending part of it does not reset this. |

**Cash-out.** CashPilot tells you when a balance reaches the provider's
minimum. This applies to every service it collects from, except services that
pay out by themselves. A balance must also be worth at least $5, so a provider
with a 5-cent minimum does not nag at the first cent. When the provider's
minimum is higher, the provider's minimum applies. When CashPilot cannot
convert the minimum or the balance, it shows nothing. It never guesses that
you can withdraw.

**Credential expiry.** You get a push before a saved token or cookie expires.
CashPilot uses the expiry date the credential itself states. When it states
none, CashPilot uses the usual lifetime of that kind of credential, counted
from the day you saved it. Owners already see it under **Needs attention**,
with a **Renew** button, so the panel does not repeat it. Only owners get
credential reminders from the API, the same as the credential health check.
A credential the provider rejected is already in the bell and already pushed,
so it does not push again.

## Which services it covers

A reminder applies to a service you use: one that is deployed, one you set up
as external in Settings, or an app a phone reports. A service you removed
still counts while it holds a balance, because the inactivity clocks start
when it stops. Custom services and discontinued services get no reminders.

## Dates and "or earlier"

The activity clocks count from what CashPilot recorded:

- the last time the balance grew,
- the last payout,
- or the first reading at or above the minimum.

Sometimes the clock started before CashPilot's first reading. Then the real
deadline may be earlier than CashPilot can see, and the row says
"by 3 Oct 2027 or earlier".

CashPilot deletes earnings history after 400 days, and the Honeygain clock
runs for 730 days. So CashPilot stores each clock start the first time it
sees one, and keeps it after the history behind it is gone. A payout resets
the clock, except where the provider counts earning only. Salad is one: a
payout that leaves a balance does not reset its 12 months.

A fixed date drops off the day after it passes, because the money is gone.
An overdue clock stays and says the provider may already have written the
money off. It stays until you mark it done or mute it, or until a payout
resets it.

## What you can do with a reminder

Owners and writers see the buttons. Viewers see the reminders only.

- **Done**, or **Requested** for a withdrawal, hides this reminder. A monthly
  window comes back next month. A withdrawal comes back once after 14 days if
  the balance is still there, and asks whether the payout arrived. That is
  inside the 60-day dispute window most providers give.
- **Snooze** hides it for a day or a week and holds its pushes. A snooze never
  runs past the last warning before a deadline.
- **Not for me**, in the **More** menu, mutes one reminder, or every reminder
  of a service. One example: Honeygain in JumpTask mode, where a flat balance
  is normal. Muted reminders are listed at the foot of the panel, with
  **Unmute**.

The household shares these choices. When one person marks a reminder done, it
is done for everyone. Each choice is recorded in the audit log with the name of
the person who made it.

## Pushes

Reminders go to the channels you set for alerts: ntfy, a webhook or Telegram
([configuration](configuration.md)). With no channel set, the panel is the only
place they show.

- One push per warning. For example, Grass pushes 60, 30, 7 and 1 day before
  its date. A reminder first seen 5 days before its date pushes once, with 5
  days left.
- Pushes go out only between 09:00 and 21:00. CashPilot uses the first owner's
  timezone from Settings, then the container's `TZ`, then UTC. A warning
  reached overnight goes out at the first check after 09:00.
- When more than 3 pushes are due at once, you get one summary instead. This
  happens on the day you upgrade, when every balance over its minimum shows up
  together.
- A push carries the service, what to do, what you would lose, the date and the
  provider's link. It never carries a balance, an address, a device id or a
  worker name. ntfy topics can be public.
- Webhook payloads carry `kind: "obligation"`, so Home Assistant and similar
  tools can route them.

## For catalog contributors

Rules live in each service's YAML file, under `obligations:`.
`services/_schema.yml` documents the fields. Add a rule only when the
provider's own terms or docs state it, and when CashPilot can see the signal it
depends on. A rule's link must be on the service's own domain, because fake
claim sites exist for exactly these services. CI fails on an invalid rule, and
on a dated rule more than 30 days past.
