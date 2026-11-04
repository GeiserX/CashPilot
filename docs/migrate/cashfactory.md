# Moving from CashFactory

CashPilot can read CashFactory's `.env` and bring your service logins over, so
you do not type them again. You check everything before CashPilot saves it.

## Before you start

You need the CashPilot owner account and at least one CashPilot worker.

Stop CashFactory on a machine before you deploy the same services there from
CashPilot. Two copies behind one connection earn as one, and the same EarnApp
device id must not run twice. Run `docker compose down` in the CashFactory
folder. Its
[compose file](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
also starts Portainer and two Watchtower containers that mount the Docker
socket (lines 31, 141 and 264). Make sure they are gone too: `docker ps` should
list none of them.

## Which file to use

Use the `.env` file in your CashFactory folder, the one you filled in from the
[sample](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose reads that file, and it expands `$` in values that are not in
single quotes. A value like that is not what the file shows, so CashPilot asks
you to retype it rather than guess.

## How to import

1. Open **Settings**, then **Import from another tool** (or go to `/import`).
2. Add the `.env` file, or paste its text. Leave the tool on "Tell from the
   files", or pick CashFactory.
3. Check the table. Tick the services you want and fill in any value marked
   missing.
4. Press **Save the ticked services**, then deploy them to your workers from the
   same page.

## What comes over

| CashFactory app | Keys read | CashPilot service | What comes over |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | device id, so your linked device keeps earning |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, password |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, password |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, API key |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | device UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API key |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | nothing: no longer available |

A value still showing the sample's placeholder (`<email>`, `sdk-node-<md5sum>`)
counts as not set, and a service with nothing but placeholders is left out of
the table.

## What never comes over

- **`DEVICE_NAME`.** CashPilot names each device after the worker it runs on, so
  two workers never report the same name. Your old devices stay listed as
  offline in each provider's dashboard until you remove them there.
- **Portainer and Watchtower.** CashPilot manages and updates its own
  containers.

## Earnings tracking

For Honeygain and IPRoyal Pawns the container login is also the account login,
so CashPilot fills in their earnings credentials too, unless you already set
them in Settings. For every other service, add the earnings login in
**Settings > Earnings collection**.

## Safety

- Nothing in the file is run or expanded, and no address in it is fetched.
- The file is read once and not kept. What you save is stored encrypted, like
  every other credential in CashPilot.
- Secrets are shown only as "set" on the page.
- Saved imports stay on the import page until you press **Forget**, so you can
  deploy them to more workers later.
