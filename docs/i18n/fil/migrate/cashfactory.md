---
source_hash: 7f8476aeb8b6
---
# Paglipat mula sa CashFactory { #moving-from-cashfactory }

Kayang basahin ng CashPilot ang `.env` ng CashFactory at ilipat ang iyong mga login sa serbisyo, kaya
hindi mo na kailangang i-type muli ang mga ito. Sinusuri mo ang lahat bago ito i-save ng CashPilot.

## Bago ka magsimula { #before-you-start }

Kailangan mo ang account ng may-ari sa CashPilot at hindi bababa sa isang CashPilot worker.

Ihinto ang CashFactory sa isang makina bago mo i-deploy doon ang parehong mga serbisyo mula sa
CashPilot. Kumikita bilang isa ang dalawang kopya sa likod ng iisang koneksyon, at hindi dapat tumakbo nang dalawang beses ang parehong EarnApp
device id. Patakbuhin ang `docker compose down` sa folder ng CashFactory.
Ang
[compose file](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml) nito
ay nagsisimula rin ng tatlong container na nagma-mount ng Docker socket: Portainer (linya 31)
at dalawang Watchtower container (mga linya 141 at 264). Tiyaking wala na rin sila: dapat walang
ilista sa kanila ang `docker ps`.

## Aling file ang gagamitin { #which-file-to-use }

Gamitin ang `.env` file sa iyong folder ng CashFactory, ang pinunan mo mula sa
[sample](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Binabasa ng Docker Compose ang file na iyon, at ine-expand nito ang `$` sa mga value na wala sa
single quote. Ang ganoong value ay hindi ang ipinapakita ng file, kaya hinihiling ng CashPilot na
i-type mo itong muli sa halip na manghula.

## Paano mag-import { #how-to-import }

1. Buksan ang **Settings** (Mga setting), pagkatapos ang **Import from another tool** (Mag-import mula sa ibang tool) (o pumunta sa `/import`).
2. Idagdag ang `.env` file, o i-paste ang teksto nito. Iwanan ang tool sa **Tell from the
   files** (Alamin mula sa mga file), o piliin ang CashFactory.
3. Suriin ang talahanayan. Lagyan ng tsek ang mga serbisyong gusto mo at punan ang anumang value na minarkahang
   kulang.
4. Pindutin ang **Save the ticked services** (I-save ang mga may tsek na serbisyo), pagkatapos i-deploy sila sa iyong mga worker mula sa
   parehong pahina.

## Ano ang nalilipat { #what-comes-over }

| App sa CashFactory | Mga key na binabasa | Serbisyo sa CashPilot | Ano ang nalilipat |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | device id, kaya patuloy na kumikita ang naka-link mong device |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, password |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, password |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, API key |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | device UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API key |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | wala: hindi na available |

Ang value na nagpapakita pa ng placeholder ng sample (`<email>`, `sdk-node-<md5sum>`)
ay itinuturing na hindi nakatakda, at ang serbisyong walang hawak kundi mga placeholder ay hindi isinasama sa
talahanayan.

## Ano ang hindi kailanman nalilipat { #what-never-comes-over }

- **`DEVICE_NAME`.** Pinapangalanan ng CashPilot ang bawat device ayon sa worker na pinagtatakbuhan nito, kaya
  hindi kailanman nag-uulat ang dalawang worker ng parehong pangalan. Nananatiling nakalista bilang
  offline ang mga luma mong device sa dashboard ng bawat provider hanggang alisin mo sila roon.
- **Bitping.** Itinatago ng CashFactory ang login ng Bitping sa isang Docker volume, hindi sa
  `.env`, kaya walang mababasa ang import at walang ipinapakitang row ng Bitping. I-type ang
  login sa deploy form ng Bitping.
- **Portainer at Watchtower.** Pinamamahalaan at ina-update ng CashPilot ang sarili nitong mga
  container.

## Pagsubaybay sa kita { #earnings-tracking }

Para sa Honeygain at IPRoyal Pawns, ang login ng container ay siya ring login ng account,
kaya pinupunan din ng CashPilot ang kanilang mga credential para sa kita, maliban kung naitakda mo na
sila sa **Settings** (Mga setting). Para sa bawat ibang serbisyo, idagdag ang login para sa kita sa
**Settings > Earnings collection** (Mga setting > Pagkolekta ng kita).

## Kaligtasan { #safety }

- Walang pinapatakbo o ine-expand sa file, at walang address dito na kinukuha.
- Binabasa nang isang beses ang file at hindi itinatago. Naka-encrypt na iniimbak ang sine-save mo, gaya ng
  bawat ibang credential sa CashPilot.
- Ipinapakita lang ang mga secret bilang **set** (nakatakda) sa pahina.
- Nananatili ang mga naka-save na import sa pahina ng import hanggang pindutin mo ang **Forget** (Kalimutan), para
  mai-deploy mo sila sa mas maraming worker sa ibang pagkakataon.
