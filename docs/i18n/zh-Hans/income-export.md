---
source_hash: 38029ca1a5d6
---
# 用于报税的收入导出 { #income-export-for-taxes }

打开 **Payouts** (付款)，找到 **Income for taxes** (用于报税的收入)，然后选择日期范围和货币。**This year** (今年) 截至今天，**Last year** (去年) 涵盖上一个日历年。把日期留空，即可导出截至今天的全部可用历史。CashPilot 使用 UTC 日期，并包含范围的两端。

CashPilot 会在记录收益读数 400 天后删除它们。CSV 使用剩下的历史，所以过去某一年可能只包含其已赚取或应计收入的一部分。

## 选择会计基础 { #choose-an-accounting-basis }

- **收付实现制。** 使用 payout 行。它们记录服务已经付出的钱。CashPilot 只包含已确认的付款。
- **权责发生制。** 使用 earned 和 accrued 行。earned 行显示你可以按服务条款提取的额度。accrued 行显示矿池尚未支付、而且可能永远不会支付的额度。

对同一笔收入只使用一种基础。把 payout 行加到 earned 和 accrued 行上，可能会把同一笔钱计算两次。请确认你的申报适用哪种基础。

## CSV 列 { #csv-columns }

| 列 | 含义 |
|---|---|
| date | 较晚那条读数或付款的 UTC 日期。付款使用你输入的日期，或 CashPilot 检测到它的那一天。 |
| period_start | 该服务和来源上一条读数的 UTC 日期。付款行留空。两条读数之间有间隔，表示该金额涵盖整个区间。 |
| kind | earned、accrued 或 payout。 |
| service | CashPilot 服务 ID。 |
| coin | CashPilot 记录的货币或代币代码。 |
| amount | 以该货币或代币计的金额。 |
| usd_rate | 每单位 coin 对应的美元数。 |
| usd_value | 以美元计价的金额。 |
| local_currency | 你为导出选择的法币。 |
| local_rate | 每美元对应的所选货币单位数。 |
| local_value | 以你所选货币计价的金额。 |
| method | 付款方式（如有记录）。 |

估值为空表示当时没有汇率。原生金额仍然存在。CashPilot 会跳过收益读数中的内部积分，例如 Grass 积分。每个来源的第一条读数提供期初余额。后面的行记录增加额，所以 CSV 可能从所选范围内最早的读数之后才开始。

如果有多个来源读取同一个账户，CSV 可能会把这部分收入计算不止一次。

USD 汇率来自较晚那条读数或付款记录。当 CashPilot 为某条读数补填价格时，它使用 CoinGecko 在当天 00:00 UTC 的价格。CashPilot 使用该行日期当天或之前最近一次的欧洲央行（ECB）参考汇率，把 USD 换算为你选择的货币。这涵盖周末、节假日以及 ECB 尚未公布汇率的日子。[Frankfurter 每日汇率](https://frankfurter.dev/v1/)

Frankfurter 为导出列出了以下货币。[支持的货币](https://api.frankfurter.dev/v1/currencies)

- AUD、BRL、CAD、CHF、CNY、CZK、DKK、EUR、GBP、HKD、HUF、IDR、ILS、INR 和 ISK。
- JPY、KRW、MXN、MYR、NOK、NZD、PHP、PLN、RON、SEK、SGD、THB、TRY、USD 和 ZAR。

如果你的货币不在该列表中，或者 Frankfurter 不可用，请选择 USD。

## 导入到其他工具 { #import-into-another-tool }

导入之前，请把 CSV 转换为该工具的格式。先选出适用于你的会计基础的行。对于工具已经在同步的钱包，跳过 payout 行。

### rotki { #rotki }

使用 Generic Events，并采用以下表头。

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

把 Type 设为 Income，把 Location 设为 external。当 Deposit、Withdrawal、Loss、Spend 和 Staking 这些类型能描述某个事件时，rotki 也接受它们。把 coin 映射到 Currency，amount 映射到 Amount，service 映射到 Description。如果 rotki 的资产标识符与 coin 代码不同，请使用 rotki 的资产标识符。把 date 转换为以毫秒计的 UTC Unix 时间戳。两个手续费字段都留空。[rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

使用 Universal 模板的必填列。

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

把 Date 格式化为 UTC 的 YYYY-MM-DD HH:mm:ss。用 amount 填 Received Amount，用 coin 填 Received Currency。两个 Sent 字段都留空。对于已知的值，把 local_value 和 local_currency 映射到可选的 Net Worth Amount 和 Net Worth Currency。在合适的情况下，用 Tag 列标注 mining 或 reward。Description 和 TxHash 是可选的。[Koinly Universal 模板](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

还没有 Koinly 账户？你可以在这里注册：https://koinly.io/?via=FFF185D5 。这是一个推荐链接，不会让你多花任何钱。

### CoinTracking { #cointracking }

把收入行转换为 CoinTracking 的常规 CSV 格式。Custom Importer 要求交易两边都有字段，而收入行只有买入一边。[CoinTracking Custom Importer 要求](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

根据情况把 Type 设为 Income 或 Mining。把 amount 映射到 Buy Amount，coin 映射到 Buy Currency，service 映射到 Comment。Sell 字段留空。把 Date 格式化为 DD.MM.YYYY HH:MM:SS。导出提供的是 UTC 日期，所以时间使用 00:00:00。请使用与你账户语言对应的类型标签。[CoinTracking 常规 CSV 格式](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

还没有 CoinTracking 账户？这个注册链接让你在每个付费方案上享受 10% 折扣：https://cointracking.info?ref=G962413 。这是一个推荐链接。CoinTracking 会把你所付金额的 20% 支付给 CashPilot 项目，而你不需要多付钱。
