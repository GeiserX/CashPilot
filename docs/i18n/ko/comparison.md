---
source_hash: 1a93abea95d7
---
# CashPilot 비교 { #how-cashpilot-compares }

이 페이지는 여러 패시브 인컴 앱을 Docker에서 실행하는 다른 오픈 프로젝트들과 CashPilot을 비교합니다. 모든 프로젝트는 2026-11-04에 확인했습니다. 다른 프로젝트에 관한 각 셀은 근거가 된 파일을 고정된 커밋 기준으로 링크하므로, 직접 확인할 수 있습니다. 셀이 틀렸거나 오래되었다면 [이슈를 열어](https://github.com/GeiserX/CashPilot/issues) 주십시오.

## 비교한 프로젝트 { #projects-compared }

| 프로젝트 | 확인한 대상 | 2026-11-04 기준 스타 수 | 라이선스 |
|---|---|---|---|
| [money4band][m4b-tree] | 릴리스 5.0.0, 태그 커밋 `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `65e900d`의 `main` (2026-10-20), 그리고 3.0.0-beta.9 바이너리에 관한 README의 주장 | 238 | 독점, [자체 라이선스 v1.4][igm-license] |
| [InternetIncome][ii-tree] | `db9338a`의 `main` (2026-11-03) | 257 | LICENSE 파일 없음. [README][ii-license]는 원본 복사를 허용하고 수정본 배포를 금지합니다 |
| [CashFactory][cf-tree] | `0ff4bd0`의 `main` (2025-04-08) | 410 | [LICENSE][cf-license-file] 파일은 GPL-3.0이지만, [README][cf-license]는 수정본 배포를 금지합니다 |
| [home-assistant-passive-income][ha-tree] (HA 애드온) | 릴리스 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | 릴리스 v1.64.0, `c7a12bd`의 `main` (2026-11-04) | 77 | GPL-3.0 |

money4band에는 코드 계열이 두 개 있습니다. 기본 브랜치 `main` (`3bfafb1`)에는 여전히 4.x 코드가 있으며, 그곳의 마지막 코드 변경은 2026-03-03이었습니다. 릴리스 5.0.0은 별도의 히스토리에서 빌드됩니다. 최신 릴리스가 배포하는 것이 5.0.0이므로 5.0.0을 비교합니다.

IGM의 웹 UI, 플릿 관리, 설치 바이너리는 비공개 소스이며 저장소에 없습니다. 셀이 이들에 의존하는 경우 "README의 주장"이라고 적고 README의 해당 줄을 링크합니다. IGM 열의 나머지는 모두 저장소의 셸 스크립트와 compose 파일에서 가져왔습니다.

제외한 프로젝트: [earning-machine](https://github.com/jf-m/earning-machine)과 [passiveMachine](https://github.com/Xpl0itU/passiveMachine)은 2024년 이후 커밋이 없습니다. GitHub 검색에서는 앱을 둘 이상 실행하면서 유지 관리되는 다른 프로젝트를 찾지 못했고, 단일 앱 이미지만 찾았습니다.

## 요약 { #short-version }

- **InternetIncome, money4band, IGM, 그리고 v1.69.0부터 CashPilot은 프록시를 통해 여러 IP에서 벌 수 있습니다.** 앞의 세 프로젝트는 프록시마다 각 앱을 한 번씩 실행하며, 프록시는 InternetIncome의 주요 기능입니다. CashPilot은 워커에 이미 배포된 서비스의 추가 사본을 실행하며, 각 사본은 SOCKS5, HTTP CONNECT 또는 Tailscale 출구 노드 프록시를 거칩니다([프록시 사본](proxies.md)).
- **InternetIncome(23)은 CashPilot의 워커(<!-- n:docker -->21<!-- /n -->)보다 많은 앱을 시작하고, IGM은 20개를 시작합니다.** CashPilot은 실행하지 않는 브라우저 확장 프로그램, 데스크톱, GPU 서비스도 추적하므로 전체적으로 더 많은 서비스(<!-- n:live -->50<!-- /n -->)를 추적합니다. v1.64.0부터는 직접 지정한 어떤 이미지든 [사용자 지정 서비스](custom-services.md)로 실행할 수도 있습니다.
- **money4band와 IGM은 일일 보상을 대신 수령하고, Watchtower로 앱 이미지를 최신 상태로 유지합니다.** CashPilot은 둘 다 하지 않습니다. 배포하거나 재배포할 때만 이미지를 다시 가져옵니다.
- **여기서 제공업체 계정에서 잔액을 읽고 기록을 남기는 것은 CashPilot뿐입니다.** money4band 5.0.0은 사용자 계정이 아니라 자체 카탈로그의 추정치를 보여 줍니다. 나머지는 각 제공업체의 대시보드로 연결합니다.
- **여기서 여러 서버를 하나의 UI로 다루는 오픈 소스 프로젝트는 CashPilot뿐입니다.** IGM의 README는 플릿 관리를 주장하지만, 그 코드는 비공개 바이너리 안에 있습니다.
- **v1.70.0부터 여기서 기본적으로 수익 앱 컨테이너를 LAN에서 떼어 두는 것은 CashPilot뿐이며, 제한이 있습니다.** 새 설치와, Docker 기본 브리지에 수익 앱이 없는 업그레이드 설치에서 켜집니다. 수익 앱이 이미 그 브리지에 있는 업그레이드 설치는 격리를 켤 때까지 그대로 두며, `CASHPILOT_CONTAINER_NETWORK`에 지정한 네트워크에는 CashPilot이 차단벽을 치지 않습니다([격리](isolation.md#modes)). 2.0.7부터 Mysterium도 차단벽 뒤에서 실행됩니다. 2.0.6까지 배포된 노드는 재배포할 때까지 차단벽 없이 호스트 네트워크에 남습니다([차단벽 뒤의 Mysterium](mysterium-fence.md)).

## 나란히 비교 { #side-by-side }

CashPilot 열은 v1.64.0을 설명합니다. 단, 프록시, Docker 소켓, LAN 격리 행은 v1.71.1 (`0170dee`, 2026-11-06)을 설명하고, 컨테이너 설정 행과 LAN 격리 행의 Mysterium 네트워크는 2.0.6 다음 릴리스 (`01e7310`)를 설명합니다. 외부 호출 행에는 [현재 온체인 가이드](onchain.md)의 탐색기 호출이 포함됩니다. 다른 열은 위 표의 커밋을 설명합니다.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA 애드온 |
|---|---|---|---|---|---|---|
| 시작할 수 있는 앱([집계 방법](#how-we-counted) 참고) | 워커가 실행하는 <!-- n:docker -->21<!-- /n -->개와 [사용자 지정 이미지](custom-services.md). 전체 추적 <!-- n:live -->50<!-- /n -->개 | 15개 ([카탈로그][m4b-catalog]). README는 35개라고 하는데, 여기에는 커뮤니티 앱과 제외된 앱이 [포함됩니다][m4b-readme-35] | 20개 ([apps.json][igm-apps]) | 23개 ([스크립트][ii-script]) | 11개 ([compose 파일][cf-compose]) | 10개 ([애드온 폴더][ha-tree]) |
| 설치 방법 | Docker Compose: UI 하나와 서버마다 워커 하나. 워커가 Docker API로 수익 앱을 시작합니다([플릿](fleet.md)) | compose 파일을 작성하는 Python CLI 또는 미리 빌드된 바이너리([릴리스][m4b-tree]) | 비공개 바이너리를 내려받는 `curl \| sh` 설치 프로그램([README][igm-install]). 같은 릴리스의 SHA256SUMS 파일로만 검증합니다([설치 프로그램][igm-installer-sums]) | `sudo docker run`을 호출하는 1,608줄짜리 bash 스크립트 하나([스크립트][ii-script]) | 정적 compose 파일과 sudo로 실행하는 `setup.sh` ([설정][cf-setup]) | Home Assistant 애드온 저장소. Home Assistant OS 또는 Supervised가 필요합니다 |
| 여러 서버, 하나의 화면 | 예([플릿](fleet.md)) | 아니요, 기기마다 스택 하나 | README는 예라고 주장하며, 비공개 바이너리 안에 있습니다([README][igm-features]) | 아니요 | 아니요 | 아니요 |
| 여러 프록시 또는 IP | 예, v1.69.0부터: 배포된 서비스의 추가 사본이 각각 SOCKS5, HTTP CONNECT 또는 Tailscale 출구 노드 프록시를 거칩니다. SOCKS5와 HTTP CONNECT는 TCP만 전달합니다(터널은 프록시 포트로 가는 TCP만 내보내므로 SOCKS5 UDP 릴레이는 버려집니다). Tailscale 출구 노드는 UDP도 전달합니다. 수익 앱은 터널 컨테이너의 네트워크 네임스페이스를 공유하며, 그 방화벽은 루프백, 터널, 그리고 터널 자신의 프록시 연결(프록시 주소와 포트로 가는 TCP, 또는 tailscaled가 표시한 패킷)만 내보내므로, 프록시가 죽으면 트래픽이 새지 않고 수익 앱이 멈춥니다([프록시 사본](proxies.md#how-it-works), [코드][cp-proxy-deploy], [터널 방화벽][cp-tunnel-fw]). 호스트 네트워킹, 게시된 포트, 볼륨, 장치, 또는 `NET_ADMIN`, `NET_RAW`, `SYS_ADMIN`이 필요한 서비스는 프록시를 거쳐 실행할 수 없습니다([프록시 사본](proxies.md#what-cannot-run-through-a-proxy)) | 예([README][m4b-features], [코드][m4b-multiproxy]) | 예([README][igm-features], [compose][igm-proxy]) | 예, 주요 기능입니다([README][ii-readme-top]) | 아니요 | 아니요 |
| 수익 | <!-- n:collectors -->20<!-- /n -->개 수집기가 제공업체 계정에서 잔액을 읽고 기록을 남깁니다. 일부는 브라우저에서 복사한 쿠키나 토큰이 필요하며, 그중 일부는 만료됩니다(각 서비스의 가이드 참고) | 계정 데이터가 아니라 카탈로그 범위에서 나온 추정치([코드][m4b-earnings]) | 스크립트에서 찾지 못함 | 없음 | 없음 | 없음 |
| 지급 | 잔액이 줄면 지급을 제안하고, 확인하면 기록합니다([스키마][cp-payouts]) | 없음 | 없음 | 없음 | 없음 | 없음 |
| 일일 보상 수령 | 아니요 | 예, 사이드카([README][m4b-features]) | 예([README][igm-features], [compose][igm-sidecars]) | 아니요 | 아니요 | 아니요 |
| 저장된 자격 증명 | UI 데이터베이스에 암호화(Fernet). 키 파일은 같은 데이터 볼륨에 있습니다([코드][cp-fernet]). 수익 앱 자격 증명은 컨테이너 환경 변수로 각 워커에 전달되므로, 그 워커의 Docker 설정(`docker inspect`)에 평문으로 남습니다 | 암호화(Fernet). 키 파일은 데이터 디렉터리에 있습니다([코드][m4b-crypto]) | 암호화(openssl을 쓴 AES-256). 키 파일은 볼트 옆에 있습니다([코드][igm-encryptor]) | `properties.conf`에 평문. 일부 비밀번호는 `docker run` 인수로 전달됩니다([스크립트][ii-password-arg]) | `.env`에 평문([파일][cf-env]) | 애드온 옵션. Supervisor가 `/data/options.json`에 저장합니다([HA 문서][ha-options]) |
| 수익 앱 컨테이너 설정 | 모든 capability를 제거한 다음 카탈로그가 서비스에 필요한 것만 다시 추가합니다. `no-new-privileges`, pids 제한, 특권 거부([코드][cp-hardening], [코드][cp-privileged]). Mysterium은 차단벽이 쳐진 브리지 위의 자체 네트워크 네임스페이스에서 `NET_ADMIN`, `SETUID`, `SETGID`와 함께, 다이제스트로 고정된 이미지로 실행됩니다([카탈로그][cp-myst]) | 특권이 아닌 모든 서비스에 `no-new-privileges` ([코드][m4b-nnp]). 프록시 컨테이너는 `NET_ADMIN`을 가진 특권 컨테이너입니다([템플릿][m4b-tun]) | 앱 서비스에는 아무것도 설정하지 않음. Mysterium은 `NET_ADMIN`을 받습니다([compose][igm-hosting-myst]). 프록시 컨테이너는 `no-new-privileges`, pids 제한과 함께 `NET_ADMIN`을 받습니다([compose][igm-proxy]) | Ebesucher는 `seccomp=unconfined`로 실행됩니다([스크립트][ii-seccomp]). 프록시 컨테이너와 Mysterium은 `NET_ADMIN`을 받습니다 | 아무것도 설정하지 않음 | 특권, 호스트 네트워크, Docker API 접근을 요청하는 애드온이 없습니다([예시 설정][ha-config]) |
| Docker 소켓이 마운트되는 곳 | v1.71.0부터 소켓 프록시(sockguard 2.4.5, 다이제스트로 고정)에 읽기 전용으로. 워커는 특권 컨테이너, `/`나 소켓의 바인드, 카탈로그 밖의 capability나 장치를 거부하는 필터링된 사본을 받습니다([compose][cp-sock], [세부 정보](security-defaults.md)). 수익 앱에는 절대 마운트되지 않습니다([코드][cp-mounts]) | Watchtower ([템플릿][m4b-watchtower]) | 읽기 전용이며 `no-new-privileges`가 설정된 Watchtower ([compose][igm-watchtower]) | 재시작 도우미 컨테이너 다섯 개([스크립트][ii-sock-helper])와 Watchtower ([스크립트][ii-watchtower]) | 모든 인터페이스의 포트 8000, 9000, 9443에 게시된 Portainer ([compose][cf-portainer]), 그리고 Watchtower 두 개([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | 없음 |
| 이미지 태그 | 수익 앱 이미지 <!-- n:docker -->21<!-- /n -->개 중 9개가 버전이나 다이제스트로 고정되고, 나머지는 움직이는 태그입니다 | 앱 이미지 15개 모두 `:latest` 사용([예시][m4b-image]). 프록시 컨테이너는 v2.6.0, Watchtower는 `:1`로 고정 | 태그가 없으므로 Docker가 `latest`를 사용합니다([compose][igm-hosting]). 일부 ARM 빌드에만 태그가 설정됩니다 | 대부분 `:latest` ([예시][ii-seccomp]). EarnApp은 `:lite`, Honeygain은 amd64에서 프록시를 거칠 때 0.6.6으로 고정([스크립트][ii-honeygain]), Traffmonetizer는 ARM에서 아키텍처별 태그, Watchtower는 `:nightly` | `:latest` 또는 태그 없음, EarnApp만 `:lite` ([compose][cf-compose]) | 애드온마다 버전 하나, 매일 실행되는 CI 작업이 올립니다([워크플로][ha-bump], [예시][ha-dockerfile]) |
| 앱 이미지 업데이트 | 배포하거나 재배포할 때마다 다시 가져옵니다. 자동 업데이트 도구 없음 | Watchtower ([템플릿][m4b-watchtower]) | 4시간마다 Watchtower ([compose][igm-watchtower]) | 켜면 하루에 한 번 Watchtower ([스크립트][ii-watchtower]) | Watchtower 두 개가 각각 앱 하나, PacketStream ([compose][cf-watchtower-ps])과 EarnFM ([compose][cf-watchtower-efm])만 맡습니다. 나머지 앱 9개는 업데이트되지 않습니다 | Home Assistant의 애드온 업데이트 |
| LAN 격리 | v1.70.0부터 새 설치와, Docker 기본 브리지에 수익 앱이 없는 업그레이드 설치에서 기본으로 켜짐: 워커가 수익 앱을 자체 브리지에 두고, 사설 대역, tailnet 대역, 클라우드 메타데이터, 호스트에 연결된 서브넷, 호스트 자체, 그리고 공인 IP 감지가 켜져 있으면 집의 공인 IP를 차단하는 방화벽 테이블을 작성합니다([격리](isolation.md#lan-isolation-by-default), [코드][cp-fence]). 수익 앱이 이미 기본 브리지에 있는 업그레이드 설치는 **Turn on isolation** (격리 켜기)을 누를 때까지 그대로 있습니다. `CASHPILOT_ISOLATION=off`는 격리를 끕니다. `CASHPILOT_CONTAINER_NETWORK`를 설정하면 CashPilot은 그 네트워크에 차단벽을 작성하지 않으며 방화벽 규칙은 사용자가 관리합니다([격리](isolation.md#modes), [코드][cp-fence-mode]). 2.0.7부터 Mysterium에도 차단벽이 쳐집니다. 2.0.6까지 배포된 노드는 재배포할 때까지 호스트 네트워크에 남습니다([차단벽 뒤의 Mysterium](mysterium-fence.md)). 점검 도구가 수익 앱이 닿을 수 있는 곳을 보여 줍니다([점검](isolation-check.md)) | 자체 브리지 서브넷([설정][m4b-subnet]). LAN을 차단하지 않습니다 | 병합된 것 없음 | 찾지 못함 | 찾지 못함 | 찾지 못함 |
| ARM | arm64 UI와 워커. 배포 전에 각 서비스의 플랫폼을 확인합니다([ARM](arm.md)) | arm64 및 armv7 바이너리([릴리스][m4b-release]) | README는 amd64와 arm64, 제한이 있는 arm32를 주장하며, QEMU를 설정합니다([README][igm-arch]) | amd64 전용 이미지에는 binfmt 에뮬레이션이 필요합니다([README][ii-arm]) | README는 Raspberry Pi에서 작동하지 않는다고 합니다([README][cf-raspberry]) | 애드온마다 다름. ProxyRack은 amd64 전용입니다([설정][ha-proxyrack]) |
| UI | 웹 UI, 그리고 Desktop, Android, MCP, Home Assistant 클라이언트 | CLI, 메뉴, 기본적으로 127.0.0.1에 바인딩되는 로컬 웹 대시보드([코드][m4b-bind]) | CLI, 메뉴, 그리고 README에 따르면 LAN에서 접속할 수 있는 포트 4747의 웹 UI ([README][igm-webui]) | 없음, 스크립트 | 포트 80의 북마크 페이지와 Portainer ([README][cf-ui]) | Home Assistant 애드온 패널 |
| 기본 브랜치의 커밋 수, 2026-08-06~2026-11-04 | 286 | 6, 모두 문서(5.0.0은 별도 히스토리에 있음) | 6 | 31 | 0 | 23 |
| 최신 릴리스 | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | 버전이 붙은 릴리스 없음 | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| 앱 외의 외부 호출 | 하루에 한 번 GitHub 릴리스(`CASHPILOT_UPDATE_CHECK=off`로 중지, [코드][cp-update]). 각 워커가 한 시간에 한 번 공인 IP 확인을 위해 `api.ipify.org`, `ifconfig.me` 또는 `icanhazip.com` 호출(`CASHPILOT_EGRESS_DETECT=off`로 중지, [코드][cp-egress]). 환율용 CoinGecko와 Frankfurter ([코드][cp-rates]). [온체인 잔액](onchain.md)용 mempool.space, api.kaspa.org, 공개 Ethereum, Polygon, Solana RPC 노드. 수집기용 각 제공업체. 브라우저는 Google Fonts ([템플릿][cp-cdn])와 jsDelivr의 Chart.js ([템플릿][cp-chartjs])를 불러옵니다 | 업데이트 확인용 GitHub 릴리스([코드][m4b-updater]). 이미지 태그 확인용 Docker Hub와 ghcr.io ([코드][m4b-registry]). IP 점검을 실행하면 공인 IP 확인용 `api.ipify.org`, `ifconfig.me` 또는 `icanhazip.com`, 그리고 IP 점수용으로 일반 HTTP를 쓰는 `ip-api.com` ([코드][m4b-ipscore]) | GitHub 릴리스([코드][igm-version]). 공인 IP 확인용 `api.ipify.org`, `ifconfig.me` 또는 `icanhazip.com` ([코드][igm-ifconfig]). IP 점수용으로 일반 HTTP를 쓰는 `ip-api.com` ([코드][igm-ipscore]). 비공개 바이너리는 확인하지 않았습니다 | 찾지 못함 | 찾지 못함 | 찾지 못함 |

우리가 읽은 코드에서 사용 현황 원격 측정을 보내는 프로젝트는 없습니다. IGM의 비공개 바이너리는 읽을 수 없었습니다.

여기 있는 모든 프로젝트는 앱 자격 증명을 환경 변수로 컨테이너에 전달하며, InternetIncome은 일부를 명령 인수로도 전달합니다. 따라서 앱을 실행하는 호스트에서는 자격 증명이 Docker의 컨테이너 설정(`docker inspect`의 `Env`와 `Args`)에 평문으로 남으며, Docker에 접근할 수 있는 누구나 읽을 수 있습니다. "저장된 자격 증명" 행은 저장된 사본만 설명합니다.

## 집계 방법 { #how-we-counted }

- **CashPilot.** 카탈로그에서 상태가 active 또는 beta이고 Docker 이미지가 있는 서비스로, GPU 컴퓨팅과 채굴 풀은 세지 않습니다. 이 페이지의 숫자는 `scripts/generate_readme_tables.py`에서 나오며, 숫자가 어긋나면 CI가 실패합니다.
- **money4band 5.0.0.** `config/catalog/supported/`의 앱별 JSON 파일: 15개. README의 "35 apps"에는 기본적으로 꺼져 있는 커뮤니티 카탈로그([설정][m4b-community]), Docker 이미지가 없는 앱, 제외된 앱도 포함됩니다.
- **IGM.** `apps.json`의 항목: 20개, 모두 활성화. 프록시 컨테이너, Watchtower, 수령 사이드카는 세지 않습니다.
- **InternetIncome.** `internetIncome.sh`의 `# Starting ... container` 주석 블록 각각에서 프록시와 Watchtower 블록을 뺀 것: 24개. Ebesucher의 Chrome 블록과 Firefox 블록은 앱 하나이며, 같은 EarnFM 계정을 쓰는 EarnFM과 EarnFM Fleetshare도 앱 하나입니다. Depin extensions 블록은 Grass와 Gradient를 시작하므로([스크립트][ii-depin]) 앱 두 개입니다. 합계 23개. README 표에는 앱 27개가 나열되어 있으며, 일부는 가입 링크만 있습니다.
- **CashFactory.** `docker-compose.yml`의 수익 서비스: 11개. Portainer, 웹 서버, Watchtower 두 개는 세지 않습니다. 서비스 하나는 주석 처리되어 있습니다.
- **HA 애드온.** 설정 파일이 있는 애드온 폴더: 10개.

각 목록의 앱이 여전히 지급하는지는 확인하지 않았습니다.

## CashPilot이 뒤처지는 부분 { #where-cashpilot-is-behind }

- 호스트 네트워킹, 게시된 포트, 볼륨, 장치 또는 추가 네트워크 capability가 필요한 서비스는 프록시를 거쳐 실행할 수 없으므로, <!-- n:docker -->21<!-- /n -->개 중 10개(EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi, Kryptex Pool (Pearl))는 서버 자체 IP에서만 법니다([프록시 사본](proxies.md#what-cannot-run-through-a-proxy)).
- 직접 시작하는 앱이 InternetIncome보다 적습니다.
- 일일 보상 수령과 자동 이미지 업데이트가 없습니다.
- 수익 앱 이미지 <!-- n:docker -->21<!-- /n -->개 중 12개가 게시자의 최신 태그를 따라 움직입니다.
- 소켓 프록시는 아직 root 경계가 아닙니다. 침해된 워커는 여전히 정책 범위 안에서 컨테이너를 만들 수 있으며, 두 단계 탈출(다른 컨테이너의 프로세스 네임스페이스에 합류하기, 허용된 폴더 안의 심볼릭 링크)은 거부되지 않습니다([세부 정보](security-defaults.md)).
- 저장된 자격 증명의 암호화 키가 데이터와 같은 볼륨에 있으며, 각 워커에서는 수익 앱 자격 증명이 Docker의 컨테이너 설정에 평문으로 남습니다.
- 일부 수집기는 브라우저에서 복사한 쿠키나 토큰이 필요하고 그중 일부는 만료되므로, 그런 서비스는 수익 추적을 계속 관리해야 합니다.
- UI가 서드파티 CDN에서 글꼴과 Chart.js를 불러옵니다.
- LAN 격리는 수익 앱이 Docker 기본 브리지에 있는 업그레이드 설치에서는 직접 켤 때까지 꺼져 있고, `CASHPILOT_CONTAINER_NETWORK`에 지정한 네트워크에는 차단벽을 치지 않으며([격리](isolation.md#modes)), 2.0.6까지 배포된 Mysterium 노드는 재배포할 때까지 차단벽 없이 호스트 네트워크에 남습니다([차단벽 뒤의 Mysterium](mysterium-fence.md)).
- 커뮤니티가 money4band보다 훨씬 작습니다.
- 릴리스가 잦으며, 때로는 하루에 여러 번입니다.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
