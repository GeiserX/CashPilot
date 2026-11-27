---
source_hash: d88e40f8d9a6
---
# Mga on-chain na balanse ng payout { #on-chain-payout-balances }

Buksan ang **Payouts** (Mga payout) para makita ang balanse sa isang pampublikong payout address. Gumagamit ang Bitcoin ng
[mempool.space](https://mempool.space/docs/api/rest) at gumagamit ang Kaspa ng
[api.kaspa.org](https://api.kaspa.org/docs). Gumagamit ang Ethereum, Polygon at Solana ng mga
pampublikong RPC node. Kayang basahin ng CashPilot ang mga address na ito nang walang key.

| Ang nakikita mo | Ang ibig sabihin |
|---|---|
| Isang halaga | Nag-ulat ang explorer ng balanse. Lumalabas na zero ang iniulat na zero. Itapat ang cursor sa halaga para makita ang pinagmulan. |
| **Pending** (Nakabinbin) | Sa Bitcoin, may nakikitang hindi pa kumpirmadong pagbabago ang explorer. Ang plus ay nangangahulugang may paparating na pondo. Ang minus ay nangangahulugang ginagastos ang pondo. Hiwalay na ipinapakita ang kumpirmadong halaga. |
| **Could not check** (Hindi matingnan) | Hindi sumagot ang explorer o nagpadala ito ng data na hindi mabasa ng CashPilot. |
| **Address not valid** (Hindi valid ang address) | Pumalya ang address sa pagsusuri ng format. Nilaktawan ng CashPilot ang request. |
| **Private chain** (Pribadong chain) | Kailangan ng iyong private view key para mabasa ang balanse ng Monero. Tingnan ang balanse sa iyong wallet. Hindi kailanman hihingin sa iyo ng CashPilot ang key na ito. |
| Isang gitling | Walang address o reader para sa row na ito, o naka-off ang lookup. Kapag isang setting ang nag-off sa lookup, itapat ang cursor sa gitling para makita kung alin. |

Isang balanse lang ang iniuulat ng pampublikong endpoint ng Kaspa. Wala itong ibinibigay na hiwalay na pending
na halaga.

Ipinapakita ng on-chain column ang balanse sa address sa mismong sandaling ito. Maaari itong may kasamang
mga transfer mula sa ibang pinagmulan. Ipinapakita ng unpaid balance ng pool kung ano pa ang hawak ng pool
para sa iyo. Hindi lumalabas sa on-chain na balanse ang OCEAN payout sa pamamagitan ng Lightning. Hindi rin
masasabi ng balanse kung aling mga transfer ang nagmula sa iyong pool.

## Piliin kung saan pupunta ang lookup { #choose-where-the-lookup-goes }

Ibinabahagi ng bawat lookup sa explorer ang iyong pampublikong payout address at ang IP ng server ng UI.
Kayang pag-ugnayin ng explorer ang mga address na tinitingnan mo mula sa parehong IP.

Itakda ang base URL sa environment ng container ng UI kung nagpapatakbo ka ng sarili mong node.
Huwag itakda ang variable para gamitin ang default. Itakda ito sa walang lamang value para i-off
ang lookup para sa chain na iyon.

Halimbawa, maaaring maglaman ang isang Compose override para sa serbisyo ng UI ng:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Gamitin ang base URL ng Esplora o Kaspa API kapag kino-configure ang Bitcoin o Kaspa.
Ibinibigay rin ng endpoint ng Bitcoin ang network difficulty at block rewards para sa
[inaasahang kita](fleet.md#running-costs) ng isang Bitcoin pool. Kailangan ng pagbasang iyon ang isang
mempool backend (ang `/v1/mining` API nito); ang purong Esplora server ay sumasagot lang sa
lookup ng balanse, at walang ipinapakitang inaasahang halaga ang row ng pool.
Para sa Ethereum, Polygon at Solana, itakda ang katumbas na mga variable na
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` o
`CASHPILOT_ONCHAIN_URL_SOLANA` sa RPC URL ng isang node. Gumamit ng HTTP o HTTPS URL
na walang credential, query string o fragment. Ilapat ang pagbabago sa pamamagitan ng
paggawang muli ng container ng UI gamit ang bagong environment.
