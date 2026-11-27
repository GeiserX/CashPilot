---
source_hash: ca9dd25d45ca
---
# 从 InternetIncome 迁移 { #moving-from-internetincome }

CashPilot 可以读取 InternetIncome 的 `properties.conf`，以及它
保存你的 EarnApp 和 ProxyRack 设备 id 的文件，并把它们带过来。在 CashPilot 保存之前，
你会逐项检查。

## 开始之前 { #before-you-start }

你需要 CashPilot 的所有者账户，以及至少一个 CashPilot 工作节点。

在一台机器上从 CashPilot 部署相同的服务之前，先在该机器上停止 InternetIncome。
同一连接后面的两个副本只会按一个计算收益，而且同一个设备 id
不能运行两次。在 InternetIncome 文件夹中运行：

```bash
sudo bash internetIncome.sh --delete
```

`--delete` 会删除容器，并保留 `earnapp.txt`、`proxyrack.txt` 和
Mysterium 数据文件夹。`--deleteBackup` 会把这些也一并删除
（[internetIncome.sh，第 61 至 64 行](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
和[第 1562 行](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)），
所以请先导入。

## 使用哪些文件 { #which-files-to-use }

从 InternetIncome 文件夹中：

- `properties.conf`，你的设置。
- `earnapp.txt`，如果你运行过 EarnApp。每一行保存一个设备链接
  （[第 1250 至 1261 行](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)）。
- `proxyrack.txt`，如果你运行过 ProxyRack。每行一个设备 UUID
  （[第 817 至 827 行](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)）。

CashPilot 取每个文件中的第一个设备：也就是你的主容器
使用的、你关联到账户的那个设备。其他行属于代理
副本，页面会告诉你省略了多少行。

InternetIncome 会让每个值都经过 shell 处理
（[第 1375 行](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)）。
单引号中的值按原样读取，这也是
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
中注释的建议。不在单引号中、却含有 `$`、反引号、空格或
其他会被 shell 改变的字符的值，并不是文件中显示的样子，所以
CashPilot 会让你重新输入，而不是运行一个 shell 去弄清楚。

## 如何导入 { #how-to-import }

1. 打开 **Settings** (设置)，然后打开 **Import from another tool** (从其他工具导入)（或访问 `/import`）。
2. 添加 `properties.conf`，如果有的话，再加上 `earnapp.txt` 和 `proxyrack.txt`。
   把工具保留为 **Tell from the files** (根据文件判断)，或者选择 InternetIncome。
3. 检查表格。勾选你想要的服务，并填写所有标记为
   缺失的值。Repocket 需要你的账户邮箱，而 InternetIncome 从未
   询问过它。
4. 按下 **Save the ticked services** (保存勾选的服务)，然后在同一页面上
   把它们部署到你的工作节点。

## 会带过来的内容 { #what-comes-over }

| InternetIncome 应用 | 读取的键 | CashPilot 服务 | 会带过来的内容 |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API 密钥（需补上你的邮箱） |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | 令牌 |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`、`proxyrack.txt` | ProxyRack | API 密钥、设备 UUID |
| `iproyals` | `IPROYALS_EMAIL`、`IPROYALS_PASSWORD` | IPRoyal Pawns | 邮箱、密码 |
| `honeygain` | `HONEYGAIN_EMAIL`、`HONEYGAIN_PASSWORD` | Honeygain | 邮箱、密码 |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | 用户 id |
| `earnfm` | `EARN_FM_API` | Earn.fm | API 密钥 |
| `earnapp` | `EARNAPP=true`、`earnapp.txt` | EarnApp | 设备 id |
| `bitping` | `BITPING_EMAIL`、`BITPING_PASSWORD` | Bitping | 邮箱、密码 |
| `mysterium` | `MYSTERIUM=true` | Mysterium | 开启；见下面关于 Mysterium 的说明 |

值为空表示该应用是关闭的，它不会被列出。

以下应用会被列出，但不会带过来：

| InternetIncome 应用 | 原因 |
|---|---|
| `urnetwork` | InternetIncome 使用会话令牌。CashPilot 用你的邮箱和密码登录 URnetwork。 |
| `grass` | Grass 以浏览器扩展的形式运行。CashPilot 只跟踪它，使用来自 Grass 仪表板的访问令牌。 |
| `titan`、`ebesucher`、`wipter` | CashPilot 跟踪这些服务，但没有可部署的容器。 |
| `peer2profit` | 已不再提供。 |

CashPilot 没有的应用（antGain、Adnade 等）的设置会
按名称列出，并标为未读取。

## 永远不会带过来的内容 { #what-never-comes-over }

- **`DEVICE_NAME`。** CashPilot 以设备所运行的工作节点为每个设备命名，所以
  两个工作节点永远不会报告相同的名称。你的旧设备会在各提供商的仪表板中
  一直显示为离线，直到你在那里删除它们。
- **代理**（`USE_PROXIES`、`proxies.txt`）。在 **Fleet** (机群) 页面的 **Proxies** (代理)
  部分逐个添加代理，然后让你的服务副本通过它运行；添加
  代理本身不会启动任何东西。设置 `USE_PROXIES=true` 时，InternetIncome 只通过代理
  运行你的服务。保存导入也不会启动任何东西。
  代理副本需要先在工作节点上部署相同的服务，而
  部署该服务会让它在工作节点自己的连接上运行，所以绝不能
  使用该连接的服务应保持未勾选。见[代理
  副本](../proxies.md)。
- **`BROWSER_USERNAME` 和 `BROWSER_PASSWORD`**，InternetIncome 自己的浏览器
  登录信息。

## 收益跟踪 { #earnings-tracking }

对于 Honeygain、IPRoyal Pawns 和 Bitping，容器登录信息同时也是
账户登录信息，所以 CashPilot 也会填写它们的收益凭据，除非你
已经在 **Settings** (设置) 中设置过。对于其他每个服务，请在
**Settings > Earnings collection** (设置 > 收益采集) 中添加收益登录信息。

## Mysterium { #mysterium }

导入会开启 Mysterium，但 CashPilot 会启动一个带有新
身份的新节点。旧节点的密钥库和所有未结算的收益都留在
InternetIncome 的 `mysterium-data` 文件夹中。请先结算它们，或者按照
[Mysterium 指南](../guides/mysterium.md)把身份迁移过来。

## 安全 { #safety }

- 文件中的任何内容都不会被运行或展开，其中的任何地址都不会被访问。
- 文件只读取一次，不会保留。你保存的内容会加密存储，就像
  CashPilot 中的其他所有凭据一样。
- 机密在页面上只显示为 **set** (已设置)。
- 已保存的导入会一直留在导入页面上，直到你按下 **Forget** (忘记)，所以你之后
  还可以把它们部署到更多工作节点。
