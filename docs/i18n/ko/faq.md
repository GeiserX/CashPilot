---
source_hash: 915470497dbc
---
# 자주 묻는 질문 { #faq }

**대역폭 공유는 안전합니까?**

대역폭 공유 서비스는 일반적으로 합법적인 트래픽(시장 조사, 광고 검증, 가격 비교, 콘텐츠 전송)을 사용자의 연결로 라우팅합니다. 그렇더라도 IP 주소를 공유하는 것이므로, 가입하기 전에 각 서비스의 서비스 약관과 개인정보 처리방침을 꼼꼼히 검토하십시오. 일부 서비스는 가정용 IP 대신 VPS에서 실행하는 방법도 있습니다. **이 내용은 법률 자문이 아닙니다. 사용하려는 각 서비스에 문의하고, 필요하면 해당 관할 지역에 관해 독립적인 법률 자문을 받으십시오.**

**얼마나 벌 수 있습니까?**

수익은 위치, ISP, 기기 수, 실행하는 서비스에 따라 크게 달라집니다. 대시보드가 시간에 따른 실제 수익을 추적하므로 설정을 최적화할 수 있습니다. 대략적인 기준일 뿐 약속은 아니지만, 서비스 10~15개를 실행하는 홈 서버 한 대는 한 달에 약 $30~$100를 벌며, 그보다 적게, 0까지 벌 수도 있습니다. 서버를 늘리거나 GPU 컴퓨팅을 쓰면 그만큼 더해집니다.

**VPS나 클라우드 서버에서 실행할 수 있습니까?**

일부 서비스는 가정용 IP가 필요하며 VPS/데이터 센터 IP에는 지급하지 않거나 계정을 정지합니다. 카탈로그는 필요한 것 아래에 "가정용 IP"를 표시합니다. VPS에서 작동하는 서비스는 집에 하드웨어를 더 들이지 않고 규모를 키우는 좋은 방법입니다.

**자격 증명은 어떻게 저장됩니까?**

모든 서비스 자격 증명은 `/data/.fernet_key`에 저장된 Fernet 키로 SQLite 데이터베이스 안에서 저장 상태로 암호화됩니다. 이 키는 첫 실행 때 자동으로 생성됩니다. 데이터베이스 파일은 마운트된 Docker 볼륨(`cashpilot_data:/data`)에 있습니다. 자격 증명은 서비스 컨테이너 자체 외에는 어디로도 전송되지 않습니다.

이 키는 로그인 세션에 서명할 뿐인 `CASHPILOT_SECRET_KEY`와는 다른 키입니다.

### 암호화 키 백업하기 { #backing-up-the-encryption-key }

자격 증명을 복구할 수 있는지는 전적으로 `/data/.fernet_key`에 달려 있습니다. 그 파일을 잃으면 저장된 값을 복호화할 방법이 없으므로 모든 자격 증명을 다시 입력해야 합니다.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

파일이 항상 환경 변수보다 우선하므로, 이미 키가 있는 인스턴스에 `CASHPILOT_ENCRYPTION_KEY`를 설정해도 아무것도 바뀌지 않으며 안전합니다. 이 변수는 키 파일이 없을 때만 채택되는데, 바로 복원하는 경우입니다.

`/data`에 쓸 수 없거나 마운트되지 않아서 CashPilot이 키를 디스크에 전혀 쓸 수 없으면, 다음 재시작 때 사라질 키로 자격 증명을 암호화하는 대신 시작을 거부합니다. 정말로 그렇게 하려는 것이라면 `CASHPILOT_ALLOW_EPHEMERAL_KEY=true`를 설정하십시오.

<a id="forgot-password"></a>

### 비밀번호나 사용자 이름을 잊었을 때 { #forgot-password-or-username }

CashPilot에는 이메일 재설정이 없습니다. 서버를 운영하는 사람이 CashPilot UI 컨테이너의 콘솔에서 비밀번호를 재설정합니다. 서비스, 수익, 저장된 자격 증명에는 영향이 없습니다. 이들은 비밀번호가 아니라 `/data/.fernet_key`로 암호화되어 있습니다.

