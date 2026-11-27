---
source_hash: d88e40f8d9a6
---
# オンチェーンの支払い残高 { #on-chain-payout-balances }

**Payouts** (支払い)を開くと、公開された支払い先アドレスの残高が見られます。Bitcoin は
[mempool.space](https://mempool.space/docs/api/rest)、Kaspa は
[api.kaspa.org](https://api.kaspa.org/docs) を使います。Ethereum、Polygon、Solana は
公開の RPC ノードを使います。CashPilot はこれらのアドレスをキーなしで読み取れます。

| 表示 | 意味 |
|---|---|
| 金額 | エクスプローラーが残高を報告しました。報告された 0 は 0 と表示されます。金額にカーソルを合わせると出典が表示されます。 |
| **Pending** (保留中) | Bitcoin で、エクスプローラーが未承認の変動を検出しています。プラスは入金中、マイナスは送金中を意味します。承認済みの金額は別に表示されます。 |
| **Could not check** (確認できません) | エクスプローラーが応答しなかったか、CashPilot が読めないデータを返しました。 |
| **Address not valid** (無効なアドレス) | アドレスが形式のチェックに通りませんでした。CashPilot はリクエストを送りませんでした。 |
| **Private chain** (プライベートチェーン) | Monero の残高を読むには、あなたの秘密の閲覧鍵が必要です。残高はウォレットで確認してください。CashPilot がこの鍵を求めることはありません。 |
| ダッシュ | この行にはアドレスも読み取り手段もないか、照会がオフになっています。設定によって照会がオフになっている場合は、ダッシュにカーソルを合わせるとどの設定かが表示されます。 |

Kaspa の公開エンドポイントが報告する残高は 1 つです。保留中の金額は別に
提供されません。

オンチェーンの列には、そのアドレスの今の残高が表示されます。ほかの送金元からの
送金が含まれることもあります。プールの未払い残高は、プールがまだあなたのために保持している額を示します。
Lightning 経由の OCEAN の支払いは、オンチェーンの残高には表示されません。また、残高からは、どの送金が
あなたのプールから来たものかはわかりません。

## 照会先を選ぶ { #choose-where-the-lookup-goes }

照会のたびに、あなたの公開された支払い先アドレスと UI サーバーの IP がエクスプローラーに
共有されます。エクスプローラーは、同じ IP から確認したアドレス同士を結び付けられます。

自分のノードを動かしている場合は、UI コンテナの環境にベース URL を設定してください。
既定のものを使うには、変数を設定しないままにします。そのチェーンの照会をオフにするには、空の値を設定します。

たとえば、UI サービスの Compose のオーバーライドには次のように書けます。

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Bitcoin または Kaspa を設定するときは、Esplora または Kaspa API のベース URL を使ってください。
Bitcoin のエンドポイントは、Bitcoin プールの[見込み収益](fleet.md#running-costs)に使う
ネットワークの難易度とブロック報酬も提供します。この読み取りには mempool のバックエンド
(その `/v1/mining` API)が必要です。素の Esplora サーバーが応答するのは残高の照会だけで、
その場合プールの行には見込み額が表示されません。
Ethereum、Polygon、Solana では、対応する変数
`CASHPILOT_ONCHAIN_URL_ETHEREUM`、`CASHPILOT_ONCHAIN_URL_POLYGON`、
`CASHPILOT_ONCHAIN_URL_SOLANA` にノードの RPC URL を設定します。認証情報、クエリ文字列、
フラグメントを含まない HTTP または HTTPS の URL を使ってください。変更を適用するには、
新しい環境で UI コンテナを作り直します。
