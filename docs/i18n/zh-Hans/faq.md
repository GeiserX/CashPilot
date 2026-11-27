---
source_hash: 915470497dbc
---
# 常见问题 { #faq }

**带宽共享安全吗？**

带宽共享服务通常通过你的连接转发合法流量（市场调研、广告验证、比价、内容分发）。尽管如此，你共享的是自己的 IP 地址，所以注册之前请仔细阅读每个服务的服务条款和隐私政策。对某些服务来说，在 VPS 而不是住宅 IP 上运行也是一种选择。**这不是法律建议：请向你打算使用的具体服务咨询，必要时就你所在的司法管辖区寻求独立的法律意见。**

**我能赚多少？**

收益因地点、ISP、设备数量以及你运行哪些服务而差别很大。仪表板会长期跟踪你的实际收益，方便你优化配置。作为粗略参考（而不是承诺），一台运行 10 到 15 个服务的家庭服务器每月大约能赚 $30 到 $100，也可能更少，甚至为零。更多服务器或 GPU 算力会在此基础上增加收益。

**我可以在 VPS 或云服务器上运行吗？**

有些服务要求住宅 IP，对 VPS/数据中心 IP 不付款（或会封禁）。目录会在服务所需条件中列出“住宅 IP”。能在 VPS 上运行的服务是在不增加家庭硬件的情况下扩大规模的好办法。

**凭据是如何存储的？**

所有服务凭据都在 SQLite 数据库中进行静态加密，使用存放在 `/data/.fernet_key` 的 Fernet 密钥，该密钥在首次运行时自动生成。数据库文件位于挂载的 Docker 卷中（`cashpilot_data:/data`）。除了服务容器本身之外，凭据从不会被发送到任何地方。

注意，这与 `CASHPILOT_SECRET_KEY` 是不同的密钥，后者只用于签名登录会话。

### 备份加密密钥 { #backing-up-the-encryption-key }

你的凭据能否恢复，完全取决于 `/data/.fernet_key`。如果丢失了这个文件，你就必须重新输入每一个凭据，因为没有它就无法解密已存储的值。

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

文件始终优先于环境变量，所以在已经有密钥的实例上设置 `CASHPILOT_ENCRYPTION_KEY` 不会改变任何东西，是安全的。只有在密钥文件不存在时才会采用它，而这正是恢复的情形。

如果 CashPilot 根本无法把密钥写入磁盘（因为 `/data` 不可写或未挂载），它会拒绝启动，而不是用一个下次重启就会消失的密钥加密你的凭据。如果这确实是你想要的，请设置 `CASHPILOT_ALLOW_EPHEMERAL_KEY=true`。

<a id="forgot-password"></a>

### 忘记密码或用户名 { #forgot-password-or-username }

CashPilot 没有通过电子邮件重置的功能。由运行服务器的人从 CashPilot UI 容器的控制台重置密码。你的服务、收益和已保存的凭据不受影响：它们是用 `/data/.fernet_key` 加密的，而不是用你的密码。

