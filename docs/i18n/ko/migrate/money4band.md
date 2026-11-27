---
source_hash: 374e39e6eac9
---
# money4band에서 옮겨 오기 { #moving-from-money4band }

CashPilot은 money4band의 설정을 읽어 서비스 로그인 정보를 가져올 수 있으므로,
다시 입력할 필요가 없습니다. CashPilot이 저장하기 전에 모든 내용을 직접 확인합니다.

## 시작하기 전에 { #before-you-start }

CashPilot 소유자 계정과, 지금 money4band가 실행 중인 머신 또는 다른 머신에
CashPilot 워커가 하나 이상 있어야 합니다.

한 머신에서 CashPilot으로 같은 서비스를 배포하기 전에 그 머신의 money4band를
중지하십시오. 한 연결 뒤의 두 사본은 하나로 집계되어 벌며, 같은 EarnApp이나
ProxyRack 기기 id가 두 번 실행되어서는 안 됩니다. money4band 메뉴의
**Stop apps stack**을 사용하거나
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
그 폴더에서 `docker compose down`을 실행하십시오. 추가 프록시 인스턴스를
설정했다면 그것들도 각각 중지하십시오.

## 사용할 파일 { #which-file-to-use }

money4band 폴더의 `config/user-config.json`을 사용하십시오. money4band는
**Setup Apps**를 실행할 때 이 파일을 작성하며, 이 파일에는 입력한 내용이 그대로 담깁니다. 그 옆의
`.env`는 이 파일에서 생성되며 이것도 작동합니다. money4band 3.x에서 손으로 편집한
`.env`도 마찬가지입니다. 두 파일 모두 디스크에만 남습니다. money4band의
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)에
이 파일들이 나열되어 있습니다.

JSON 파일을 우선 사용하십시오. `.env`에서는 Docker Compose가 따옴표 없는 값의 `$`를
확장하므로, `$`가 들어 있는 비밀번호는 파일에 보이는 값과 다릅니다. CashPilot은
추측하지 않고, 그 값을 다시 입력하라고 요청합니다.

## 가져오는 방법 { #how-to-import }

1. **Settings** (설정)를 열고 **Import from another tool** (다른 도구에서 가져오기)를 여십시오(또는 `/import`로 이동).
2. `user-config.json`을 추가하거나 그 텍스트를 붙여 넣으십시오. 도구는
   **Tell from the files** (파일로 판단)로 두거나 money4band를 고르십시오.
3. 표를 확인하십시오. 원하는 서비스에 체크하고, 누락으로 표시된 값을 채우십시오.
4. **Save the ticked services** (체크한 서비스 저장)를 누른 다음, 같은 페이지에서 워커에
   배포하십시오.

## 가져오는 항목 { #what-comes-over }

필드 이름은 money4band의
[user-config 템플릿](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)과
그 [생성기](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)가
작성하는 `.env` 이름(`<APP>_<FLAG>`, 예: `REPOCKET_APIKEY`)에서 가져옵니다.

| money4band 앱 | CashPilot 서비스 | 가져오는 항목 |
|---|---|---|
| `earnapp` | EarnApp | 기기 id(`uuid`). 연결된 기기가 계속 벌 수 있습니다 |
| `honeygain` | Honeygain | 이메일, 비밀번호 |
| `iproyalpawns` | IPRoyal Pawns | 이메일, 비밀번호 |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | 토큰 |
| `repocket` | Repocket | 이메일, API 키 |
| `earnfm` | Earn.fm | API 키 |
| `proxyrack` | ProxyRack | API 키, 기기 UUID |
| `proxylite` | ProxyLite | 사용자 id |
| `bitping` | Bitping | 이메일, 비밀번호 |
| `mystnode` | Mysterium | 켜짐. 아래 Mysterium 안내 참고 |

money4band에서 끈 앱은 체크되지 않은 상태로 표시됩니다. 꺼져 있고 템플릿의
자리 표시자(`yourHONEYGAINMail`)와 포트 목록만 담긴 앱은 제외되므로, 손대지 않은
`user-config.json`은 빈 표를 만듭니다.

