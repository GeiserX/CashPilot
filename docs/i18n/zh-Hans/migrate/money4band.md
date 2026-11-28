---
source_hash: 098dcc2576d9
---
# 从 money4band 迁移 { #moving-from-money4band }

CashPilot 可以读取 money4band 的配置，把你的服务登录信息带过来，
这样你不必再输入一遍。在 CashPilot 保存之前，你会逐项检查。

## 开始之前 { #before-you-start }

你需要 CashPilot 的所有者账户，以及至少一个 CashPilot 工作节点，它可以位于
money4band 现在运行的机器上，也可以位于另一台机器上。

在一台机器上从 CashPilot 部署相同的服务之前，先在该机器上停止 money4band。
同一连接后面的两个副本只会按一个计算收益，而且同一个 EarnApp
或 ProxyRack 设备 id 不能运行两次。使用 money4band 菜单中的 **Stop apps stack**
（[m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)），
或者在它的文件夹中运行 `docker compose down`。如果你设置了额外的代理
实例，也要逐个停止它们。

## 使用哪个文件 { #which-file-to-use }

使用 money4band 文件夹中的 `config/user-config.json`。如何把它交给
CashPilot，取决于你的 money4band 版本。

在 money4band 4.x 中，money4band 在你运行
**Setup Apps** 时写入该文件，其中保存的正是你输入的内容。它旁边的 `.env`
由该文件生成，同样可用；money4band 3.x 中手工编辑的
`.env` 也可以。两者都只保存在你的磁盘上：money4band 的
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
列出了它们。

money4band 5.0 会在磁盘上加密 `config/user-config.json`
（[安全说明](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)），
并在每次启动后删除它的 `.env`
（[env builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)）。
CashPilot 无法读取加密后的文件。请在 money4band 文件夹中运行 `m4b config edit`：
它会在你的编辑器中打开解密后的文件
（[CLI 参考](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)）。
复制其中的全部文本，粘贴到 **Import from another tool** (从其他工具导入) 页面，然后关闭编辑器。

优先使用 JSON 文件。在 `.env` 中，Docker Compose 会展开未加引号的值中的 `$`，
所以含有 `$` 的密码并不是文件中显示的样子。CashPilot 不会
猜测：它会让你重新输入这个值。

## 如何导入 { #how-to-import }

1. 打开 **Settings** (设置)，然后打开 **Import from another tool** (从其他工具导入)（或访问 `/import`）。
2. 添加 `user-config.json`，或粘贴它的文本。把工具保留为 **Tell from the files** (根据文件判断)，
   或者选择 money4band。
3. 检查表格。勾选你想要的服务，并填写所有标记为
   缺失的值。
4. 按下 **Save the ticked services** (保存勾选的服务)，然后在同一页面上
   把它们部署到你的工作节点。

## 会带过来的内容 { #what-comes-over }

字段名来自 money4band 的
[user-config 模板](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)，
以及它的
[生成器](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
写入的 `.env` 名称（`<APP>_<FLAG>`，例如 `REPOCKET_APIKEY`）。money4band 5.0 在它的
[应用目录](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported)中
沿用了相同的字段名。

| money4band 应用 | CashPilot 服务 | 会带过来的内容 |
|---|---|---|
| `earnapp` | EarnApp | 设备 id（`uuid`），这样你已关联的设备会继续赚钱 |
| `honeygain` | Honeygain | 邮箱、密码 |
| `iproyalpawns` | IPRoyal Pawns | 邮箱、密码 |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | 令牌 |
| `repocket` | Repocket | 邮箱、API 密钥 |
| `earnfm` | Earn.fm | API 密钥 |
| `proxyrack` | ProxyRack | API 密钥、设备 UUID |
| `proxylite` | ProxyLite | 用户 id |
| `bitping` | Bitping | 邮箱、密码 |
| `mystnode` | Mysterium | 开启；见下面关于 Mysterium 的说明 |

你在 money4band 中关闭的应用会显示为未勾选。关闭了、并且
只有模板占位符（`yourHONEYGAINMail`）和端口列表的应用
会被省略，所以一个未改动过的 `user-config.json` 会得到一张空表。

以下应用会被列出，但不会带过来：

| money4band 应用 | 原因 |
|---|---|
| `proxybase` | money4band 运行的是 ProxyBase 的旧客户端，使用用户 id。CashPilot 运行的是当前客户端，它需要来自 proxybase.org 的 Access Token。 |
| `urnetwork` | money4band 保存的是会话令牌。CashPilot 用你的邮箱和密码登录 URnetwork。 |
| `grass` | Grass 以浏览器扩展的形式运行。CashPilot 只跟踪它，使用来自 Grass 仪表板的访问令牌。 |
| `gradient`、`dawn`、`teneo`、`titan`、`spide`、`wipter` | CashPilot 跟踪这些服务，但没有可部署的容器。 |
| `packetshare`、`peer2profit`、`speedshare` | 已不再提供。 |

其他任何应用都会被列为**CashPilot has no such service** (CashPilot 没有这个服务)。

## 永远不会带过来的内容 { #what-never-comes-over }

- **设备名称。** CashPilot 以设备所运行的工作节点为每个设备命名，所以
  两个工作节点永远不会报告相同的名称。你的旧设备会在各提供商的仪表板中
  一直显示为离线，直到你在那里删除它们。
- **代理。** 在 **Fleet** (机群) 页面的 **Proxies** (代理) 部分逐个添加代理，然后让
  你的服务副本通过它运行；添加代理本身不会启动任何东西。
  保存导入也不会启动任何东西。代理副本需要先在工作节点上
  部署相同的服务，而部署该服务会让它在工作节点自己的
  连接上运行，所以绝不能使用该连接的服务应保持
  未勾选。见[代理副本](../proxies.md)。
- **Watchtower 和通知。** CashPilot 会更新它自己的容器。
- **money4band 的仪表板及其端口。**

## 收益跟踪 { #earnings-tracking }

对于 Honeygain、IPRoyal Pawns 和 Bitping，容器登录信息同时也是
账户登录信息，所以 CashPilot 也会填写它们的收益凭据，除非你
已经在 **Settings** (设置) 中设置过。对于其他每个服务，请在
**Settings > Earnings collection** (设置 > 收益采集) 中添加收益登录信息。

## Mysterium { #mysterium }

导入会开启 Mysterium，但 CashPilot 会启动一个带有新
身份的新节点。旧节点的密钥库和所有未结算的收益都留在
money4band 的 `.data/mysterium-node` 文件夹中
（[app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)）。请先结算它们，或者按照
[Mysterium 指南](../guides/mysterium.md)把身份迁移过来。

3.x 的 `.env` 无法看出你是否运行过 Mysterium：它的模板总是
列出仪表板端口。从 3.x 文件导入时不会导入 Mysterium，所以如果你运行过它，
请从目录中添加它。

## 安全 { #safety }

- 文件中的任何内容都不会被运行或展开，其中的任何地址都不会被访问。
- 文件只读取一次，不会保留。你保存的内容会加密存储，就像
  CashPilot 中的其他所有凭据一样。
- 机密在页面上只显示为**set** (已设置)。
- 已保存的导入会一直留在导入页面上，直到你按下 **Forget** (忘记)，所以你之后
  还可以把它们部署到更多工作节点。
