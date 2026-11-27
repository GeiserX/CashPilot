---
source_hash: e99e2c0c80bb
---
# 앱 스토어 { #app-stores }

여러 홈 서버 시스템의 앱 스토어에서 CashPilot을 설치할 수 있습니다.
각 등록 항목은 대시보드(`drumsergio/cashpilot`)와 워커
(`drumsergio/cashpilot-worker`)를 설치하며, 워커는 서비스 컨테이너를
시작하고 중지합니다. 이 저장소의 CasaOS 패키지와 Runtipi 패키지만
`docker-compose.yml`의 Docker 소켓 프록시도 함께 설치하므로, 그 워커는
원시 Docker 소켓을 절대 보유하지 않습니다. Unraid 템플릿, TrueNAS 앱, 그리고
CasaOS 앱 스토어에 열려 있는 풀 리퀘스트의 패키지는 여전히 워커에 Docker
소켓을 직접 마운트합니다.

어느 스토어를 쓰든 대시보드는 LAN이나 VPN 안에 두십시오. 대시보드는 워커에
명령할 수 있고, 워커는 호스트의 Docker를 조작합니다. 워커가 소켓을 직접 보유하는
경우, 이는 호스트의 root 권한과 같습니다.

## 현재 등록됨 { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Apps 탭에서 **CashPilot**을 검색하고 두 템플릿을 모두 설치하십시오:
`cashpilot`(대시보드)와 `cashpilot-worker`입니다. 두 템플릿에 같은
`CASHPILOT_API_KEY`를 설정하십시오.

템플릿은 https://github.com/GeiserX/docker-templates 에서 제공되며
`latest` 이미지 태그를 따르므로, Community Applications 사용자는 템플릿을
바꾸지 않아도 각 릴리스를 받습니다.

### TrueNAS SCALE { #truenas-scale }

CashPilot은 TrueNAS **community** 트레인에 있습니다. Apps를 열고 Discover Apps로
이동한 다음 **CashPilot**을 검색하십시오.

앱 정의는
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot 에서 관리되며
정확한 이미지 다이제스트를 고정합니다. TrueNAS 자체 봇이 이를 새 릴리스로 옮기므로,
최신 CashPilot보다 몇 릴리스 뒤처질 수 있습니다.

## 검토 대기 중 { #waiting-for-review }

### CasaOS { #casaos }

CasaOS 앱 스토어에 대한 풀 리퀘스트가 열려 있습니다:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

병합되기 전까지는 사용자 지정 앱으로 설치하십시오. CasaOS에서 App Store를 선택하고,
Custom Install, Import를 차례로 선택한 다음 아래 파일의 내용을 붙여 넣으십시오:
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

CasaOS 0.4.5 이상이 필요합니다. 그 릴리스부터 앱 관리자가 Docker Compose 2.23 위에서
작동하며, 이 버전은 파일에서 소켓 프록시의 정책을 읽습니다. 이전 버전은 정책을
버리므로, 그러면 워커가 Docker에 접근할 수 없습니다.

그 파일은 정확한 릴리스 하나를 고정합니다. 가져오기 전에 두 이미지 태그
(`drumsergio/cashpilot`와 `drumsergio/cashpilot-worker`)를
https://github.com/GeiserX/CashPilot/releases 의 최신 릴리스로 설정하십시오. 파일의
프록시 정책은 `main`을 따릅니다. 워커의 상태 페이지에 정책이 오래되었다고
표시되면 파일을 다시 가져오십시오.

## 준비됨, 아직 제출 전 { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

패키지는
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
에 준비되어 있지만 아직 Runtipi 앱 스토어에는 없습니다. 지금 사용하려면 Runtipi 문서에
따라 직접 관리하는 사용자 지정 앱 스토어에 추가하십시오:
https://runtipi.io/docs/guides/create-your-own-app-store

## 제공하지 않음 { #not-offered }

Umbrel 앱은 호스트 소켓이 아니라 Docker-in-Docker 컨테이너를 통해 Docker에
접근하므로, Umbrel에는 다른 워커 설계가 필요합니다. 아직 이를 테스트하지 않았으므로
Umbrel 패키지는 아직 없습니다.

그 밖의 시스템에서는 [시작하기](getting-started.md)에 나온 대로 저장소의
`docker-compose.yml`을 사용하십시오.
