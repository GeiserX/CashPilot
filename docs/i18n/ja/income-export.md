---
source_hash: 38029ca1a5d6
---
# 税金用の収入エクスポート { #income-export-for-taxes }

**Payouts** (支払い)を開き、**Income for taxes** (税金用の収入)を見つけて、期間と通貨を選びます。**This year** (今年)は今日までで、**Last year** (昨年)は前の暦年全体です。日付を空のままにすると、今日までの利用できる履歴をエクスポートします。CashPilot は UTC の日付を使い、期間の両端を含めます。

CashPilot は収益の読み取り値を、記録してから 400 日後に削除します。CSV は残っている履歴を使うので、過去の年には、稼いだ収入や発生した収入の一部しか含まれないことがあります。

## 会計の基準を選ぶ { #choose-an-accounting-basis }

- **現金主義。** payout の行を使います。これはサービスが支払ったお金を記録します。CashPilot が含めるのは確認済みの支払いだけです。
- **発生主義。** earned と accrued の行を使います。earned の行は、サービスの条件に従って出金できるクレジットを示します。accrued の行は、プールが支払わない可能性もある未払いのプールのクレジットを示します。

同じ収入には 1 つの基準を使ってください。earned と accrued の行に payout の行を加えると、同じお金を 2 回数えることがあります。あなたの申告にどの基準が当てはまるかを確認してください。

## CSV の列 { #csv-columns }

| 列 | 意味 |
|---|---|
| date | 後の読み取り値または支払いの UTC の日。支払いでは、あなたが入力した日付か、CashPilot がそれを検出した日を使います。 |
| period_start | このサービスと出典の 1 つ前の読み取り値の UTC の日。支払いでは空です。読み取り値の間に間隔がある場合、金額はその間隔全体を対象にしています。 |
| kind | earned、accrued、payout のいずれか。 |
| service | CashPilot のサービス ID。 |
| coin | CashPilot が記録した通貨またはトークンのコード。 |
| amount | その通貨またはトークンでの金額。 |
| usd_rate | coin 1 単位あたりの米ドルの数。 |
| usd_value | 米ドルで評価した金額。 |
| local_currency | エクスポートで選んだ法定通貨。 |
| local_rate | 1 米ドルあたりの、選んだ通貨の単位数。 |
| local_value | 選んだ通貨で評価した金額。 |
| method | 記録されている場合の支払い方法。 |

評価額が空なのは、レートが手に入らなかったことを意味します。元の通貨での金額は残っています。CashPilot は、収益の読み取り値に含まれる Grass ポイントのような内部ポイントを飛ばします。出典ごとの最初の読み取り値が期首残高になります。それ以降の行は増加分を記録するので、CSV は選んだ期間の最も古い読み取り値より後から始まることがあります。

複数の出典が同じアカウントを読み取る場合、CSV がその収入を 2 回以上数えることがあります。

USD のレートは、後の読み取り値か支払いの記録から取ります。CashPilot が読み取り値の価格を後から補うときは、その日の 00:00 UTC の CoinGecko の価格を使います。USD を選んだ通貨に換算するには、その行の日付以前で最も新しい ECB の参照レートを使います。これで週末、祝日、ECB がまだレートを公表していない日にも対応できます。[Frankfurter の日次レート](https://frankfurter.dev/v1/)

Frankfurter がエクスポート用に提供している通貨は次のとおりです。[対応通貨](https://api.frankfurter.dev/v1/currencies)

- AUD、BRL、CAD、CHF、CNY、CZK、DKK、EUR、GBP、HKD、HUF、IDR、ILS、INR、ISK。
- JPY、KRW、MXN、MYR、NOK、NZD、PHP、PLN、RON、SEK、SGD、THB、TRY、USD、ZAR。

あなたの通貨がこの一覧にない場合や、Frankfurter が使えない場合は、USD を選んでください。

## ほかのツールにインポートする { #import-into-another-tool }

インポートする前に、CSV をそのツールの形式に変換してください。まず、会計の基準に合った行を選びます。ツールがすでに同期しているウォレットの payout の行は飛ばしてください。

### rotki { #rotki }

次のヘッダーで Generic Events を使います。

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Type を Income に、Location を external に設定します。rotki は、それぞれの種類がイベントに当てはまる場合、Deposit、Withdrawal、Loss、Spend、Staking も受け付けます。coin を Currency に、amount を Amount に、service を Description に対応させます。rotki のアセット識別子が coin のコードと違う場合は、そちらを使ってください。date をミリ秒単位の UTC の Unix タイムスタンプに変換します。2 つの手数料の欄は空のままにします。[rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Universal テンプレートの必須の列を使います。

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Date は UTC で YYYY-MM-DD HH:mm:ss の形式にします。Received Amount には amount を、Received Currency には coin を設定します。2 つの Sent の欄は空のままにします。値がわかっている場合は、local_value と local_currency を任意の Net Worth Amount と Net Worth Currency に対応させます。必要に応じて、Tag の列に mining または reward を使います。Description と TxHash は任意です。[Koinly Universal テンプレート](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

まだ Koinly のアカウントがない場合は、こちらから登録できます:
https://koinly.io/?via=FFF185D5
これは紹介リンクで、あなたに費用はかかりません。

### CoinTracking { #cointracking }

収入の行を CoinTracking の通常の CSV 形式に変換します。Custom Importer は両側に取引の欄を必要としますが、収入の行には購入側しかありません。[CoinTracking Custom Importer の要件](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Type は場合に応じて Income または Mining に設定します。amount を Buy Amount に、coin を Buy Currency に、service を Comment に対応させます。Sell の欄は空のままにします。Date は DD.MM.YYYY HH:MM:SS の形式にします。エクスポートには UTC の日しかないので、時刻には 00:00:00 を使ってください。種類のラベルは、あなたのアカウントの言語のものを使います。[CoinTracking の通常の CSV 形式](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

まだ CoinTracking のアカウントがない場合は、この登録リンクですべての有料プランが 10% 割引になります:
https://cointracking.info?ref=G962413
これは紹介リンクです。CoinTracking は、あなたが支払う額の 20% を CashPilot プロジェクトに支払います。あなたの支払う額が増えることはありません。
