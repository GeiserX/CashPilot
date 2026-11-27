---
source_hash: ca9dd25d45ca
---
# Paglipat mula sa InternetIncome { #moving-from-internetincome }

Kayang basahin ng CashPilot ang `properties.conf` ng InternetIncome, at ang mga file kung saan
nito itinatago ang mga device id mo sa EarnApp at ProxyRack, at ilipat ang mga ito. Sinusuri mo
ang lahat bago ito i-save ng CashPilot.

## Bago ka magsimula { #before-you-start }

Kailangan mo ang account ng may-ari sa CashPilot at hindi bababa sa isang CashPilot worker.

Ihinto ang InternetIncome sa isang makina bago mo i-deploy doon ang parehong mga serbisyo mula sa
CashPilot. Kumikita bilang isa ang dalawang kopya sa likod ng iisang koneksyon, at hindi dapat tumakbo nang dalawang beses ang parehong device id.
Sa folder ng InternetIncome, patakbuhin ang:

```bash
sudo bash internetIncome.sh --delete
```

Inaalis ng `--delete` ang mga container at pinapanatili ang `earnapp.txt`, `proxyrack.txt` at
ang data folder ng Mysterium. Inaalis din ng `--deleteBackup` ang mga iyon
([internetIncome.sh, mga linya 61 hanggang 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
at [linya 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
kaya mag-import muna.

## Aling mga file ang gagamitin { #which-files-to-use }

Mula sa folder ng InternetIncome:

- `properties.conf`, ang iyong mga setting.
- `earnapp.txt`, kung pinatakbo mo ang EarnApp. May hawak na device link ang bawat linya
  ([mga linya 1250 hanggang 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, kung pinatakbo mo ang ProxyRack. Isang device UUID bawat linya
  ([mga linya 817 hanggang 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

Kinukuha ng CashPilot ang unang device sa bawat file: ang ginamit ng iyong pangunahing container
at ang ini-link mo sa iyong account. Pag-aari ng mga proxy copy ang ibang mga linya,
at sinasabi sa iyo ng pahina kung ilan ang hindi nito isinama.

Pinapadaan ng InternetIncome ang bawat value sa shell
([linya 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Kinukuha nang eksakto ang value na nasa single quote, gaya ng payo ng mga comment sa
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Ang value na wala sa single quote na may `$`, backtick, espasyo o
ibang character na babaguhin ng shell ay hindi ang ipinapakita ng file, kaya
hinihiling ng CashPilot na i-type mo itong muli sa halip na magpatakbo ng shell para malaman.

## Paano mag-import { #how-to-import }

1. Buksan ang **Settings** (Mga setting), pagkatapos ang **Import from another tool** (Mag-import mula sa ibang tool) (o pumunta sa `/import`).
2. Idagdag ang `properties.conf`, pati ang `earnapp.txt` at `proxyrack.txt` kung mayroon ka
   ng mga iyon. Iwanan ang tool sa **Tell from the files** (Alamin mula sa mga file), o piliin ang InternetIncome.
3. Suriin ang talahanayan. Lagyan ng tsek ang mga serbisyong gusto mo at punan ang anumang value na minarkahang
   kulang. Kailangan ng Repocket ang email ng iyong account, na hindi kailanman hiningi ng InternetIncome.
4. Pindutin ang **Save the ticked services** (I-save ang mga may tsek na serbisyo), pagkatapos i-deploy sila sa iyong mga worker mula sa
   parehong pahina.

## Ano ang nalilipat { #what-comes-over }

| App sa InternetIncome | Mga key na binabasa | Serbisyo sa CashPilot | Ano ang nalilipat |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API key (idagdag ang iyong email) |
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
| `mysterium` | `MYSTERIUM=true` | Mysterium | naka-on; tingnan ang tala tungkol sa Mysterium sa ibaba |

Ang blangkong value ay nangangahulugang naka-off ang app, at hindi ito nakalista.

Nakalista ang mga app na ito pero hindi inililipat:

| App sa InternetIncome | Bakit |
|---|---|
| `urnetwork` | Gumagamit ang InternetIncome ng session token. Sina-sign in ng CashPilot ang URnetwork gamit ang iyong email at password. |
| `grass` | Tumatakbo ang Grass bilang browser extension. Sinusubaybayan lang ito ng CashPilot, gamit ang access token mula sa dashboard ng Grass. |
| `titan`, `ebesucher`, `wipter` | Sinusubaybayan ng CashPilot ang mga ito, pero walang container na ide-deploy. |
| `peer2profit` | Hindi na available. |

Ang mga setting para sa mga app na wala sa CashPilot (antGain, Adnade at iba pa) ay
nakalista ayon sa pangalan bilang hindi nabasa.

## Ano ang hindi kailanman nalilipat { #what-never-comes-over }

- **`DEVICE_NAME`.** Pinapangalanan ng CashPilot ang bawat device ayon sa worker na pinagtatakbuhan nito, kaya
  hindi kailanman nag-uulat ang dalawang worker ng parehong pangalan. Nananatiling nakalista bilang
  offline ang mga luma mong device sa dashboard ng bawat provider hanggang alisin mo sila roon.
- **Mga proxy** (`USE_PROXIES`, `proxies.txt`). Idagdag ang bawat isa sa seksyong **Proxies** (Mga proxy)
  ng pahinang **Fleet** (Fleet), pagkatapos patakbuhin ang mga kopya ng iyong mga serbisyo sa pamamagitan nito; walang sinisimulan nang mag-isa
  ang pagdaragdag ng proxy. Kapag `USE_PROXIES=true`, sa pamamagitan lang ng mga proxy pinatakbo ng InternetIncome
  ang iyong mga serbisyo. Wala ring sinisimulan ang pag-save ng import. Kailangan muna ng
  proxied copy na naka-deploy ang parehong serbisyo sa worker, at
  ang pag-deploy nito ay nagpapatakbo rito sa sariling koneksyon ng worker, kaya ang serbisyong
  hindi kailanman dapat gumamit ng koneksyong iyon ay dapat manatiling walang tsek. Tingnan ang [Mga
  proxied copy](../proxies.md).
- **`BROWSER_USERNAME` at `BROWSER_PASSWORD`**, ang sariling browser login ng InternetIncome.

## Pagsubaybay sa kita { #earnings-tracking }

Para sa Honeygain, IPRoyal Pawns at Bitping, ang login ng container ay siya ring
login ng account, kaya pinupunan din ng CashPilot ang kanilang mga credential para sa kita, maliban kung
naitakda mo na sila sa **Settings** (Mga setting). Para sa bawat ibang serbisyo, idagdag ang login para sa kita
sa **Settings > Earnings collection** (Mga setting > Pagkolekta ng kita).

## Mysterium { #mysterium }

Ino-on ng pag-import ang Mysterium, pero nagsisimula ang CashPilot ng bagong node na may bagong
identity. Nananatili ang keystore ng lumang node at anumang hindi pa na-settle na kita sa
folder na `mysterium-data` ng InternetIncome. I-settle muna sila, o sundin ang
[gabay sa Mysterium](../guides/mysterium.md) para mailipat ang identity.

## Kaligtasan { #safety }

- Walang pinapatakbo o ine-expand sa mga file, at walang address sa mga ito na kinukuha.
- Binabasa nang isang beses ang mga file at hindi itinatago. Naka-encrypt na iniimbak ang sine-save mo, gaya ng
  bawat ibang credential sa CashPilot.
- Ipinapakita lang ang mga secret bilang **set** (nakatakda) sa pahina.
- Nananatili ang mga naka-save na import sa pahina ng import hanggang pindutin mo ang **Forget** (Kalimutan), para
  mai-deploy mo sila sa mas maraming worker sa ibang pagkakataon.