`python -m app.users` 命令需要 CashPilot 2.3 或更高版本。在 2.2 或更早版本上，它会以 `No module named app.users` 失败。请先更新：使用 Docker Compose 时，把 `drumsergio/cashpilot` 和 `drumsergio/cashpilot-worker` 的标签改为 `2.3` 或更高（像 `2.2` 或 `2.2.9` 这样的固定标签会一直停留在那个版本），然后运行 `docker compose up -d`（[更新 CashPilot](getting-started.md#updating-cashpilot)）。在 Unraid 上，更新该容器。

1. 列出账户。这也会显示你忘记的用户名。用户名区分大小写。

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. 为该账户设置一个新的随机密码。把 `alice` 替换为第 1 步中的用户名。

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    如果恰好只有一个所有者，你可以省略用户名，命令会重置那个所有者。如果用户名以 `-` 开头，请在它前面加上 `--`：`reset-password -- -alice`。

    命令会把新密码打印一次。

3. 如果可能有其他人访问过该账户，请现在重启 UI 容器（`docker restart cashpilot-ui`）。仍以该用户身份登录的浏览器只有在重启后才会退出登录。如果你只是忘记了密码，重启是可选的。
4. 用新密码登录，然后从头像菜单（右上角）的 **Change password** (修改密码) 修改它。

容器名称取决于你安装 CashPilot 的方式：

| 安装方式 | UI 容器 |
|---|---|
| `docker-compose.yml`、CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot`（`docker exec -it cashpilot python -m app.users list`） |
| Runtipi | 自动生成的名称；`docker ps` 会显示它 |

Portainer、Unraid 和 CasaOS 也为容器提供了控制台按钮。该命令不需要终端输入，所以在那里也能运行。

要修改用户名：

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

新名称遵循注册规则：3 到 32 个字母、数字、`_` 或 `-`。退出后重新登录即可看到它。

**在怀疑遭到入侵之后**，例如丢失了一份包含 `/data/.secret_key` 的备份，仅重置密码是不够的。拥有该密钥的人可以签发有效的登录 cookie，重置密码无法阻止这一点。请更换该密钥，然后重启 UI 容器。`&&` 只在新密钥就位时才会重启它；如果命令打印出错误，请先解决错误：

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

重启后，所有浏览器都会退出登录，每个人都要用自己的密码重新登录。已保存的凭据不受影响。如果你自己设置了 `CASHPILOT_SECRET_KEY`，该命令会拒绝执行：请改为在该变量中放入一个新的随机值，然后重建容器。从镜像执行的 `docker run` 看不到该变量，因而无法拒绝，所以请对 UI 容器使用 `docker exec`。

新密钥能终结伪造的 cookie，但无法撤销攻击者在入侵期间做过的事。还要做两步：

1. 运行 `docker exec cashpilot-ui python -m app.users list`。在仪表板中删除任何你不认识的账户。
2. 如果丢失的副本包含整个 `/data`，请修改你在各提供商处账户的密码。`.fernet_key` 和 `cashpilot.db` 合在一起可以解密每一个已保存的凭据。

如果你之后恢复了一份在轮换之前做的备份，请不要恢复其中的 `.secret_key`（[备份与恢复](backup-restore.md#restore)），或者再轮换并重启一次。否则旧密钥会回来。恢复的数据库还会带回它当时保存的账户和密码，所以请重复账户检查以及必要的密码重置。

**如果 UI 容器无法启动**，请用同一个镜像针对同一份数据运行该命令。先找到存放 UI `/data` 的主机文件夹。这对已停止的容器有效，也同时适用于命名卷和绑定挂载（Unraid、CasaOS、Runtipi）：

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

然后挂载该文件夹，并使用你正在运行的镜像标签：

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

确认列表中显示了你的账户，然后把同一行中的 `list` 换成 `reset-password alice` 再运行。

如果路径下没有数据库，会出现“no database”错误，命令不会在那里创建或修改任何东西。Docker 仍可能留下一个同名的空文件夹或卷；请把它删除。

**不要**删除数据卷：那会抹掉 `/data/.fernet_key`，并连带抹掉每一个已保存的凭据。也**不要**从 `users` 表中删除行。

**如何彻底删除 CashPilot？**

`docker compose down -v` 只会删除 CashPilot 自己的容器。它部署的服务会继续运行，它们的数据、隔离网络和一个防火墙表也会保留下来。[彻底删除 CashPilot](uninstall.md) 会删除所有这些内容，说明哪些东西会永久丢失，并演示如何确认没有任何残留。

**安全性如何？**

CashPilot 部署的每个服务都运行在自己的容器中，所有 Linux capability 都被移除（少数服务只加回它们声明的那些），并设置了 `--security-opt no-new-privileges`，所以容器内的进程无法提升权限。除了服务声明的卷之外，容器看不到你的主机文件系统。在新安装中，工作节点还会用隔离墙把它们与你的 LAN、主机、tailnet 和云元数据隔开，因此它们只能访问互联网，访问不到任何本地资源（[网络隔离](isolation.md)）。在 Podman 上没有隔离墙：收益应用运行在 Podman 的默认网络上，可以访问你的 LAN，**Fleet** (机群) 页面会对此给出提示（[网络隔离](isolation.md)列出了可选方案）。从 1.70 之前的版本升级而来的安装，会把收益应用留在 Docker 的默认网桥上，可以访问你的 LAN，直到你在 **Fleet** (机群) 页面上点击 **Turn on isolation** (开启隔离)。自 2.0.7 起，Mysterium 也运行在隔离墙之后；通过 2.0.6 及更早版本部署的节点会一直留在主机网络上，直到你重新部署它（[把你的 Mysterium 节点移到隔离墙之后](mysterium-fence.md)）。[保护你的家庭网络](home-network-security.md)介绍了另一种做法：为你自己的网桥设置防火墙。服务凭据使用 Fernet 对称加密进行静态加密。UI 没有 Docker 访问权限。使用随附的 compose 文件时，工作节点从不会拿到原始的 Docker socket：它通过 `cashpilot-socket-proxy` 访问 Docker，该代理拒绝特权容器以及对 `/` 或 socket 的绑定（除非你把其中之一，或 socket 之上的某个文件夹，写进 `CASHPILOT_PROXY_BIND_MOUNTS` 或 `CASHPILOT_COMPOSE_DIR`：代理会照单全收），并把工作节点限制在带有其所有者标签的容器、卷和网络上（[安全默认设置](security-defaults.md)）。Unraid 模板和 TrueNAS 应用仍然在工作节点中挂载原始 socket，这相当于主机上的 root（[应用商店](app-stores.md)）。

尽管如此，没有任何配置是万无一失的。你运行的仍然是会把外部流量转发经过你网络的第三方软件。与直接在主机上运行这些服务相比，Docker 隔离大大缩小了攻击面，但并不能消除所有风险。我们建议在专用机器或 VLAN 上运行 CashPilot，及时更新 Docker 和主机操作系统，并在部署任何服务之前审查其开源代码。

**服务容器崩溃了会怎样？**

CashPilot 会持续监控容器健康状况。如果服务容器意外退出，它会被自动重启。仪表板会显示每个运行中服务的运行时间和健康状况。

**重新部署后，我的 Mysterium 节点无法启动。为什么？**

最常见的原因是其 UDP 端口范围中的某个端口已被主机上的另一个程序占用。Docker 必须预留该范围内的每个端口，所以只要有一个端口被占用，启动就会失败。[选择 UDP 端口范围](mysterium-fence.md#choosing-the-udp-port-range)说明了如何选一个不会被占用的范围。

**我的代理副本在运行，但什么也赚不到。为什么？**

代理可能拒绝连接到该收益应用的服务器，或者只允许 80 和 443 端口。CashPilot 的 **Test** (测试) 只检查代理能否访问互联网。[通过代理探测收益应用的服务器](proxies.md#probe-an-earners-servers-through-the-proxy)演示了如何检查收益应用自己的主机和端口。

**哪些服务比较重，应该在哪里运行？**

存储节点、中继和 VPN 出口节点，以及 GPU 任务消耗最多。[为小机器做资源预算](fleet.md#budgeting-a-small-box)列出了它们，并演示了在做决定之前如何测量每个容器。

<a id="worker-lost-docker"></a>

### Docker 更新后工作节点失去了 Docker { #the-worker-lost-docker-after-a-docker-update }

**你看到的现象。** 工作节点在 **Fleet** (机群) 页面上保持在线，但 CashPilot 无法启动、停止或更新它的容器。**Fleet** (机群) 页面会在该工作节点旁显示 **Docker unreachable** (无法访问 Docker)。10 分钟后，工作节点的健康检查失败（`docker ps` 显示工作节点为 `unhealthy`）。30 分钟后，铃铛和你的通知会提示该工作节点无法访问 Docker。`docker logs cashpilot-socket-proxy` 显示 `upstream Docker socket unreachable`，使用当前的 compose 文件时，`docker ps` 会在大约 3 分钟内显示代理为 `unhealthy`。你的收益应用会继续运行。

**原因。** 随附的 compose 文件把 socket 文件 `/var/run/docker.sock` 绑定到 `cashpilot-socket-proxy` 中。文件绑定只持有那一个文件。Docker 更新（例如 `unattended-upgrades` 安装新的 `docker-ce`）会重启 Docker，而 Docker 会在同一路径上创建一个新的 socket 文件。开启 Docker 的 live-restore 时，代理会在这次重启中继续运行，并保留旧文件。旧文件上不再有任何东西应答。

**快速修复。** 在那台机器上重启代理：

```bash
docker restart cashpilot-socket-proxy
```

重启会绑定新的 socket，工作节点会在下一次心跳时重新找到 Docker。你不必重启工作节点。在 Unraid 和 TrueNAS 上，工作节点自己持有 socket，所以要重启工作节点。

**长期修复。** 绑定 socket 所在的文件夹，而不是 socket 文件。文件夹绑定会立即反映被替换的 socket。在 compose 文件的 `cashpilot-socket-proxy` 服务中，把 `- /var/run/docker.sock:/var/run/docker.sock:ro` 这一行替换为下面的绑定，并在它的 `environment` 中添加 `SOCKGUARD_UPSTREAM_SOCKET` 这一行：

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

然后运行 `docker compose up -d`。同样的修改也适用于 `docker-compose.worker.yml` 和 `docker-compose.fleet.yml`。Compose 只有在你指定这些文件时才会读取它们，所以请运行 `docker compose -f docker-compose.worker.yml up -d` 或 `docker compose -f docker-compose.fleet.yml up -d`，除非 `COMPOSE_FILE` 已经指定了该文件。

- `recursive: disabled` 是必需的。`/var/run` 中还有其他挂载，例如 `/run/docker/netns` 下 Docker 的网络命名空间以及 `/run/user/...`。递归绑定会把它们全部带进代理。非递归绑定只显示该文件夹本身。
- `SOCKGUARD_UPSTREAM_SOCKET` 让代理使用新路径。策略块及其指纹保持不变，因为该环境变量会覆盖策略中的 `upstream.socket`。没有这个变量，代理就无法启动（`upstream socket not found (/var/run/docker.sock)`）。
- `cashpilot-migrate` 可以保留它的文件绑定。它在每次 `docker compose up` 时都会重新启动，所以总能拿到当前的 socket。如果你给它同样的文件夹绑定，请在它的 `environment` 中添加 `DOCKER_HOST=unix:///host-run/docker.sock`。工作节点 2.8.4 及更高版本会读取这个变量。永远不要把它指向代理的 socket：迁移程序需要的是主机自己的 socket。
- 文件夹绑定会把 `/var/run` 中的每个 socket 都交给代理，而不只是 Docker 的。在典型的服务器上，这包括 systemd 自己的 socket、D-Bus，以及 Tailscale 或 snapd 等工具的 socket。`read_only` 并不能阻止程序连接到 socket，而且代理以 root 身份运行。访问 Docker socket 本来就等于拥有主机上的 root，所以被攻破的代理也得不到多少它原本没有的东西。如果你希望代理只持有 Docker socket，请保留文件绑定，并在 Docker 更新后重启代理：上面的警报会告诉你何时需要这样做。
- 它需要 Docker Compose 2.30.0 或更高版本。更早的版本会以 `Additional property recursive is not allowed` 拒绝整个文件。运行 `docker compose version` 来检查。Debian 13 打包的是 Compose 2.26.1，所以在 Debian 上请从 Docker 自己的仓库安装 Compose。应用内更新使用它自带的 Compose 2.33，所以能读取修改后的文件。
- 它只在 Linux 上有效。macOS 和 Windows 上的 Docker Desktop 只把 `/var/run/docker.sock` 映射进它的虚拟机。在那里，`/var/run` 是你 Mac 或 PC 上的一个文件夹，里面没有 Docker socket。
- 使用 rootless Docker 时，socket 位于 `/run/user/<your uid>`，那是一个单独的挂载。请把该文件夹用作 `source`。
- 在 Podman 上，请保留文件绑定。我们还没有在那里测试过文件夹绑定。

随附的文件保留文件绑定，因为文件夹绑定需要 Compose 2.30 和 Linux，而 CashPilot 也支持更早的 Compose 版本和 Docker Desktop。你下载的较新 compose 文件不包含你的修改，所以替换文件后请再改一次。