다음 앱은 목록에는 나오지만 가져오지 않습니다:

| money4band 앱 | 이유 |
|---|---|
| `proxybase` | money4band는 사용자 id로 ProxyBase의 이전 클라이언트를 실행합니다. CashPilot은 현재 클라이언트를 실행하며, 여기에는 proxybase.org의 Access Token이 필요합니다. |
| `urnetwork` | money4band는 세션 토큰을 보관합니다. CashPilot은 이메일과 비밀번호로 URnetwork에 로그인합니다. |
| `grass` | Grass는 브라우저 확장 프로그램으로 실행됩니다. CashPilot은 Grass 대시보드의 액세스 토큰으로 추적만 합니다. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot은 이들을 추적하지만, 배포할 컨테이너가 없습니다. |
| `packetshare`, `peer2profit`, `speedshare` | 더 이상 제공되지 않습니다. |

그 밖의 앱은 **CashPilot has no such service** (CashPilot에 해당 서비스 없음)로 표시됩니다.

## 가져오지 않는 항목 { #what-never-comes-over }

- **기기 이름.** CashPilot은 각 기기에 그 기기가 실행되는 워커의 이름을 붙이므로,
  두 워커가 같은 이름을 보고하는 일이 없습니다. 이전 기기는 각 제공업체의 대시보드에서
  직접 제거할 때까지 오프라인으로 남아 있습니다.
- **프록시.** **Fleet** (플릿) 페이지의 **Proxies** (프록시) 섹션에서 프록시를 하나씩 추가한 다음,
  그 프록시로 서비스 사본을 실행하십시오. 프록시를 추가하는 것만으로는 아무것도 시작되지 않습니다.
  가져오기를 저장해도 아무것도 시작되지 않습니다. 프록시 사본을 쓰려면 먼저 같은 서비스가
  워커에 배포되어 있어야 하며, 그 배포는 워커 자체 연결에서 실행되므로, 그 연결을 절대 쓰면
  안 되는 서비스는 체크하지 않은 채로 두십시오. [프록시 사본](../proxies.md)을 참고하십시오.
- **Watchtower와 알림.** CashPilot은 자체 컨테이너를 업데이트합니다.
- **money4band의 대시보드와 그 포트.**

## 수익 추적 { #earnings-tracking }

Honeygain, IPRoyal Pawns, Bitping은 컨테이너 로그인이 곧 계정 로그인이므로,
**Settings** (설정)에서 이미 설정하지 않았다면 CashPilot이 수익 자격 증명도 채워 넣습니다.
그 밖의 모든 서비스는 **Settings > Earnings collection** (설정 > 수익 수집)에서 수익 로그인을 추가하십시오.

## Mysterium { #mysterium }

가져오기는 Mysterium을 켜지만, CashPilot은 새 신원으로 새 노드를 시작합니다.
이전 노드의 키 저장소와 정산되지 않은 수익은 money4band의 `.data/mysterium-node`
폴더에 남습니다
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). 먼저 정산하거나,
[Mysterium 가이드](../guides/mysterium.md)에 따라 신원을 옮기십시오.

3.x `.env`로는 Mysterium을 실행했는지 알 수 없습니다. 그 템플릿에는 항상
대시보드 포트가 나열되기 때문입니다. 3.x 파일에서는 Mysterium을 가져오지 않으므로,
Mysterium을 실행했다면 카탈로그에서 추가하십시오.

## 안전 { #safety }

- 파일 안의 어떤 것도 실행되거나 확장되지 않으며, 파일 안의 어떤 주소도 가져오지 않습니다.
- 파일은 한 번 읽히고 보관되지 않습니다. 저장한 내용은 CashPilot의 다른 모든 자격 증명처럼
  암호화되어 저장됩니다.
- 비밀 값은 페이지에 **set** (설정됨)으로만 표시됩니다.
- 저장된 가져오기는 **Forget** (삭제)을 누를 때까지 가져오기 페이지에 남으므로,
  나중에 더 많은 워커에 배포할 수 있습니다.
