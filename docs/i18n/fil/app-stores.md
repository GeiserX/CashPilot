---
source_hash: e99e2c0c80bb
---
# Mga app store { #app-stores }

Maaari mong i-install ang CashPilot mula sa app store ng ilang home-server system.
Ini-install ng bawat listing ang dashboard (`drumsergio/cashpilot`) at ang worker
(`drumsergio/cashpilot-worker`), na nagsisimula at humihinto sa mga container ng
serbisyo. Ang mga package lang ng CasaOS at Runtipi sa repository na ito ang
nag-i-install din ng Docker socket proxy mula sa `docker-compose.yml`, kaya hindi kailanman
hawak ng worker nila ang hilaw na Docker socket. Ang mga Unraid template, ang TrueNAS app at
ang package sa bukas na pull request ng CasaOS app store ay direkta pa ring nagma-mount ng Docker
socket sa worker.

Alinmang store ang gamitin mo, panatilihin ang dashboard sa iyong LAN o VPN. Kaya nitong utusan
ang worker, at ang worker ang nagpapatakbo ng Docker sa host. Kung saan hawak mismo ng worker
ang socket, katumbas iyon ng root sa host.

## Nakalista ngayon { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Hanapin ang **CashPilot** sa Apps tab at i-install ang dalawang template:
`cashpilot` (ang dashboard) at `cashpilot-worker`. Itakda ang parehong
`CASHPILOT_API_KEY` sa dalawa.

Nagmumula ang mga template sa https://github.com/GeiserX/docker-templates at sinusundan nila
ang image tag na `latest`, kaya nakukuha ng mga gumagamit ng Community Applications ang bawat release
nang hindi binabago ang template.

### TrueNAS SCALE { #truenas-scale }

Nasa **community** train ng TrueNAS ang CashPilot. Buksan ang Apps, pagkatapos ang Discover Apps,
at hanapin ang **CashPilot**.

Pinapanatili ang app definition sa
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot at nagpi-pin ito
ng eksaktong image digest. Ang sariling mga bot ng TrueNAS ang naglilipat dito sa mga bagong release, kaya maaaring
ilang release itong nahuhuli sa pinakabagong CashPilot.

## Naghihintay ng review { #waiting-for-review }

### CasaOS { #casaos }

May bukas na pull request sa CasaOS app store:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Habang hindi pa ito naisasama, i-install ito bilang custom app: sa CasaOS piliin ang App Store,
pagkatapos ang Custom Install, pagkatapos ang Import, at i-paste ang laman ng
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Kailangan nito ang CasaOS 0.4.5 o mas bago: mula sa release na iyon, nakabatay ang app manager nito sa
Docker Compose 2.23, na bumabasa sa policy ng socket proxy mula sa file.
Itinatapon ito ng mas lumang bersyon, at hindi na maaabot ng worker ang Docker.

Nagpi-pin ang file na iyon ng eksaktong release. Bago mo ito i-import, itakda ang parehong image tag
(`drumsergio/cashpilot` at `drumsergio/cashpilot-worker`) sa pinakabagong
release mula sa https://github.com/GeiserX/CashPilot/releases. Sinusundan ng policy ng proxy
sa file ang `main`; kung sinasabi ng status page ng worker na luma na ang policy nito,
i-import muli ang file.

## Handa na, hindi pa naisusumite { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Handa na ang package sa
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
pero wala pa sa Runtipi app store. Para magamit ito ngayon, idagdag ito sa isang custom app
store na hawak mo, ayon sa docs ng Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Hindi inaalok { #not-offered }

Kailangan ng Umbrel ng ibang disenyo ng worker, dahil naaabot ng mga Umbrel app ang Docker
sa pamamagitan ng isang Docker-in-Docker container sa halip na ang socket ng host. Hindi pa namin
iyon nasusubukan, kaya wala pang package para sa Umbrel.

Para sa kahit anong ibang system, gamitin ang `docker-compose.yml` mula sa repository, gaya ng nasa
[Pagsisimula](getting-started.md).
