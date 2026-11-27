---
source_hash: 38029ca1a5d6
---
# Export ng kita para sa buwis { #income-export-for-taxes }

Buksan ang **Payouts** (Mga payout), hanapin ang **Income for taxes** (Kita para sa buwis), at pumili ng saklaw ng petsa at currency. Tumatakbo ang **This year** (Ngayong taon) hanggang ngayong araw, at sakop ng **Last year** (Nakaraang taon) ang nakaraang taon sa kalendaryo. Iwanang blangko ang mga petsa para i-export ang available na history hanggang ngayong araw. Gumagamit ang CashPilot ng mga petsang UTC at isinasama nito ang dalawang dulo ng saklaw.

Binubura ng CashPilot ang mga reading ng kita 400 araw pagkatapos itong maitala. Ginagamit ng CSV ang natitirang history, kaya maaaring bahagi lang ng earned o accrued na kita nito ang laman ng isang nakaraang taon.

## Pumili ng accounting basis { #choose-an-accounting-basis }

- **Cash basis.** Gamitin ang mga payout row. Itinatala ng mga ito ang perang ibinayad ng serbisyo. Ang mga kumpirmadong payout lang ang isinasama ng CashPilot.
- **Accrual basis.** Gamitin ang mga earned at accrued na row. Ipinapakita ng mga earned row ang credit na maaari mong i-withdraw ayon sa terms ng serbisyo. Ipinapakita ng mga accrued row ang hindi pa nababayarang credit sa pool na maaaring hindi kailanman bayaran ng pool.

Gumamit ng iisang basis para sa parehong kita. Ang pagdaragdag ng mga payout row sa mga earned at accrued na row ay maaaring magbilang sa parehong pera nang dalawang beses. Alamin kung aling basis ang angkop sa iyong paghahain.

## Mga column ng CSV { #csv-columns }

| Column | Ibig sabihin |
|---|---|
| date | Araw (UTC) ng mas huling reading o ng payout. Ginagamit ng payout ang petsang inilagay mo o ang araw na natukoy ito ng CashPilot. |
| period_start | Araw (UTC) ng naunang reading para sa serbisyo at pinagmulang ito. Blangko para sa mga payout. Kapag may puwang sa pagitan ng mga reading, sakop ng halaga ang buong pagitan. |
| kind | earned, accrued o payout. |
| service | ID ng serbisyo sa CashPilot. |
| coin | Code ng currency o token ayon sa pagkakatala ng CashPilot. |
| amount | Halaga sa currency o token na iyon. |
| usd_rate | Bilang ng US dollar bawat unit ng coin. |
| usd_value | Halagang tinaya sa US dollar. |
| local_currency | Fiat currency na pinili mo para sa export. |
| local_rate | Mga unit ng napili mong currency bawat US dollar. |
| local_value | Halagang tinaya sa napili mong currency. |
| method | Paraan ng payout, kung naitala. |

Ang blangkong pagtaya ay nangangahulugang hindi available ang rate. Nandoon pa rin ang katutubong halaga. Nilalaktawan ng CashPilot ang mga panloob na puntos gaya ng Grass points sa mga reading ng kita. Ang unang reading bawat pinagmulan ang nagbibigay ng panimulang balanse. Itinatala ng mga sumunod na row ang mga pagtaas, kaya maaaring magsimula ang CSV pagkatapos ng pinakalumang reading sa napiling saklaw.

Kung higit sa isang pinagmulan ang bumabasa sa iisang account, maaaring bilangin ng CSV ang kitang iyon nang higit sa isang beses.

Nagmumula ang USD rate sa mas huling reading o sa talaan ng payout. Kapag pinupunan ng CashPilot ang presyo ng isang reading, ginagamit nito ang presyo ng CoinGecko sa 00:00 UTC ng araw na iyon. Ginagamit ng CashPilot ang pinakabagong reference rate ng ECB sa araw ng row o bago nito para i-convert ang USD sa napili mong currency. Sakop nito ang mga weekend, holiday at mga araw na hindi pa nailalathala ng ECB ang rate nito. [Araw-araw na rate ng Frankfurter](https://frankfurter.dev/v1/)

Inililista ng Frankfurter ang mga currency na ito para sa export. [Mga suportadong currency](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR at ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD at ZAR.

Piliin ang USD kung wala sa listahang iyon ang iyong currency o kung hindi available ang Frankfurter.

## Pag-import sa ibang tool { #import-into-another-tool }

I-convert ang CSV sa format ng tool bago mag-import. Piliin muna ang mga row para sa iyong accounting basis. Laktawan ang mga payout row para sa wallet na sini-sync na ng tool.

### rotki { #rotki }

Gamitin ang Generic Events na may ganitong mga header.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Itakda ang Type sa Income at ang Location sa external. Tinatanggap din ng rotki ang Deposit, Withdrawal, Loss, Spend at Staking kapag inilalarawan ng mga uring iyon ang isang event. I-map ang coin sa Currency, ang amount sa Amount at ang service sa Description. Gamitin ang asset identifier ng rotki kung saan iba ito sa code ng coin. I-convert ang date sa UTC Unix timestamp sa milliseconds. Iwanang blangko ang dalawang field ng fee. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Gamitin ang mga kinakailangang column ng Universal template.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

I-format ang Date bilang YYYY-MM-DD HH:mm:ss sa UTC. Itakda ang Received Amount mula sa amount at ang Received Currency mula sa coin. Iwanang blangko ang dalawang field na Sent. Para sa mga alam na value, i-map ang local_value at local_currency sa opsyonal na Net Worth Amount at Net Worth Currency. Gamitin ang column na Tag para sa mining o reward kung saan angkop. Opsyonal ang Description at TxHash. [Universal template ng Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Wala ka pang Koinly account? Maaari kang mag-sign up dito: https://koinly.io/?via=FFF185D5. Referral link ito, at wala itong gastos sa iyo.

### CoinTracking { #cointracking }

I-convert ang mga income row sa regular na CSV format ng CoinTracking. Kailangan ng Custom Importer ang mga field ng trade sa magkabilang panig, at ang income row ay may buy side lang. [Mga kinakailangan ng CoinTracking Custom Importer](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Itakda ang Type sa Income o Mining ayon sa angkop. I-map ang amount sa Buy Amount, ang coin sa Buy Currency at ang service sa Comment. Iwanang blangko ang mga field na Sell. I-format ang Date bilang DD.MM.YYYY HH:MM:SS. Ang araw (UTC) ang ibinibigay ng export, kaya gamitin ang 00:00:00 para sa oras. Gamitin ang mga label ng type para sa wika ng iyong account. [Regular na CSV format ng CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Wala ka pang CoinTracking account? Binibigyan ka ng signup link na ito ng 10% diskwento sa bawat bayad na plan: https://cointracking.info?ref=G962413. Referral link ito. Binabayaran ng CoinTracking ang proyektong CashPilot ng 20% ng ibinabayad mo, at hindi ka nito pinagbabayad nang mas malaki.
