---
source_hash: 06e0336d2a02
---
# CashPilot 与同类项目的比较 { #how-cashpilot-compares }

本页把 CashPilot 与其他在 Docker 中运行多个被动收入应用的开源项目进行比较。我们在 2026-11-04 检查了每个项目，并在 2026-11-28 再次检查了 CashPilot。关于其他项目的每个单元格都链接到其信息来源文件，并固定在某个提交上，方便你自己核对。如果某个单元格有误或已过时，请[提交 issue](https://github.com/GeiserX/CashPilot/issues)。

## 参与比较的项目 { #projects-compared }

| 项目 | 我们检查的内容 | 2026-11-04 的星标数 | 许可证 |
|---|---|---|---|
| [money4band][m4b-tree] | 版本 5.0.0，标签提交 `af9d903`（2026-07-25） | 471 | GPL-3.0 |
| [income-generator][igm-tree]（IGM） | `main` 位于 `65e900d`（2026-10-20），外加 README 中关于其 3.0.0-beta.9 二进制文件的说法 | 238 | 专有，[自有许可证 v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` 位于 `db9338a`（2026-11-03） | 257 | 没有 LICENSE 文件。[README][ii-license] 允许复制原版，禁止分发修改后的副本 |
| [CashFactory][cf-tree] | `main` 位于 `0ff4bd0`（2025-04-08） | 410 | [LICENSE][cf-license-file] 文件是 GPL-3.0，但 [README][cf-license] 禁止分发修改后的副本 |
| [home-assistant-passive-income][ha-tree]（HA 加载项） | 版本 2.0.6，`bf4b9f4`（2026-11-03） | 105 | Unlicense |
| CashPilot | 版本 v3.0.1，`47a07fb`（2026-11-27） | 77 | GPL-3.0 |

money4band 有两条代码线。它的默认分支 `main`（`3bfafb1`）仍然是 4.x 代码，那里最后一次代码改动是在 2026-03-03。版本 5.0.0 构建自一段单独的历史。我们比较 5.0.0，因为它的最新版本发布的就是这个。

IGM 的 Web UI、机群管理和安装程序二进制文件都是闭源的，不在它的仓库中。凡是依赖这些内容的单元格，都会注明“README 声称”，并链接到 README 中的对应行。IGM 一列中的其他内容都来自仓库里的 shell 脚本和 compose 文件。

未纳入比较：[earning-machine](https://github.com/jf-m/earning-machine) 和 [passiveMachine](https://github.com/Xpl0itU/passiveMachine) 自 2024 年以来没有任何提交。GitHub 搜索没有找到其他仍在维护、能运行不止一个应用的项目，只有单应用镜像。

## 简短版本 { #short-version }

- **InternetIncome、money4band、IGM，以及自 v1.69.0 起的 CashPilot，都能通过代理在多个 IP 上赚钱。** 前三者为每个代理运行一次每个应用，代理也是 InternetIncome 的主要功能。CashPilot 为工作节点上已部署的服务运行额外副本，每个副本都经由一个 SOCKS5、HTTP CONNECT 或 Tailscale 出口节点代理（[代理副本](proxies.md)）。
- **InternetIncome 能启动 23 个应用，IGM 能启动 20 个，CashPilot 的工作节点能启动 <!-- n:docker -->21<!-- /n --> 个。** CashPilot 跟踪的服务总数更多（<!-- n:live -->50<!-- /n --> 个），因为它还跟踪自己不运行的浏览器扩展、桌面和 GPU 服务。自 v1.64.0 起，它还能把你指定的任何镜像作为[自定义服务](custom-services.md)运行。
- **money4band 和 IGM 会替你领取每日奖励，并用 Watchtower 保持应用镜像更新。** CashPilot 这两样都不做。它只在你部署或重新部署时才重新拉取镜像。
- **CashPilot 是这里唯一一个从你的提供商账户读取余额并保留历史记录的项目。** money4band 5.0.0 显示的是来自它自己目录的估算值，而不是你的账户数据。其他项目则链接到各提供商的仪表板。
- **CashPilot 是这里唯一一个用一个 UI 管理多台服务器的开源项目。** IGM 的 README 声称有机群管理，但那部分代码在它的闭源二进制文件中。
- **自 v1.70.0 起，CashPilot 是这里唯一一个默认让收益应用容器远离你 LAN 的项目，但有限制。** 它对新安装开启，也对没有任何收益应用位于 Docker 默认网桥上的升级安装开启。收益应用已经位于该网桥上的升级安装，会一直留在那里，直到你开启隔离；你在 `CASHPILOT_CONTAINER_NETWORK` 中指定的网络不会获得 CashPilot 的隔离墙（[隔离](isolation.md#modes)）。自 2.0.7 起，Mysterium 也运行在隔离墙之后；通过 2.0.6 及更早版本部署的节点会留在主机网络上、不受隔离墙保护，直到你重新部署它（[隔离墙之后的 Mysterium](mysterium-fence.md)）。

## 逐项对比 { #side-by-side }

CashPilot 一列描述的是 v3.0.1。这一列的每个单元格都很简短，[表格下方的说明](#cashpilot-notes)给出了细节和代码链接。其他列描述的是上表中的提交。

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA 加载项 |
|---|---|---|---|---|---|---|
| 能启动的应用（见[我们如何计数](#how-we-counted)） | 工作节点运行 <!-- n:docker -->21<!-- /n --> 个，另加[自定义镜像](custom-services.md)；总共跟踪 <!-- n:live -->50<!-- /n --> 个 | 15 个（[目录][m4b-catalog]）。README 说是 35 个，这个数字[包括][m4b-readme-35]社区应用和已弃用的应用 | 20 个（[apps.json][igm-apps]） | 23 个（[脚本][ii-script]） | 11 个（[compose 文件][cf-compose]） | 10 个（[加载项文件夹][ha-tree]） |
| 安装方式 | Docker Compose：一个 UI，外加每台服务器上一个工作节点（[机群](fleet.md)） | Python CLI，或一个会写出 compose 文件的预构建二进制文件（[版本][m4b-tree]） | `curl \| sh` 安装程序（[README][igm-install]），它会下载一个闭源二进制文件，只用同一版本中的 SHA256SUMS 文件进行校验（[安装程序][igm-installer-sums]） | 一个 1,608 行的 bash 脚本，调用 `sudo docker run`（[脚本][ii-script]） | 一个静态 compose 文件，外加用 sudo 运行的 `setup.sh`（[设置][cf-setup]） | 一个 Home Assistant 加载项仓库；需要 Home Assistant OS 或 Supervised |
| 多台服务器，一个视图 | 是（[机群](fleet.md)） | 否，每台设备一个堆栈 | README 声称是，在闭源二进制文件中（[README][igm-features]） | 否 | 否 | 否 |
| 多个代理或 IP | 是，通过 SOCKS5、HTTP CONNECT 或 Tailscale 出口节点代理（[代理副本](proxies.md)、[说明](#cashpilot-notes)） | 是（[README][m4b-features]、[代码][m4b-multiproxy]） | 是（[README][igm-features]、[compose][igm-proxy]） | 是，这是它的主要功能（[README][ii-readme-top]） | 否 | 否 |
| 收益 | <!-- n:collectors -->20<!-- /n --> 个采集器从你的提供商账户读取余额并保留历史记录 | 基于目录范围的估算值，而不是账户数据（[代码][m4b-earnings]） | 在脚本中未发现 | 无 | 无 | 无 |
| 付款 | 余额下降时提议记录一笔付款，并在你确认后记录它（[schema][cp-payouts]） | 无 | 无 | 无 | 无 | 无 |
| 领取每日奖励 | 否 | 是，通过边车容器（[README][m4b-features]） | 是（[README][igm-features]、[compose][igm-sidecars]） | 否 | 否 | 否 |
| 静态存储的凭据 | 在 UI 的数据库中加密（Fernet）（[说明](#cashpilot-notes)） | 加密（Fernet）；密钥文件位于数据目录中（[代码][m4b-crypto]） | 加密（用 openssl 进行 AES-256）；密钥文件就在保险库旁边（[代码][igm-encryptor]） | 在 `properties.conf` 中是明文；有些密码作为 `docker run` 参数传递（[脚本][ii-password-arg]） | 在 `.env` 中是明文（[文件][cf-env]） | 加载项选项，由 Supervisor 存储在 `/data/options.json` 中（[HA 文档][ha-options]） |
| 收益应用容器设置 | 移除所有 capability，`no-new-privileges`，进程数（pids）限制；拒绝特权模式（[说明](#cashpilot-notes)） | 每个非特权服务都设置了 `no-new-privileges`（[代码][m4b-nnp]）；代理容器是特权容器，带 `NET_ADMIN`（[模板][m4b-tun]） | 应用服务上什么都没设置；Mysterium 获得 `NET_ADMIN`（[compose][igm-hosting-myst]）；代理容器获得 `NET_ADMIN`，带 `no-new-privileges` 和进程数限制（[compose][igm-proxy]） | Ebesucher 以 `seccomp=unconfined` 运行（[脚本][ii-seccomp]）；代理容器和 Mysterium 获得 `NET_ADMIN` | 什么都没设置 | 没有任何加载项要求特权模式、主机网络或 Docker API 访问（[示例配置][ha-config]） |
| Docker socket 挂载到 | socket 代理（只读），以及一个只运行一次的迁移容器（[说明](#cashpilot-notes)） | Watchtower（[模板][m4b-watchtower]） | Watchtower，只读，带 `no-new-privileges`（[compose][igm-watchtower]） | 五个重启辅助容器（[脚本][ii-sock-helper]）和 Watchtower（[脚本][ii-watchtower]） | Portainer，在所有网络接口上发布 8000、9000 和 9443 端口（[compose][cf-portainer]），以及两个 Watchtower（[compose][cf-watchtower-ps]、[compose][cf-watchtower-efm]） | 无 |
| 镜像标签 | <!-- n:docker -->21<!-- /n --> 个收益应用镜像中有 <!-- n:pinned -->9<!-- /n --> 个固定到某个版本或摘要；其余的是浮动的 | 所有 15 个应用镜像都使用 `:latest`（[示例][m4b-image]）；代理容器固定为 v2.6.0，Watchtower 固定为 `:1` | 没有标签，所以 Docker 使用 `latest`（[compose][igm-hosting]）；只有部分 ARM 构建设置了标签 | 大多是 `:latest`（[示例][ii-seccomp]）；EarnApp 为 `:lite`，在 amd64 上通过代理运行时 Honeygain 固定为 0.6.6（[脚本][ii-honeygain]），Traffmonetizer 在 ARM 上使用按架构区分的标签；Watchtower 为 `:nightly` | `:latest` 或没有标签，EarnApp 的 `:lite` 除外（[compose][cf-compose]） | 每个加载项一个版本，由每日 CI 任务更新（[工作流][ha-bump]、[示例][ha-dockerfile]） |
| 应用镜像更新 | 每次部署或重新部署时重新拉取；没有自动更新工具 | Watchtower（[模板][m4b-watchtower]） | Watchtower，每 4 小时一次（[compose][igm-watchtower]） | Watchtower，每天一次，如果你开启的话（[脚本][ii-watchtower]） | 两个 Watchtower，各自只负责一个应用：PacketStream（[compose][cf-watchtower-ps]）和 EarnFM（[compose][cf-watchtower-efm]）；其他 9 个应用不会更新 | Home Assistant 的加载项更新 |
| LAN 隔离 | 对新安装默认开启（[隔离](isolation.md#lan-isolation-by-default)、[说明](#cashpilot-notes)） | 自有网桥子网（[配置][m4b-subnet]），但它不会阻止访问 LAN | 没有已合并的实现 | 未发现 | 未发现 | 未发现 |
| ARM | arm64 的 UI 和工作节点，每次部署前都会检查平台（[ARM](arm.md)） | arm64 和 armv7 二进制文件（[版本][m4b-release]） | README 声称支持 amd64 和 arm64，有限支持 arm32，并会设置 QEMU（[README][igm-arch]） | 对只有 amd64 的镜像需要 binfmt 模拟（[README][ii-arm]） | README 说它不能在 Raspberry Pi 上运行（[README][cf-raspberry]） | 因加载项而异；ProxyRack 只支持 amd64（[配置][ha-proxyrack]） |
| UI | Web UI，另有 Desktop、Android、MCP 和 Home Assistant 客户端 | CLI、菜单，以及一个默认绑定到 127.0.0.1 的本地 Web 仪表板（[代码][m4b-bind]） | CLI、菜单，以及据 README 所说一个在 4747 端口、可从 LAN 访问的 Web UI（[README][igm-webui]） | 无，只是一个脚本 | 80 端口上的一个书签页面，外加 Portainer（[README][cf-ui]） | Home Assistant 加载项面板 |
| 最新版本 | v3.0.1，2026-11-27 | 5.0.0，2026-07-25 | 3.0.0-beta.9，2026-09-23 | 没有带版本号的发布 | v1.10，2024-07-17 | 2.0.6，2026-11-03 |
| 应用之外的对外调用 | 更新检查、公网 IP 查询、汇率和链上余额；来自 CDN 的字体和 Chart.js（[说明](#cashpilot-notes)） | 访问 GitHub releases 进行更新检查（[代码][m4b-updater]）；访问 Docker Hub 和 ghcr.io 检查镜像标签（[代码][m4b-registry]）；在你运行 IP 检查时，访问 `api.ipify.org`、`ifconfig.me` 或 `icanhazip.com` 获取你的公网 IP，并通过明文 HTTP 访问 `ip-api.com` 获取 IP 评分（[代码][m4b-ipscore]） | 访问 GitHub releases（[代码][igm-version]）；访问 `api.ipify.org`、`ifconfig.me` 或 `icanhazip.com` 获取你的公网 IP（[代码][igm-ifconfig]）；通过明文 HTTP 访问 `ip-api.com` 获取 IP 评分（[代码][igm-ipscore]）。闭源二进制文件未经检查 | 未发现 | 未发现 | 未发现 |

### 关于 CashPilot 一列的说明 { #cashpilot-notes }

- **多个代理或 IP。** 自 v1.69.0 起，CashPilot 会为已部署在工作节点上的服务运行额外副本，每个副本都经由自己的代理。SOCKS5 和 HTTP CONNECT 只承载 TCP：隧道只放行发往代理端口的 TCP，所以 SOCKS5 的 UDP 中继会被丢弃。Tailscale 出口节点也承载 UDP。收益应用与一个隧道容器共享网络命名空间（[代码][cp-proxy-deploy]）。该命名空间只放行回环、隧道以及隧道自身到代理的连接：发往其地址和端口的 TCP，或 tailscaled 标记的数据包（[隧道防火墙][cp-tunnel-fw]）。所以代理失效时，收益应用会停止，而不会泄漏流量（[工作原理](proxies.md#how-it-works)）。如果服务需要主机网络、发布端口、卷、设备、GPU 或 `NET_ADMIN`、`NET_RAW` 或 `SYS_ADMIN`，或者其条款禁止使用代理，它就无法通过代理运行。所以 <!-- n:docker -->21<!-- /n --> 个收益应用中有 <!-- n:noproxy -->10<!-- /n --> 个只能用服务器自己的 IP 赚取收益（[无法通过代理运行的服务](proxies.md#what-cannot-run-through-a-proxy)）。
- **收益。** 有些采集器需要从你的浏览器复制的 cookie 或令牌，其中一些会过期。各服务的指南会说明是哪些。
- **静态存储的凭据。** UI 把加密密钥文件放在与数据库相同的数据卷中（[代码][cp-fernet]）。收益应用的凭据以容器环境变量的形式到达每个工作节点，所以在该工作节点的 Docker 配置中是明文（`docker inspect`）。
- **收益应用容器设置。** 工作节点移除所有 capability，然后加回目录为该服务列出的那些。它设置 `no-new-privileges` 和进程数（pids）限制，并拒绝特权容器（[代码][cp-hardening]、[代码][cp-privileged]、[安全默认设置](security-defaults.md)）。Mysterium 在隔离网桥上的自有网络命名空间中运行，带 `NET_ADMIN`、`SETUID` 和 `SETGID`，使用按摘要固定的镜像（[目录][cp-myst]）。可选的 gVisor 运行时可以再加一层用户空间内核（[运行时](security-defaults.md#container-runtimes-gvisor-where-it-works)）。
- **Docker socket。** 自 v1.71.0 起，工作节点不再持有 socket。socket 由 socket 代理持有：sockguard 2.4.7，按摘要固定，只读（[compose][cp-sock]）。工作节点获得一个经过过滤的副本，它拒绝特权容器、对 `/` 或 socket 的绑定，以及目录之外的 capability 或设备（[socket 代理](security-defaults.md#docker-socket-proxy)）。只运行一次的 `cashpilot-migrate` 容器也会挂载 socket。它为旧版本创建的卷和隔离墙网络加上所有者标签，并在其上重新创建它们的容器，使代理的所有者隔离也覆盖它们。它在代理启动前退出（[compose][cp-migrate]）。收益应用从不获得 socket（[代码][cp-mounts]）。该代理还不是一道 root 边界。设置了 `CASHPILOT_COMPOSE_DIR` 或 `CASHPILOT_PROXY_BIND_MOUNTS` 时，被攻破的工作节点可以用一个容器在允许的文件夹中放置符号链接，再用第二个容器触及主机的 `/`（[详情](security-defaults.md#docker-socket-proxy)）。Unraid 和 TrueNAS 的应用条目仍会把原始 socket 挂载到工作节点中（[应用商店](app-stores.md)）。
- **LAN 隔离。** 自 v1.70.0 起，对新安装以及没有任何收益应用位于 Docker 默认网桥上的升级安装默认开启。工作节点把收益应用放到它自己的网桥上，并为该网桥写入一个防火墙表（[代码][cp-fence]）。该表丢弃发往私有地址段、tailnet 地址段、云元数据、主机已连接的子网以及主机本身的流量。开启公网 IP 检测时，它还会丢弃发往家庭公网 IP 的流量（[隔离](isolation.md#lan-isolation-by-default)）。收益应用已经位于默认网桥上的升级安装会一直留在那里，直到你按下 **Turn on isolation** (开启隔离)。`CASHPILOT_ISOLATION=off` 会关闭它。设置了 `CASHPILOT_CONTAINER_NETWORK` 时，CashPilot 不为该网络写入隔离墙，防火墙规则由你负责。在 Podman 上没有隔离墙，机群页面会注明这一点（[模式](isolation.md#modes)、[代码][cp-fence-mode]）。自 2.0.7 起，Mysterium 也受隔离墙保护。通过 2.0.6 及更早版本部署的节点会留在主机网络上，直到你重新部署它（[隔离墙之后的 Mysterium](mysterium-fence.md)）。有一项检查可以显示收益应用能访问到什么（[检查](isolation-check.md)）。
- **对外调用。** 除应用本身之外，CashPilot 会访问：
    - GitHub releases，每天一次，用于更新检查（`CASHPILOT_UPDATE_CHECK=off` 可停止，[代码][cp-update]）。
    - `api.ipify.org`、`ifconfig.me` 或 `icanhazip.com`，每个工作节点每小时一次，以获取其公网 IP（`CASHPILOT_EGRESS_DETECT=off` 可停止，[代码][cp-egress]）。
    - CoinGecko 和 Frankfurter，用于汇率（[代码][cp-rates]）。
    - mempool.space、api.kaspa.org 以及公共的 Ethereum、Ethereum Classic、Polygon 和 Solana RPC 节点，用于[链上余额](onchain.md)。
    - iptoasn.com，用于 CashPilot 的网络名称表，最多每周一次，并且只在有工作节点开启了[活动](activity.md#network-names-and-countries)时访问（[代码][cp-ipgeo]）。
    - 各提供商，用于采集器。

    浏览器会加载 Google Fonts（[模板][cp-cdn]）以及来自 jsDelivr 的 Chart.js（[模板][cp-chartjs]）。

在我们读过的代码中，没有任何项目发送使用情况遥测数据。IGM 的闭源二进制文件无法读取。

这里的每个项目都以环境变量的形式把应用凭据传给容器，InternetIncome 还把其中一些作为命令参数传递，所以在运行这些应用的主机上，它们在 Docker 的容器配置中是明文（`docker inspect` 中的 `Env` 和 `Args`），任何拥有 Docker 访问权限的人都能读取。“静态存储的凭据”一行只描述存储下来的那份副本。

## 我们如何计数 { #how-we-counted }

- **CashPilot。** 目录中状态为 active 或 beta 且带有 Docker 镜像的服务，不计 GPU 算力和矿池。本页上的数字来自 `scripts/generate_readme_tables.py`，如果它出现偏差，CI 会失败。
- **money4band 5.0.0。** `config/catalog/supported/` 中每个应用一个 JSON 文件：15 个。README 中的“35 apps”还计入了默认关闭的社区目录（[配置][m4b-community]）、没有 Docker 镜像的应用以及已弃用的应用。
- **IGM。** `apps.json` 中的条目：20 个，全部启用。代理容器、Watchtower 和领取奖励的边车容器不计入。
- **InternetIncome。** `internetIncome.sh` 中每个 `# Starting ... container` 注释块，代理和 Watchtower 的块除外：24 个。Ebesucher 的 Chrome 和 Firefox 块算一个应用，EarnFM 和 EarnFM Fleetshare 也算一个，因为它们使用同一个 EarnFM 账户。Depin 扩展块会启动 Grass 和 Gradient（[脚本][ii-depin]），算两个应用。总计 23 个。README 的表格列出了 27 个应用，其中一些只有注册链接。
- **CashFactory。** `docker-compose.yml` 中的赚钱服务：11 个。Portainer、Web 服务器和两个 Watchtower 不计入。有一个服务被注释掉了。
- **HA 加载项。** 带有配置文件的加载项文件夹：10 个。

我们没有检查每个列表上的每个应用是否仍在付款。

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
