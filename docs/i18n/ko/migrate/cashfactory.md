---
source_hash: 7f8476aeb8b6
---
# CashFactory에서 옮겨 오기 { #moving-from-cashfactory }

CashPilot은 CashFactory의 `.env`를 읽어 서비스 로그인 정보를 가져올 수 있으므로,
다시 입력할 필요가 없습니다. CashPilot이 저장하기 전에 모든 내용을 직접 확인합니다.

## 시작하기 전에 { #before-you-start }

CashPilot 소유자 계정과 CashPilot 워커가 하나 이상 있어야 합니다.

한 머신에서 CashPilot으로 같은 서비스를 배포하기 전에 그 머신의 CashFactory를
중지하십시오. 한 연결 뒤의 두 사본은 하나로 집계되어 벌며, 같은 EarnApp 기기 id가
두 번 실행되어서는 안 됩니다. CashFactory 폴더에서 `docker compose down`을
실행하십시오. CashFactory의
[compose 파일](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)은
Docker 소켓을 마운트하는 컨테이너 세 개도 시작합니다. Portainer(31번째 줄)와
Watchtower 컨테이너 두 개(141번째 줄과 264번째 줄)입니다. 이것들도 사라졌는지 확인하십시오. `docker ps`에
이 중 아무것도 나오지 않아야 합니다.

## 사용할 파일 { #which-file-to-use }

CashFactory 폴더의 `.env` 파일, 즉
[샘플](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env)을 보고 채운 파일을 사용하십시오.

Docker Compose는 그 파일을 읽으며, 작은따옴표로 감싸지 않은 값의 `$`를 확장합니다.
그런 값은 파일에 보이는 값과 다르므로, CashPilot은 추측하지 않고 다시 입력하라고
요청합니다.

## 가져오는 방법 { #how-to-import }

1. **Settings** (설정)를 열고 **Import from another tool** (다른 도구에서 가져오기)를 여십시오(또는 `/import`로 이동).
2. `.env` 파일을 추가하거나 그 텍스트를 붙여 넣으십시오. 도구는
   **Tell from the files** (파일로 판단)로 두거나 CashFactory를 고르십시오.
3. 표를 확인하십시오. 원하는 서비스에 체크하고, 누락으로 표시된 값을 채우십시오.
4. **Save the ticked services** (체크한 서비스 저장)를 누른 다음, 같은 페이지에서 워커에
   배포하십시오.

## 가져오는 항목 { #what-comes-over }

| CashFactory 앱 | 읽는 키 | CashPilot 서비스 | 가져오는 항목 |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | 기기 id. 연결된 기기가 계속 벌 수 있습니다 |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | 이메일, 비밀번호 |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | 이메일, 비밀번호 |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | 토큰 |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | 이메일, API 키 |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | 사용자 id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | 기기 UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API 키 |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | 없음: 더 이상 제공되지 않음 |

샘플의 자리 표시자(`<email>`, `sdk-node-<md5sum>`)가 그대로 남은 값은 설정되지 않은
것으로 간주하며, 자리 표시자만 있는 서비스는 표에서 제외됩니다.

## 가져오지 않는 항목 { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot은 각 기기에 그 기기가 실행되는 워커의 이름을 붙이므로,
  두 워커가 같은 이름을 보고하는 일이 없습니다. 이전 기기는 각 제공업체의 대시보드에서
  직접 제거할 때까지 오프라인으로 남아 있습니다.
- **Bitping.** CashFactory는 Bitping 로그인을 `.env`가 아니라 Docker 볼륨에 보관하므로,
  가져오기에서 읽을 것이 없어 Bitping 행이 표시되지 않습니다. Bitping의 배포 양식에서
  로그인 정보를 입력하십시오.
- **Portainer와 Watchtower.** CashPilot은 자체 컨테이너를 관리하고
  업데이트합니다.

## 수익 추적 { #earnings-tracking }

Honeygain과 IPRoyal Pawns는 컨테이너 로그인이 곧 계정 로그인이므로,
**Settings** (설정)에서 이미 설정하지 않았다면 CashPilot이 수익 자격 증명도 채워 넣습니다.
그 밖의 모든 서비스는 **Settings > Earnings collection** (설정 > 수익 수집)에서
수익 로그인을 추가하십시오.

## 안전 { #safety }

- 파일 안의 어떤 것도 실행되거나 확장되지 않으며, 파일 안의 어떤 주소도 가져오지 않습니다.
- 파일은 한 번 읽히고 보관되지 않습니다. 저장한 내용은 CashPilot의 다른 모든 자격 증명처럼
  암호화되어 저장됩니다.
- 비밀 값은 페이지에 **set** (설정됨)으로만 표시됩니다.
- 저장된 가져오기는 **Forget** (삭제)을 누를 때까지 가져오기 페이지에 남으므로,
  나중에 더 많은 워커에 배포할 수 있습니다.
