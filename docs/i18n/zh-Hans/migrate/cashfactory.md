---
source_hash: 7f8476aeb8b6
---
# 从 CashFactory 迁移 { #moving-from-cashfactory }

CashPilot 可以读取 CashFactory 的 `.env`，把你的服务登录信息带过来，
这样你不必再输入一遍。在 CashPilot 保存之前，你会逐项检查。

## 开始之前 { #before-you-start }

你需要 CashPilot 的所有者账户，以及至少一个 CashPilot 工作节点。

在一台机器上从 CashPilot 部署相同的服务之前，先在该机器上停止 CashFactory。
同一连接后面的两个副本只会按一个计算收益，而且同一个 EarnApp
设备 id 不能运行两次。在 CashFactory 文件夹中运行 `docker compose down`。
它的
[compose 文件](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
还会启动三个挂载 Docker socket 的容器：Portainer（第 31 行）
和两个 Watchtower 容器（第 141 行和第 264 行）。确保它们也都已停止：`docker ps` 应该
一个也不列出。

## 使用哪个文件 { #which-file-to-use }

使用 CashFactory 文件夹中的 `.env` 文件，也就是你根据
[示例](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env)填写的那个文件。

Docker Compose 会读取该文件，并展开不在
单引号中的值里的 `$`。这样的值并不是文件中显示的样子，所以 CashPilot 会让
你重新输入，而不是去猜。

## 如何导入 { #how-to-import }

1. 打开 **Settings** (设置)，然后打开 **Import from another tool** (从其他工具导入)（或访问 `/import`）。
2. 添加 `.env` 文件，或粘贴它的文本。把工具保留为 **Tell from the files** (根据文件判断)，
   或者选择 CashFactory。
3. 检查表格。勾选你想要的服务，并填写所有标记为
   缺失的值。
4. 按下 **Save the ticked services** (保存勾选的服务)，然后在同一页面上
   把它们部署到你的工作节点。

## 会带过来的内容 { #what-comes-over }

| CashFactory 应用 | 读取的键 | CashPilot 服务 | 会带过来的内容 |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | 设备 id，这样你已关联的设备会继续赚钱 |
| `honeygain` | `HONEYGAIN_EMAIL`、`HONEYGAIN_PASSWD` | Honeygain | 邮箱、密码 |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`、`IPROYALPAWNS_PASSWD` | IPRoyal Pawns | 邮箱、密码 |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | 令牌 |
| `repocket` | `RP_EMAIL`、`RP_API_KEY` | Repocket | 邮箱、API 密钥 |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | 用户 id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | 设备 UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API 密钥 |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | 无：已不再提供 |

仍然显示示例占位符（`<email>`、`sdk-node-<md5sum>`）的值
视为未设置，只有占位符的服务会从
表格中省略。

## 永远不会带过来的内容 { #what-never-comes-over }

- **`DEVICE_NAME`。** CashPilot 以设备所运行的工作节点为每个设备命名，所以
  两个工作节点永远不会报告相同的名称。你的旧设备会在各提供商的仪表板中
  一直显示为离线，直到你在那里删除它们。
- **Bitping。** CashFactory 把 Bitping 登录信息保存在 Docker 卷中，而不是
  `.env` 中，所以导入没有可读取的内容，也不会显示 Bitping 这一行。请在
  Bitping 的部署表单中输入登录信息。
- **Portainer 和 Watchtower。** CashPilot 会管理并更新它自己的
  容器。

## 收益跟踪 { #earnings-tracking }

对于 Honeygain 和 IPRoyal Pawns，容器登录信息同时也是账户登录信息，
所以 CashPilot 也会填写它们的收益凭据，除非你已经在
**Settings** (设置) 中设置过。对于其他每个服务，请在
**Settings > Earnings collection** (设置 > 收益采集) 中添加收益登录信息。

## 安全 { #safety }

- 文件中的任何内容都不会被运行或展开，其中的任何地址都不会被访问。
- 文件只读取一次，不会保留。你保存的内容会加密存储，就像
  CashPilot 中的其他所有凭据一样。
- 机密在页面上只显示为 **set** (已设置)。
- 已保存的导入会一直留在导入页面上，直到你按下 **Forget** (忘记)，所以你之后
  还可以把它们部署到更多工作节点。