`python -m app.users` 명령에는 CashPilot 2.3 이상이 필요합니다. 2.2 이하에서는 `No module named app.users` 오류로 실패합니다. 먼저 업데이트하십시오. Docker Compose에서는 `drumsergio/cashpilot`과 `drumsergio/cashpilot-worker` 태그를 `2.3` 이상으로 바꾼 다음(`2.2`나 `2.2.9` 같은 고정 태그는 그 릴리스에 머뭅니다) `docker compose up -d`를 실행하십시오([CashPilot 업데이트](getting-started.md#updating-cashpilot)). Unraid에서는 컨테이너를 업데이트하십시오.

1. 계정 목록을 표시합니다. 잊어버린 사용자 이름도 여기에 나옵니다. 사용자 이름은 대소문자를 구분합니다.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. 계정에 새 무작위 비밀번호를 설정합니다. `alice`를 1단계의 사용자 이름으로 바꾸십시오.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    소유자가 정확히 한 명이면 사용자 이름을 생략할 수 있으며, 그러면 명령이 그 소유자를 재설정합니다. 사용자 이름이 `-`로 시작하면 그 앞에 `--`를 붙이십시오: `reset-password -- -alice`.

    명령은 새 비밀번호를 한 번 출력합니다.

3. 다른 사람이 그 계정에 접근했을 수 있다면 지금 UI 컨테이너를 재시작하십시오(`docker restart cashpilot-ui`). 그 사용자로 아직 로그인되어 있던 브라우저는 재시작한 뒤에야 로그아웃됩니다. 비밀번호를 잊었을 뿐이라면 재시작은 선택 사항입니다.
4. 새 비밀번호로 로그인한 다음, 아바타 메뉴(오른쪽 위)의 **Change password** (비밀번호 변경)에서 비밀번호를 바꾸십시오.

컨테이너 이름은 CashPilot을 설치한 방법에 따라 다릅니다:

| 설치 방법 | UI 컨테이너 |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | 생성된 이름. `docker ps`로 확인할 수 있습니다 |

Portainer, Unraid, CasaOS에도 컨테이너용 콘솔 버튼이 있습니다. 이 명령은 터미널 입력이 필요 없으므로 그곳에서도 작동합니다.

사용자 이름을 바꾸려면:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

새 이름은 가입 규칙을 따릅니다: 영문자, 숫자, `_` 또는 `-`로 된 3~32자입니다. 바뀐 이름을 보려면 로그아웃했다가 다시 로그인하십시오.

**침해가 의심될 때**, 예를 들어 `/data/.secret_key`가 담긴 백업을 잃어버렸다면 비밀번호 재설정만으로는 충분하지 않습니다. 그 키를 가진 사람은 유효한 로그인 쿠키에 서명할 수 있고, 재설정으로는 이를 막을 수 없습니다. 키를 교체한 다음 UI 컨테이너를 재시작하십시오. `&&`는 새 키가 자리를 잡았을 때만 재시작합니다. 명령이 오류를 출력하면 먼저 그 오류를 해결하십시오:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

재시작하면 모든 브라우저가 로그아웃되고, 모두 자신의 비밀번호로 다시 로그인합니다. 저장된 자격 증명에는 영향이 없습니다. `CASHPILOT_SECRET_KEY`를 직접 설정했다면 명령이 거부합니다. 대신 그 변수에 새 무작위 값을 넣고 컨테이너를 다시 만드십시오. 이미지에서 실행한 `docker run`은 그 변수를 보지 못해 거부할 수 없으므로, UI 컨테이너에서 `docker exec`를 사용하십시오.

새 키는 위조된 쿠키를 무효로 만들지만, 공격자가 접근해 있는 동안 한 일까지 되돌리지는 않습니다. 두 단계가 더 필요합니다:

1. `docker exec cashpilot-ui python -m app.users list`를 실행하십시오. 알아보지 못하는 계정은 대시보드에서 삭제하십시오.
2. 잃어버린 사본에 `/data` 전체가 들어 있었다면 제공업체 계정의 비밀번호를 바꾸십시오. `.fernet_key`와 `cashpilot.db`가 함께 있으면 저장된 모든 자격 증명을 복호화할 수 있습니다.

나중에 교체 전에 만든 백업을 복원한다면 그 백업의 `.secret_key`는 빼거나([백업 및 복원](backup-restore.md#restore)), 다시 교체하고 재시작하십시오. 그렇지 않으면 이전 키가 돌아옵니다. 복원된 데이터베이스는 그 안에 있던 계정과 비밀번호도 되살리므로, 계정 확인과 필요한 비밀번호 재설정을 다시 하십시오.

**UI 컨테이너가 시작되지 않으면** 같은 이미지에서 같은 데이터를 대상으로 명령을 실행하십시오. 먼저 UI의 `/data`를 담고 있는 호스트 폴더를 찾습니다. 이 방법은 중지된 컨테이너에서도 작동하며, 바인드 마운트뿐 아니라 이름 있는 볼륨에서도 작동합니다(Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

그런 다음 그 폴더를 마운트하고 실행 중인 이미지 태그를 사용하십시오:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

목록에 계정이 나오는지 확인한 다음, `list` 대신 `reset-password alice`를 넣어 같은 줄을 실행하십시오.

데이터베이스가 없는 경로에서는 "no database" 오류가 나며, 명령은 그곳에서 아무것도 만들거나 바꾸지 않습니다. 그래도 Docker가 그 이름의 빈 폴더나 볼륨을 남길 수 있으니 제거하십시오.

데이터 볼륨은 **절대** 삭제하지 마십시오. 그러면 `/data/.fernet_key`가 지워지고, 그와 함께 저장된 모든 자격 증명도 사라집니다. `users` 테이블의 행도 **절대** 삭제하지 마십시오.

**CashPilot을 완전히 제거하려면 어떻게 합니까?**

`docker compose down -v`는 CashPilot 자체 컨테이너만 제거합니다. CashPilot이 배포한 서비스는 계속 실행되며, 그 데이터, 차단벽이 쳐진 네트워크, 방화벽 테이블도 남습니다. [CashPilot 완전히 제거하기](uninstall.md)는 이 모든 것을 제거하고, 영구히 잃는 것이 무엇인지 알려 주며, 아무것도 남지 않았는지 확인하는 방법을 보여 줍니다.

**보안은 어떻습니까?**

CashPilot이 배포하는 모든 서비스는 자체 컨테이너에서 실행되며, 모든 Linux 기능(capability)이 제거되고(일부 서비스는 선언한 기능만 다시 추가합니다) `--security-opt no-new-privileges`가 설정되므로, 컨테이너 안의 프로세스는 권한을 얻을 수 없습니다. 컨테이너는 서비스가 선언한 볼륨 외에는 호스트 파일 시스템을 볼 수 없습니다. 새 설치에서는 워커가 컨테이너를 LAN, 호스트, tailnet, 클라우드 메타데이터로부터 차단벽으로 막아, 컨테이너가 인터넷에만 닿고 로컬에는 닿지 않게 합니다([네트워크 격리](isolation.md)). Podman에서는 차단벽을 사용할 수 없습니다. 수익 앱은 LAN에 닿을 수 있는 Podman 기본 네트워크에서 실행되며, **Fleet** (플릿) 페이지가 그렇다고 알려 줍니다([네트워크 격리](isolation.md)에 선택지가 나와 있습니다). 1.70 이전 릴리스에서 업그레이드한 설치는 **Fleet** (플릿) 페이지에서 **Turn on isolation** (격리 켜기)을 클릭할 때까지 수익 앱을 LAN에 닿을 수 있는 Docker 기본 브리지에 둡니다. 2.0.7부터 Mysterium도 차단벽 뒤에서 실행됩니다. 2.0.6까지 배포된 노드는 재배포할 때까지 호스트 네트워크에 남습니다([Mysterium 노드를 차단벽 뒤로 옮기기](mysterium-fence.md)). 대신 직접 만든 브리지에 방화벽을 거는 방법은 [홈 네트워크 보호](home-network-security.md)에서 다룹니다. 서비스 자격 증명은 Fernet 대칭 암호화로 저장 상태에서 암호화됩니다. UI에는 Docker 접근 권한이 없습니다. 배포되는 compose 파일에서 워커는 원시 Docker 소켓을 절대 받지 않습니다. 워커는 `cashpilot-socket-proxy`를 통해 Docker에 접근하며, 이 프록시는 특권 컨테이너와 `/` 또는 소켓의 바인드를 거부하고(단, 그중 하나나 소켓보다 위의 폴더를 `CASHPILOT_PROXY_BIND_MOUNTS` 또는 `CASHPILOT_COMPOSE_DIR`에 넣은 경우는 예외입니다. 프록시는 그 값을 그대로 받아들입니다), 워커를 자신의 소유자 레이블이 붙은 컨테이너, 볼륨, 네트워크로 제한합니다([보안 기본값](security-defaults.md)). Unraid 템플릿과 TrueNAS 앱은 여전히 워커에 원시 소켓을 마운트하며, 이는 호스트의 root 권한과 같습니다([앱 스토어](app-stores.md)).

그렇더라도 완벽한 설정은 없습니다. 여전히 외부 트래픽을 사용자의 네트워크로 라우팅하는 서드파티 소프트웨어를 실행하는 것입니다. Docker 격리는 이 서비스들을 호스트에서 직접 실행하는 것보다 공격 표면을 크게 줄이지만, 모든 위험을 없애지는 못합니다. CashPilot은 전용 머신이나 VLAN에서 실행하고, Docker와 호스트 OS를 최신 상태로 유지하며, 배포하기 전에 각 서비스의 오픈 소스 코드를 검토할 것을 권장합니다.

**서비스 컨테이너가 충돌하면 어떻게 됩니까?**

CashPilot은 컨테이너 헬스를 계속 모니터링합니다. 서비스 컨테이너가 예기치 않게 종료되면 자동으로 재시작됩니다. 대시보드는 실행 중인 모든 서비스의 가동 시간과 헬스 상태를 보여 줍니다.

**재배포한 뒤 Mysterium 노드가 시작되지 않습니다. 왜 그렇습니까?**

가장 흔한 원인은 UDP 범위 안의 포트를 호스트의 다른 프로그램이 이미 사용하고 있는 경우입니다. Docker는 범위 안의 모든 포트를 예약해야 하므로, 사용 중인 포트 하나 때문에 시작이 멈춥니다. 비어 있는 상태로 유지되는 범위를 고르는 방법은 [UDP 포트 범위 선택하기](mysterium-fence.md#choosing-the-udp-port-range)에서 설명합니다.

**프록시 사본이 실행 중인데 아무것도 벌지 못합니다. 왜 그렇습니까?**

프록시가 그 수익 앱의 서버에 연결하기를 거부하거나, 포트 80과 443만 허용할 수 있습니다. CashPilot의 **Test** (테스트)는 프록시가 인터넷에 닿는지만 확인합니다. 수익 앱 자체의 호스트와 포트를 확인하는 방법은 [프록시를 통해 수익 앱의 서버 점검하기](proxies.md#probe-an-earners-servers-through-the-proxy)에 나와 있습니다.

**어떤 서비스가 무겁고, 어디에서 실행해야 합니까?**

스토리지 노드, 릴레이와 VPN 출구, GPU 작업이 가장 많이 사용합니다. [작은 머신의 자원 계획](fleet.md#budgeting-a-small-box)에 이들이 나열되어 있으며, 결정하기 전에 각 컨테이너를 측정하는 방법도 나와 있습니다.

<a id="worker-lost-docker"></a>

### Docker 업데이트 후 워커가 Docker를 잃었을 때 { #the-worker-lost-docker-after-a-docker-update }

**보이는 증상.** 워커는 **Fleet** (플릿) 페이지에서 온라인 상태로 남아 있지만, CashPilot이 그 컨테이너를 시작, 중지, 업데이트할 수 없습니다. **Fleet** (플릿) 페이지에서 워커 옆에 **Docker unreachable** (Docker에 연결할 수 없음)이 표시됩니다. 10분 후 워커의 헬스체크가 실패합니다(`docker ps`에서 워커가 `unhealthy`로 표시됩니다). 30분 후에는 알림 벨과 알림이 워커가 Docker에 연결할 수 없다고 알려 줍니다. `docker logs cashpilot-socket-proxy`에는 `upstream Docker socket unreachable`이 표시되며, 현재 compose 파일을 쓰면 약 3분 안에 `docker ps`에서 프록시가 `unhealthy`로 표시됩니다. 수익 앱은 계속 실행됩니다.

**원인.** 배포되는 compose 파일은 소켓 파일 `/var/run/docker.sock`을 `cashpilot-socket-proxy`에 바인드합니다. 파일 바인드는 그 파일 하나를 붙잡습니다. Docker 업데이트(예: `unattended-upgrades`가 새 `docker-ce`를 설치하는 경우)는 Docker를 재시작하고, Docker는 같은 경로에 새 소켓 파일을 만듭니다. Docker의 live-restore가 켜져 있으면 프록시는 그 재시작 동안에도 계속 실행되며 이전 파일을 그대로 붙잡고 있습니다. 이전 파일에서는 아무것도 응답하지 않습니다.

**빠른 해결.** 해당 머신에서 프록시를 재시작하십시오:

```bash
docker restart cashpilot-socket-proxy
```

재시작하면 새 소켓이 바인드되고, 워커는 다음 하트비트 때 Docker를 다시 찾습니다. 워커를 재시작할 필요는 없습니다. Unraid와 TrueNAS에서는 워커가 소켓을 직접 보유하므로 워커를 재시작하십시오.

**영구적인 해결.** 소켓 파일이 아니라 소켓의 폴더를 바인드하십시오. 폴더 바인드는 교체된 소켓을 즉시 보여 줍니다. compose 파일의 `cashpilot-socket-proxy` 서비스에서 `- /var/run/docker.sock:/var/run/docker.sock:ro` 줄을 아래 바인드로 바꾸고, 그 `environment`에 `SOCKGUARD_UPSTREAM_SOCKET` 줄을 추가하십시오:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

그런 다음 `docker compose up -d`를 실행하십시오. 같은 변경은 `docker-compose.worker.yml`과 `docker-compose.fleet.yml`에서도 작동합니다. Compose는 이 파일들을 이름으로 지정할 때만 읽으므로, `COMPOSE_FILE`이 이미 그 파일을 지정하고 있지 않다면 `docker compose -f docker-compose.worker.yml up -d` 또는 `docker compose -f docker-compose.fleet.yml up -d`를 실행하십시오.

- `recursive: disabled`는 반드시 필요합니다. `/var/run`에는 다른 마운트도 있습니다. 예를 들어 `/run/docker/netns` 아래의 Docker 네트워크 네임스페이스와 `/run/user/...`입니다. 재귀 바인드는 이들을 모두 프록시 안으로 가져옵니다. 비재귀 바인드는 폴더 자체만 보여 줍니다.
- `SOCKGUARD_UPSTREAM_SOCKET`은 프록시를 새 경로로 보냅니다. 환경 변수가 정책의 `upstream.socket`을 재정의하므로, 정책 블록과 그 지문은 그대로 둡니다. 이 변수가 없으면 프록시가 시작되지 않습니다(`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate`는 파일 바인드를 유지해도 됩니다. 이 컨테이너는 `docker compose up`할 때마다 다시 시작되므로 항상 현재 소켓을 받습니다. 같은 폴더 바인드를 준다면 그 `environment`에 `DOCKER_HOST=unix:///host-run/docker.sock`을 추가하십시오. 워커 2.8.4 이상이 이 변수를 읽습니다. 이 변수가 프록시의 소켓을 가리키게 하지는 마십시오. 마이그레이터에는 호스트 자체의 소켓이 필요합니다.
- 폴더 바인드는 Docker의 소켓뿐 아니라 `/var/run`의 모든 소켓을 프록시에 줍니다. 일반적인 서버에서는 systemd 자체 소켓, D-Bus, 그리고 Tailscale이나 snapd 같은 도구의 소켓이 포함됩니다. `read_only`는 프로그램이 소켓에 연결하는 것을 막지 않으며, 프록시는 root로 실행됩니다. Docker 소켓에 접근할 수 있다는 것은 이미 호스트의 root 권한을 뜻하므로, 침해된 프록시가 새로 얻는 것은 거의 없습니다. 프록시가 Docker 소켓만 보유하게 하려면 파일 바인드를 유지하고 Docker 업데이트 후 프록시를 재시작하십시오. 언제 해야 하는지는 위의 알림이 알려 줍니다.
- Docker Compose 2.30.0 이상이 필요합니다. 이전 릴리스는 `Additional property recursive is not allowed`와 함께 파일 전체를 거부합니다. 확인하려면 `docker compose version`을 실행하십시오. Debian 13은 Compose 2.26.1을 패키지로 제공하므로, Debian에서는 Docker 자체 저장소에서 Compose를 설치하십시오. 앱 내 업데이트는 자체 Compose 2.33을 사용하므로 변경된 파일을 읽습니다.
- Linux에서만 작동합니다. macOS와 Windows의 Docker Desktop은 `/var/run/docker.sock`만 가상 머신 안으로 매핑합니다. 그곳에서 `/var/run`은 Mac이나 PC의 폴더이며, 그 안에 Docker 소켓이 없습니다.
- rootless Docker에서는 소켓이 별도 마운트인 `/run/user/<your uid>`에 있습니다. 그 폴더를 `source`로 사용하십시오.
- Podman에서는 파일 바인드를 유지하십시오. 그곳에서는 폴더 바인드를 테스트하지 않았습니다.

폴더 바인드에는 Compose 2.30과 Linux가 필요하고 CashPilot은 이전 Compose 릴리스와 Docker Desktop도 지원하므로, 배포되는 파일은 파일 바인드를 유지합니다. 새로 내려받은 compose 파일에는 직접 한 변경이 들어 있지 않으므로, 파일을 교체한 뒤 다시 변경하십시오.
