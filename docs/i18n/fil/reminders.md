---
source_hash: b4ae1a3ae496
---
# Perang naghihintay: mga paalala bago ka mawalan ng kita { #money-waiting-reminders-before-you-lose-earnings }

May mga provider na binabawi ang perang matagal nang nakatengga. Maaaring mag-expire ang isang balanse pagkatapos
ng ilang buwang walang aktibidad. Maaaring magsara ang palugit para mag-claim. Maaaring i-ban ng provider ang
isang account, tumigil sa pagbabayad o magsara habang nandoon pa ang iyong balanse.
Nababasa na ng CashPilot ang karamihan ng kailangan nito para makita ang mga ito bago mangyari. Ipinapakita ng panel na
**Money waiting** (Perang naghihintay) sa dashboard kung ano ang gagawin at hanggang kailan, at
nakakatanggap ang iyong mga notification channel ng push bago ang bawat deadline.

Hindi kailanman nagki-claim o nagwi-withdraw ang CashPilot ng kahit ano para sa iyo. Nagli-link ang bawat paalala sa
sariling pahina ng provider, at doon ka kikilos.

## Ano ang ipinapaalala nito { #what-it-reminds-you-about }

**Mga patakaran mula sa sariling terms ng provider.** Bawat patakaran ay bumabanggit sa terms o
help page ng provider, at sa petsa kung kailan ito huling binasa ng isang tao. Binubuksan ito ng link na **Source** (Pinagmulan) sa
menu na **More** (Iba pa) ng row.

| Serbisyo | Paalala | Kailan |
|---|---|---|
| Grass | I-claim ang iyong Stage 2 USDC | Hanggang 22 Ene 2027. Itinatago ng Grass ang hindi na-claim. |
| MystNodes | I-claim ang rewards ng nakaraang buwan | Sa loob ng 30 araw ng bawat buwanang distribusyon |
| Honeygain | I-withdraw ang iyong balanse | 24 na buwan pagkatapos itong unang umabot sa $20 |
| Honeygain | Panatilihing nagsi-share ang isang device, o mag-payout | 6 na buwan pagkatapos ng huling aktibidad o payout |
| Repocket | Panatilihing nagsi-share ang isang device, o mag-withdraw | 12 buwan pagkatapos ng huling aktibidad o payout |
| Bitping | I-withdraw ang iyong balanse | 12 buwan pagkatapos ng huling withdrawal |
| Salad | Kumita ng ilang Reward Points, o gastusin ang iyong balanse | 12 buwan pagkatapos huling lumaki ang balanse. Hindi ito nire-reset ng paggastos ng bahagi nito. |

**Cash-out.** Sinasabi sa iyo ng CashPilot kapag umabot ang isang balanse sa minimum ng provider.
Angkop ito sa bawat serbisyong kinokolektahan nito, maliban sa mga serbisyong
kusang nagpa-payout. Dapat ding hindi bababa sa $5 ang halaga ng balanse, para ang provider
na may minimum na 5 sentimo ay hindi mangulit sa unang sentimo. Kapag mas mataas ang minimum ng provider,
ang minimum ng provider ang nasusunod. Kapag hindi ma-convert ng CashPilot ang minimum o ang balanse, wala itong
ipinapakita. Hindi ito kailanman nanghuhula na
maaari ka nang mag-withdraw.

**Pag-expire ng credential.** Nakakatanggap ka ng push bago mag-expire ang isang naka-save na token o cookie.
Ginagamit ng CashPilot ang petsa ng pag-expire na nakasaad mismo sa credential. Kapag wala itong
nakasaad, ginagamit ng CashPilot ang karaniwang tagal ng ganoong uri ng credential, binibilang
mula sa araw na sine-save mo ito. Nakikita na ito ng mga may-ari sa ilalim ng **Needs attention** (Kailangang asikasuhin),
na may button na **Renew** (I-renew), kaya hindi na ito inuulit ng panel. Ang mga may-ari lang ang nakakatanggap
ng mga paalala sa credential mula sa API, gaya ng credential health check.
Ang credential na tinanggihan ng provider ay nasa bell na at na-push na,
kaya hindi na ito muling nagpu-push.

## Aling mga serbisyo ang sakop nito { #which-services-it-covers }

Angkop ang paalala sa serbisyong ginagamit mo: isang naka-deploy, isang sine-set up mo
bilang external sa **Settings** (Mga setting), o isang app na iniuulat ng telepono. Ang serbisyong inalis mo
ay binibilang pa rin habang may hawak itong balanse, dahil nagsisimula ang mga orasan ng kawalan ng aktibidad
kapag huminto ito. Walang paalala ang mga custom na serbisyo at ang mga itinigil nang serbisyo.

## Mga petsa at "o mas maaga" { #dates-and-or-earlier }

Binibilang ng mga orasan ng aktibidad mula sa naitala ng CashPilot:

- ang huling pagkakataong lumaki ang balanse,
- ang huling payout,
- o ang unang reading na nasa minimum o higit pa.

