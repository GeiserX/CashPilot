---
source_hash: ca9dd25d45ca
---
# InternetIncome에서 옮겨 오기 { #moving-from-internetincome }

CashPilot은 InternetIncome의 `properties.conf`와, EarnApp 및 ProxyRack 기기 id를
보관하는 파일을 읽어 가져올 수 있습니다. CashPilot이 저장하기 전에 모든 내용을
직접 확인합니다.

## 시작하기 전에 { #before-you-start }

CashPilot 소유자 계정과 CashPilot 워커가 하나 이상 있어야 합니다.

한 머신에서 CashPilot으로 같은 서비스를 배포하기 전에 그 머신의 InternetIncome을
중지하십시오. 한 연결 뒤의 두 사본은 하나로 집계되어 벌며, 같은 기기 id가 두 번
실행되어서는 안 됩니다. InternetIncome 폴더에서 다음을 실행하십시오:

```bash
sudo bash internetIncome.sh --delete
```

`--delete`는 컨테이너를 제거하고 `earnapp.txt`, `proxyrack.txt`,
Mysterium 데이터 폴더는 남깁니다. `--deleteBackup`은 이것들까지 제거하므로
([internetIncome.sh, 61~64번째 줄](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
및 [1562번째 줄](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
먼저 가져오십시오.

## 사용할 파일 { #which-files-to-use }

InternetIncome 폴더에서:

- `properties.conf`: 설정 파일입니다.
- `earnapp.txt`: EarnApp을 실행했다면 사용합니다. 각 줄에 기기 링크가 하나씩 있습니다
  ([1250~1261번째 줄](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`: ProxyRack을 실행했다면 사용합니다. 한 줄에 기기 UUID가 하나씩 있습니다
  ([817~827번째 줄](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot은 각 파일의 첫 번째 기기를 가져옵니다. 이 기기는 기본 컨테이너가 사용했고
계정에 연결한 기기입니다. 나머지 줄은 프록시 사본의 것이었으며, 페이지에서 몇 개를
제외했는지 알려 줍니다.

InternetIncome은 모든 값을 셸로 처리합니다
([1375번째 줄](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
작은따옴표로 감싼 값은
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)의
주석이 권하는 대로 적힌 그대로 받아들입니다. 작은따옴표 밖에 있으면서 `$`, 백틱, 공백,
또는 셸이 바꿀 다른 문자가 들어 있는 값은 파일에 보이는 값과 다르므로, CashPilot은
셸을 실행해 알아내는 대신 다시 입력하라고 요청합니다.

## 가져오는 방법 { #how-to-import }

1. **Settings** (설정)를 열고 **Import from another tool** (다른 도구에서 가져오기)를 여십시오(또는 `/import`로 이동).
2. `properties.conf`를 추가하고, 있다면 `earnapp.txt`와 `proxyrack.txt`도
   추가하십시오. 도구는 **Tell from the files** (파일로 판단)로 두거나 InternetIncome을 고르십시오.
3. 표를 확인하십시오. 원하는 서비스에 체크하고, 누락으로 표시된 값을 채우십시오.
   Repocket에는 계정 이메일이 필요한데, InternetIncome은 이를 요청한 적이
   없습니다.
4. **Save the ticked services** (체크한 서비스 저장)를 누른 다음, 같은 페이지에서 워커에
   배포하십시오.

## 가져오는 항목 { #what-comes-over }

| InternetIncome 앱 | 읽는 키 | CashPilot 서비스 | 가져오는 항목 |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API 키(이메일 추가 필요) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | 토큰 |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API 키, 기기 UUID |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | 이메일, 비밀번호 |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | 이메일, 비밀번호 |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | 사용자 id |
| `earnfm` | `EARN_FM_API` | Earn.fm | API 키 |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | 기기 id |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | 이메일, 비밀번호 |
| `mysterium` | `MYSTERIUM=true` | Mysterium | 켜짐. 아래 Mysterium 안내 참고 |

값이 비어 있으면 앱이 꺼져 있었다는 뜻이며, 목록에 나오지 않습니다.

다음 앱은 목록에는 나오지만 가져오지 않습니다:

| InternetIncome 앱 | 이유 |
|---|---|
| `urnetwork` | InternetIncome은 세션 토큰을 사용합니다. CashPilot은 이메일과 비밀번호로 URnetwork에 로그인합니다. |
| `grass` | Grass는 브라우저 확장 프로그램으로 실행됩니다. CashPilot은 Grass 대시보드의 액세스 토큰으로 추적만 합니다. |
| `titan`, `ebesucher`, `wipter` | CashPilot은 이들을 추적하지만, 배포할 컨테이너가 없습니다. |
| `peer2profit` | 더 이상 제공되지 않습니다. |

CashPilot에 없는 앱(antGain, Adnade 등)의 설정은 읽지 않은 항목으로 이름과 함께
나열됩니다.

## 가져오지 않는 항목 { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot은 각 기기에 그 기기가 실행되는 워커의 이름을 붙이므로,
  두 워커가 같은 이름을 보고하는 일이 없습니다. 이전 기기는 각 제공업체의 대시보드에서
  직접 제거할 때까지 오프라인으로 남아 있습니다.
- **프록시** (`USE_PROXIES`, `proxies.txt`). **Fleet** (플릿) 페이지의 **Proxies** (프록시)
  섹션에서 프록시를 하나씩 추가한 다음, 그 프록시로 서비스 사본을 실행하십시오. 프록시를
  추가하는 것만으로는 아무것도 시작되지 않습니다. `USE_PROXIES=true`이면 InternetIncome은
  서비스를 프록시를 통해서만 실행했습니다. 가져오기를 저장해도 아무것도 시작되지 않습니다.
  프록시 사본을 쓰려면 먼저 같은 서비스가 워커에 배포되어 있어야 하며, 그 배포는 워커 자체
  연결에서 실행되므로, 그 연결을 절대 쓰면 안 되는 서비스는 체크하지 않은 채로 두십시오.
  [프록시 사본](../proxies.md)을 참고하십시오.
- **`BROWSER_USERNAME`과 `BROWSER_PASSWORD`**: InternetIncome 자체 브라우저
  로그인입니다.

## 수익 추적 { #earnings-tracking }

Honeygain, IPRoyal Pawns, Bitping은 컨테이너 로그인이 곧 계정 로그인이므로,
**Settings** (설정)에서 이미 설정하지 않았다면 CashPilot이 수익 자격 증명도 채워 넣습니다.
그 밖의 모든 서비스는 **Settings > Earnings collection** (설정 > 수익 수집)에서
수익 로그인을 추가하십시오.

## Mysterium { #mysterium }

가져오기는 Mysterium을 켜지만, CashPilot은 새 신원으로 새 노드를 시작합니다.
이전 노드의 키 저장소와 정산되지 않은 수익은 InternetIncome의 `mysterium-data`
폴더에 남습니다. 먼저 정산하거나,
[Mysterium 가이드](../guides/mysterium.md)에 따라 신원을 옮기십시오.

## 안전 { #safety }

- 파일 안의 어떤 것도 실행되거나 확장되지 않으며, 파일 안의 어떤 주소도 가져오지 않습니다.
- 파일은 한 번 읽히고 보관되지 않습니다. 저장한 내용은 CashPilot의 다른 모든 자격 증명처럼
  암호화되어 저장됩니다.
- 비밀 값은 페이지에 **set** (설정됨)으로만 표시됩니다.
- 저장된 가져오기는 **Forget** (삭제)을 누를 때까지 가져오기 페이지에 남으므로,
  나중에 더 많은 워커에 배포할 수 있습니다.
