---
source_hash: 098dcc2576d9
---
# Paglipat mula sa money4band { #moving-from-money4band }

Kayang basahin ng CashPilot ang config ng money4band at ilipat ang iyong mga login sa serbisyo, kaya
hindi mo na kailangang i-type muli ang mga ito. Sinusuri mo ang lahat bago ito i-save ng CashPilot.

## Bago ka magsimula { #before-you-start }

Kailangan mo ang account ng may-ari sa CashPilot at hindi bababa sa isang CashPilot worker sa
makina kung saan tumatakbo ngayon ang money4band, o sa ibang makina.

Ihinto ang money4band sa isang makina bago mo i-deploy doon ang parehong mga serbisyo mula sa
CashPilot. Kumikita bilang isa ang dalawang kopya sa likod ng iisang koneksyon, at hindi dapat tumakbo nang dalawang beses ang parehong EarnApp
o ProxyRack device id. Gamitin ang **Stop apps stack** sa
menu ng money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
o patakbuhin ang `docker compose down` sa folder nito. Kung nag-set up ka ng mga dagdag na proxy
instance, ihinto rin ang bawat isa sa mga iyon.

## Aling file ang gagamitin { #which-file-to-use }

Gamitin ang `config/user-config.json` sa iyong folder ng money4band. Kung paano mo ito
dadalhin sa CashPilot ay depende sa bersyon ng iyong money4band.

Sa money4band 4.x, isinusulat ng money4band ang file
kapag pinatakbo mo ang **Setup Apps**, at hawak nito ang mismong itinype mo. Ang `.env`
katabi nito ay ginawa mula sa file na iyon at gumagana rin, gayundin ang in-edit sa kamay na
`.env` ng money4band 3.x. Pareho silang nananatili sa iyong disk lang: inililista sila ng
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
ng money4band.