Minsan nagsimula ang orasan bago ang unang reading ng CashPilot. Kung ganoon, maaaring mas maaga ang tunay na
deadline kaysa sa nakikita ng CashPilot, at sinasabi ng row na
"by 3 Oct 2027 or earlier" (hanggang 3 Okt 2027 o mas maaga).

Binubura ng CashPilot ang history ng kita pagkalipas ng 400 araw, at tumatakbo ang orasan ng Honeygain
nang 730 araw. Kaya iniimbak ng CashPilot ang bawat simula ng orasan sa unang pagkakataong
makita nito ito, at pinapanatili ito kahit wala na ang history sa likod nito. Nire-reset ng payout
ang orasan, maliban kung saan ang pagkita lang ang binibilang ng provider. Isa rito ang Salad: ang
payout na nag-iiwan ng balanse ay hindi nagre-reset sa 12 buwan nito.

Nawawala ang nakapirming petsa sa araw pagkatapos itong lumipas, dahil wala na ang pera.
Nananatili ang lumampas nang orasan at sinasabi nitong maaaring isinulat na ng provider bilang lugi ang
pera. Nananatili ito hanggang markahan mo itong tapos o i-mute ito, o hanggang i-reset ito ng isang payout.

## Ano ang magagawa mo sa isang paalala { #what-you-can-do-with-a-reminder }

Nakikita ng mga may-ari at editor ang mga button. Ang mga paalala lang ang nakikita ng mga viewer. Ang mga may-ari lang
ang makakakilos sa paalala sa credential.

- Itinatago ng **Done** (Tapos na), o **Requested** (Hiniling na) para sa withdrawal, ang paalalang ito. Bumabalik ang buwanang
  palugit sa susunod na buwan. Bumabalik nang isang beses ang withdrawal pagkalipas ng 14 na araw kung
  nandoon pa ang balanse, at nagtatanong kung dumating na ang payout. Pasok iyon
  sa 60 araw na palugit para sa dispute na ibinibigay ng karamihan ng provider.
- Itinatago ito ng **Snooze** (I-snooze) nang isang araw o isang linggo at pinipigil ang mga push nito. Hindi kailanman
  lumalampas ang snooze sa huling babala bago ang isang deadline.
- Ang **Not for me** (Hindi para sa akin), sa menu na **More** (Iba pa), ay nagmu-mute ng isang paalala, o ng bawat paalala
  ng isang serbisyo. Isang halimbawa: ang Honeygain sa JumpTask mode, kung saan normal ang
  hindi gumagalaw na balanse. Nakalista ang mga naka-mute na paalala sa ibaba ng panel, may
  **Unmute** (I-unmute).

Pinagsasaluhan ng buong sambahayan ang mga pagpiling ito. Kapag minarkahan ng isang tao na tapos ang isang paalala,
tapos na ito para sa lahat. Naitatala ang bawat pagpili sa audit log kasama ang pangalan ng
taong gumawa nito.

## Mga push { #pushes }

Napupunta ang mga paalala sa mga channel na itinakda mo para sa mga alerto: ntfy, isang webhook o Telegram
([configuration](configuration.md)). Kung walang channel na nakatakda, ang panel lang ang
lugar kung saan sila lumalabas.

- Isang push bawat babala. Halimbawa, nagpu-push ang Grass 60, 30, 7 at 1 araw bago
  ang petsa nito. Ang paalalang unang nakita 5 araw bago ang petsa nito ay nagpu-push nang isang beses, na may 5
  araw na natitira.
- Lumalabas lang ang mga push sa pagitan ng 09:00 at 21:00. Ginagamit ng CashPilot ang timezone ng unang may-ari
  mula sa **Settings** (Mga setting), pagkatapos ang `TZ` ng container, pagkatapos ang UTC. Ang babalang
  naabot sa magdamag ay lumalabas sa unang check pagkatapos ng 09:00.
- Kapag higit sa 3 push ang sabay-sabay na dapat ipadala, isang buod ang matatanggap mo sa halip. Nangyayari ito
  sa araw na nag-upgrade ka, kapag sabay-sabay na lumalabas ang bawat balanseng lampas sa minimum nito.
- Dala ng push ang serbisyo, ang gagawin, ang mawawala sa iyo, ang petsa at ang
  link ng provider. Hindi ito kailanman nagdadala ng balanse, address, device id o
  pangalan ng worker. Maaaring pampubliko ang mga ntfy topic.
- May `kind: "obligation"` ang mga webhook payload, para mairuta ito ng Home Assistant at ng mga katulad na
  tool.

## Para sa mga nag-aambag sa katalogo { #for-catalog-contributors }

Nakatira ang mga patakaran sa YAML file ng bawat serbisyo, sa ilalim ng `obligations:`.
Idinodokumento ng `services/_schema.yml` ang mga field. Magdagdag lang ng patakaran kapag
nakasaad ito sa sariling terms o docs ng provider, at kapag nakikita ng CashPilot ang signal na
pinagbabatayan nito. Dapat nasa sariling domain ng serbisyo ang link ng patakaran, dahil may mga pekeng
claim site para mismo sa mga serbisyong ito. Pumapalya ang CI sa isang invalid na patakaran, at
sa isang patakarang may petsa na lampas na nang higit sa 30 araw.
