# Moving from money4band

CashPilot can read money4band's config and bring your service logins over, so
you do not type them again. You check everything before CashPilot saves it.

## Before you start

You need the CashPilot owner account and at least one CashPilot worker on the
machine where money4band runs now, or on another machine.

Stop money4band on a machine before you deploy the same services there from
CashPilot. Two copies behind one connection earn as one, and the same EarnApp
or ProxyRack device id must not run twice. Use **Stop apps stack** in
money4band's menu
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
or run `docker compose down` in its folder. If you set up extra proxy
instances, stop each of them too.

## Which file to use

Use `config/user-config.json` in your money4band folder. money4band writes it
when you run **Setup Apps**, and it holds exactly what you typed. The `.env`
next to it is generated from that file and also works, as does the hand-edited
`.env` of money4band 3.x. Both stay on your disk only: money4band's
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
lists them.

Prefer the JSON file. In a `.env`, Docker Compose expands `$` in unquoted
values, so a password with `$` in it is not what the file shows. CashPilot does
not guess: it asks you to retype that value.

## How to import

1. Open **Settings**, then **Import from another tool** (or go to `/import`).
2. Add `user-config.json`, or paste its text. Leave the tool on "Tell from the
   files", or pick money4band.
3. Check the table. Tick the services you want and fill in any value marked
   missing.
4. Press **Save the ticked services**, then deploy them to your workers from the
   same page.

## What comes over

Field names come from money4band's
[user-config template](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
and the `.env` names its
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
writes (`<APP>_<FLAG>`, for example `REPOCKET_APIKEY`).

| money4band app | CashPilot service | What comes over |
|---|---|---|
| `earnapp` | EarnApp | device id (`uuid`), so your linked device keeps earning |
| `honeygain` | Honeygain | email, password |
| `iproyalpawns` | IPRoyal Pawns | email, password |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | email, API key |
| `earnfm` | Earn.fm | API key |
| `proxyrack` | ProxyRack | API key, device UUID |
| `proxylite` | ProxyLite | user id |
| `bitping` | Bitping | email, password |
| `mystnode` | Mysterium | turned on; see the Mysterium note below |

An app you turned off in money4band shows up unticked. An app that is off and
holds only the template's placeholders (`yourHONEYGAINMail`) is left out, so an
untouched `user-config.json` gives an empty table.

These apps are listed but not brought over:

| money4band app | Why |
|---|---|
| `proxybase` | money4band runs ProxyBase's old client with a user id. CashPilot runs the current one, which needs the Access Token from proxybase.org. |
| `urnetwork` | money4band keeps a session token. CashPilot signs URnetwork in with your email and password. |
| `grass` | Grass runs as a browser extension. CashPilot only tracks it, with the access token from the Grass dashboard. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide` | CashPilot tracks these, but there is no container to deploy. |
| `wipter`, `packetshare`, `peer2profit`, `speedshare` | No longer available. |

Any other app is listed as "CashPilot has no such service".

## What never comes over

- **Device name.** CashPilot names each device after the worker it runs on, so
  two workers never report the same name. Your old devices stay listed as
  offline in each provider's dashboard until you remove them there.
- **Proxies.** Add each one in the Proxies section of the Fleet page, then run
  copies of your services through it; adding a proxy starts nothing by itself.
  Saving an import starts nothing either. A proxied copy needs the same service
  deployed on the worker first, and deploying it runs it on the worker's own
  connection, so a service that must never use that connection should stay
  unticked. See [Proxied copies](../proxies.md).
- **Watchtower and notifications.** CashPilot updates its own containers.
- **money4band's dashboard and its ports.**

## Earnings tracking

For Honeygain, IPRoyal Pawns and Bitping the container login is also the
account login, so CashPilot fills in their earnings credentials too, unless you
already set them in Settings. For every other service, add the earnings login
in **Settings > Earnings collection**.

## Mysterium

Importing turns Mysterium on, but CashPilot starts a new node with a new
identity. The old node's keystore and any unsettled earnings stay in
money4band's `.data/mysterium-node` folder
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Settle them first, or follow the
[Mysterium guide](../guides/mysterium.md) to carry the identity over.

A 3.x `.env` cannot tell whether you ran Mysterium: its template always
lists the dashboard port. From a 3.x file Mysterium is not imported, so add
it from the catalog if you ran it.

## Safety

- Nothing in the file is run or expanded, and no address in it is fetched.
- The file is read once and not kept. What you save is stored encrypted, like
  every other credential in CashPilot.
- Secrets are shown only as "set" on the page.
- Saved imports stay on the import page until you press **Forget**, so you can
  deploy them to more workers later.