Ine-encrypt ng money4band 5.0 ang `config/user-config.json` sa disk
([mga tala sa seguridad](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
at binubura nito ang `.env` nito pagkatapos ng bawat pagsisimula
([env builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
Hindi mabasa ng CashPilot ang naka-encrypt na file. Patakbuhin ang `m4b config edit` sa iyong
folder ng money4band: binubuksan nito ang na-decrypt na file sa iyong editor
([CLI reference](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Kopyahin ang lahat ng teksto nito, i-paste ito sa pahina ng **Import from another tool** (Mag-import mula sa ibang tool), pagkatapos isara ang editor.

Mas mainam ang JSON file. Sa isang `.env`, ine-expand ng Docker Compose ang `$` sa mga value na walang quote,
kaya ang password na may `$` ay hindi ang ipinapakita ng file. Hindi nanghuhula ang CashPilot:
hinihiling nitong i-type mo muli ang value na iyon.

## Paano mag-import { #how-to-import }

1. Buksan ang **Settings** (Mga setting), pagkatapos ang **Import from another tool** (Mag-import mula sa ibang tool) (o pumunta sa `/import`).
2. Idagdag ang `user-config.json`, o i-paste ang teksto nito. Iwanan ang tool sa **Tell from the
   files** (Alamin mula sa mga file), o piliin ang money4band.
3. Suriin ang talahanayan. Lagyan ng tsek ang mga serbisyong gusto mo at punan ang anumang value na minarkahang
   kulang.
4. Pindutin ang **Save the ticked services** (I-save ang mga may tsek na serbisyo), pagkatapos i-deploy sila sa iyong mga worker mula sa
   parehong pahina.

## Ano ang nalilipat { #what-comes-over }

Nagmumula ang mga pangalan ng field sa
[user-config template](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json) ng money4band
at sa mga pangalan sa `.env` na isinusulat ng
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545) nito
(`<APP>_<FLAG>`, halimbawa `REPOCKET_APIKEY`). Pareho pa rin ang mga pangalan ng field
sa money4band 5.0, sa
[app catalog](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported) nito.

| App sa money4band | Serbisyo sa CashPilot | Ano ang nalilipat |
|---|---|---|
| `earnapp` | EarnApp | device id (`uuid`), kaya patuloy na kumikita ang naka-link mong device |
| `honeygain` | Honeygain | email, password |
| `iproyalpawns` | IPRoyal Pawns | email, password |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | email, API key |
| `earnfm` | Earn.fm | API key |
| `proxyrack` | ProxyRack | API key, device UUID |
| `proxylite` | ProxyLite | user id |
| `bitping` | Bitping | email, password |
| `mystnode` | Mysterium | naka-on; tingnan ang tala tungkol sa Mysterium sa ibaba |

Lumalabas nang walang tsek ang app na in-off mo sa money4band. Ang app na naka-off at
walang hawak kundi ang mga placeholder ng template (`yourHONEYGAINMail`) at mga listahan ng port
ay hindi isinasama, kaya walang laman na talahanayan ang ibinibigay ng hindi ginalaw na `user-config.json`.

Nakalista ang mga app na ito pero hindi inililipat:

| App sa money4band | Bakit |
|---|---|
| `proxybase` | Pinapatakbo ng money4band ang lumang client ng ProxyBase gamit ang user id. Pinapatakbo ng CashPilot ang kasalukuyan, na nangangailangan ng Access Token mula sa proxybase.org. |
| `urnetwork` | Nagtatago ang money4band ng session token. Sina-sign in ng CashPilot ang URnetwork gamit ang iyong email at password. |
| `grass` | Tumatakbo ang Grass bilang browser extension. Sinusubaybayan lang ito ng CashPilot, gamit ang access token mula sa dashboard ng Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | Sinusubaybayan ng CashPilot ang mga ito, pero walang container na ide-deploy. |
| `packetshare`, `peer2profit`, `speedshare` | Hindi na available. |

Ang kahit anong ibang app ay nakalista bilang **CashPilot has no such service** (Walang ganoong serbisyo ang CashPilot).

## Ano ang hindi kailanman nalilipat { #what-never-comes-over }

- **Pangalan ng device.** Pinapangalanan ng CashPilot ang bawat device ayon sa worker na pinagtatakbuhan nito, kaya
  hindi kailanman nag-uulat ang dalawang worker ng parehong pangalan. Nananatiling nakalista bilang
  offline ang mga luma mong device sa dashboard ng bawat provider hanggang alisin mo sila roon.
- **Mga proxy.** Idagdag ang bawat isa sa seksyong **Proxies** (Mga proxy) ng pahinang **Fleet** (Fleet), pagkatapos patakbuhin ang
  mga kopya ng iyong mga serbisyo sa pamamagitan nito; walang sinisimulan nang mag-isa ang pagdaragdag ng proxy.
  Wala ring sinisimulan ang pag-save ng import. Kailangan muna ng proxied copy na naka-deploy ang parehong serbisyo
  sa worker, at ang pag-deploy nito ay nagpapatakbo rito sa sariling koneksyon ng worker, kaya ang serbisyong hindi kailanman dapat gumamit ng koneksyong iyon ay dapat manatiling
  walang tsek. Tingnan ang [Mga proxied copy](../proxies.md).
- **Watchtower at mga notification.** Ina-update ng CashPilot ang sarili nitong mga container.
- **Ang dashboard ng money4band at ang mga port nito.**

## Pagsubaybay sa kita { #earnings-tracking }

Para sa Honeygain, IPRoyal Pawns at Bitping, ang login ng container ay siya ring
login ng account, kaya pinupunan din ng CashPilot ang kanilang mga credential para sa kita, maliban kung
naitakda mo na sila sa **Settings** (Mga setting). Para sa bawat ibang serbisyo, idagdag ang login para sa kita
sa **Settings > Earnings collection** (Mga setting > Pagkolekta ng kita).

## Mysterium { #mysterium }

Ino-on ng pag-import ang Mysterium, pero nagsisimula ang CashPilot ng bagong node na may bagong
identity. Nananatili ang keystore ng lumang node at anumang hindi pa na-settle na kita sa
folder na `.data/mysterium-node` ng money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). I-settle muna sila, o sundin ang
[gabay sa Mysterium](../guides/mysterium.md) para mailipat ang identity.

Hindi masasabi ng isang 3.x na `.env` kung pinatakbo mo ang Mysterium: laging inililista ng template nito
ang port ng dashboard. Mula sa isang 3.x na file, hindi ini-import ang Mysterium, kaya idagdag
ito mula sa katalogo kung pinatakbo mo ito.

## Kaligtasan { #safety }

- Walang pinapatakbo o ine-expand sa file, at walang address dito na kinukuha.
- Binabasa nang isang beses ang file at hindi itinatago. Naka-encrypt na iniimbak ang sine-save mo, gaya ng
  bawat ibang credential sa CashPilot.
- Ipinapakita lang ang mga secret bilang **set** (nakatakda) sa pahina.
- Nananatili ang mga naka-save na import sa pahina ng import hanggang pindutin mo ang **Forget** (Kalimutan), para
  mai-deploy mo sila sa mas maraming worker sa ibang pagkakataon.
