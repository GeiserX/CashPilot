# Moving from InternetIncome

CashPilot can read InternetIncome's `properties.conf`, and the files where it
keeps your EarnApp and ProxyRack device ids, and bring them over. You check
everything before CashPilot saves it.

## Before you start

You need the CashPilot owner account and at least one CashPilot worker.

Stop InternetIncome on a machine before you deploy the same services there from
CashPilot. Two copies behind one connection earn as one, and the same device id
must not run twice. In the InternetIncome folder, run:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` removes the containers and keeps `earnapp.txt`, `proxyrack.txt` and
the Mysterium data folder. `--deleteBackup` removes those as well
([internetIncome.sh, lines 61 to 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
and [line 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
so import first.

## Which files to use

From the InternetIncome folder:

- `properties.conf`, your settings.
- `earnapp.txt`, if you ran EarnApp. Each line holds a device link
  ([lines 1250 to 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, if you ran ProxyRack. One device UUID per line
  ([lines 817 to 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot takes the first device in each file: the one your main container
used and the one you linked to your account. The other lines belonged to proxy
copies, and the page tells you how many it left out.

InternetIncome runs every value through the shell
([line 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
A value in single quotes is taken as written, as the comments in
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
advise. A value outside single quotes that holds `$`, a backtick, a space or
another character the shell would change is not what the file shows, so
CashPilot asks you to retype it rather than run a shell to find out.

## How to import

1. Open **Settings**, then **Import from another tool** (or go to `/import`).
2. Add `properties.conf`, plus `earnapp.txt` and `proxyrack.txt` if you have
   them. Leave the tool on "Tell from the files", or pick InternetIncome.
3. Check the table. Tick the services you want and fill in any value marked
   missing. Repocket needs your account email, which InternetIncome never asked
   for.
4. Press **Save the ticked services**, then deploy them to your workers from the
   same page.

## What comes over

| InternetIncome app | Keys read | CashPilot service | What comes over |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API key (add your email) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API key, device UUID |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, password |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, password |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `earnfm` | `EARN_FM_API` | Earn.fm | API key |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | device id |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, password |
| `mysterium` | `MYSTERIUM=true` | Mysterium | turned on; see the Mysterium note below |

A blank value means the app was off, and it is not listed.

These apps are listed but not brought over:

| InternetIncome app | Why |
|---|---|
| `urnetwork` | InternetIncome uses a session token. CashPilot signs URnetwork in with your email and password. |
| `grass` | Grass runs as a browser extension. CashPilot only tracks it, with the access token from the Grass dashboard. |
| `titan`, `ebesucher` | CashPilot tracks these, but there is no container to deploy. |
| `wipter`, `peer2profit` | No longer available. |

Settings for apps CashPilot does not have (antGain, Adnade and others) are
listed by name as not read.

## What never comes over

- **`DEVICE_NAME`.** CashPilot names each device after the worker it runs on, so
  two workers never report the same name. Your old devices stay listed as
  offline in each provider's dashboard until you remove them there.
- **Proxies** (`USE_PROXIES`, `proxies.txt`). Add each one in the Proxies
  section of the Fleet page, then run copies of your services through it;
  adding a proxy starts nothing by itself. See [Proxied copies](../proxies.md).
- **`BROWSER_USERNAME` and `BROWSER_PASSWORD`**, InternetIncome's own browser
  login.

## Earnings tracking

For Honeygain, IPRoyal Pawns and Bitping the container login is also the
account login, so CashPilot fills in their earnings credentials too, unless you
already set them in Settings. For every other service, add the earnings login
in **Settings > Earnings collection**.

## Mysterium

Importing turns Mysterium on, but CashPilot starts a new node with a new
identity. The old node's keystore and any unsettled earnings stay in
InternetIncome's `mysterium-data` folder. Settle them first, or follow the
[Mysterium guide](../guides/mysterium.md) to carry the identity over.

## Safety

- Nothing in the files is run or expanded, and no address in them is fetched.
- The files are read once and not kept. What you save is stored encrypted, like
  every other credential in CashPilot.
- Secrets are shown only as "set" on the page.
- Saved imports stay on the import page until you press **Forget**, so you can
  deploy them to more workers later.
