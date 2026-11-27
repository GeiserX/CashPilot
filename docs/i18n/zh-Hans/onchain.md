---
source_hash: d88e40f8d9a6
---
# 链上付款余额 { #on-chain-payout-balances }

打开 **Payouts** (付款) 即可查看某个公开付款地址上的余额。Bitcoin 使用
[mempool.space](https://mempool.space/docs/api/rest)，Kaspa 使用
[api.kaspa.org](https://api.kaspa.org/docs)。Ethereum、Polygon 和 Solana 使用
公共 RPC 节点。CashPilot 无需密钥即可读取这些地址。

| 你看到的内容 | 含义 |
|---|---|
| 一个金额 | 区块浏览器报告了余额。报告为零时显示为零。把鼠标悬停在金额上可以查看来源。 |
| **Pending** (待确认) | 在 Bitcoin 上，区块浏览器看到了一笔未确认的变动。加号表示资金正在转入。减号表示资金正在被花出。已确认的金额单独显示。 |
| **Could not check** (无法检查) | 区块浏览器没有响应，或者发送了 CashPilot 无法读取的数据。 |
| **Address not valid** (地址无效) | 地址未通过格式检查。CashPilot 跳过了这次请求。 |
| **Private chain** (隐私链) | 读取 Monero 余额需要你的私有查看密钥（view key）。请在你的钱包中查看余额。CashPilot 从不向你索要这个密钥。 |
| 一条短横线 | 这一行没有地址或读取器，或者查询已关闭。当某个设置关闭了查询时，把鼠标悬停在短横线上可以看到是哪一个设置。 |

Kaspa 的公共端点只报告一个余额。它不单独提供待确认
金额。

链上列显示的是该地址当前的余额。它可能包含
来自其他来源的转账。矿池的未付余额显示的是矿池
仍为你保留的金额。通过 Lightning 进行的 OCEAN 付款不会出现在
链上余额中。余额也无法告诉你哪些转账来自
你的矿池。

## 选择查询发往何处 { #choose-where-the-lookup-goes }

每次查询都会把你的公开付款地址和 UI 服务器的 IP 共享给
区块浏览器。区块浏览器可以把你从同一个 IP 查询的地址关联起来。

如果你运行自己的节点，请在 UI 容器的环境中设置基础 URL。
不设置该变量则使用默认值。把它设为空值则关闭
该链的查询。

例如，UI 服务的 Compose 覆盖文件可以包含：

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

配置 Bitcoin 或 Kaspa 时，请使用 Esplora 或 Kaspa API 的基础 URL。
Bitcoin 端点还会为 Bitcoin 矿池的
[预期收益](fleet.md#running-costs)提供全网难度和区块奖励。这项读取需要
mempool 后端（它的 `/v1/mining` API）；普通的 Esplora 服务器只响应
余额查询，此时该矿池的行不显示预期金额。
对于 Ethereum、Polygon 和 Solana，请把相应的变量
`CASHPILOT_ONCHAIN_URL_ETHEREUM`、`CASHPILOT_ONCHAIN_URL_POLYGON` 或
`CASHPILOT_ONCHAIN_URL_SOLANA` 设为某个节点的 RPC URL。请使用 HTTP 或 HTTPS URL，
且不带凭据、查询字符串或片段。用新的环境重建 UI 容器
即可应用更改。
