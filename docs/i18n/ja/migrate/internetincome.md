---
source_hash: ca9dd25d45ca
---
# InternetIncome からの移行 { #moving-from-internetincome }

CashPilot は InternetIncome の `properties.conf` と、EarnApp と ProxyRack のデバイス ID を
保存しているファイルを読み込み、それらを引き継げます。CashPilot が保存する前に、
すべてをあなたが確認します。

## 始める前に { #before-you-start }

CashPilot のオーナーアカウントと、少なくとも 1 つの CashPilot ワーカーが必要です。

あるマシンで同じサービスを CashPilot からデプロイする前に、そのマシンの InternetIncome を止めてください。
1 つの回線の後ろにある 2 つのコピーは 1 つとして稼ぐだけで、同じデバイス ID を
2 つ同時に動かしてはいけません。InternetIncome のフォルダーで次を実行します。

```bash
sudo bash internetIncome.sh --delete
```

`--delete` はコンテナを削除し、`earnapp.txt`、`proxyrack.txt`、
Mysterium のデータフォルダーは残します。`--deleteBackup` はそれらも削除するので
([internetIncome.sh の 61〜64 行目](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
と [1562 行目](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562))、
先にインポートしてください。

## 使うファイル { #which-files-to-use }

InternetIncome のフォルダーから:

- `properties.conf`: あなたの設定。
- `earnapp.txt`: EarnApp を動かしていた場合。各行にデバイスのリンクが入っています
  ([1250〜1261 行目](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261))。
- `proxyrack.txt`: ProxyRack を動かしていた場合。1 行に 1 つのデバイスの UUID
  ([817〜827 行目](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827))。

CashPilot は各ファイルの最初のデバイスを使います。メインのコンテナが使っていたもので、
あなたがアカウントにリンクしたものです。ほかの行はプロキシ経由のコピーのもので、
ページには除外した数が表示されます。

InternetIncome はすべての値をシェルに通します
([1375 行目](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375))。
一重引用符で囲まれた値は、
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
のコメントが勧めるとおり、書かれたとおりに扱われます。一重引用符の外にあって、`$`、バッククォート、空白、
またはシェルが変えてしまうほかの文字を含む値は、ファイルに見えているものとは違います。そのため
CashPilot は、シェルを実行して確かめるのではなく、入力し直すよう求めます。

## インポートの手順 { #how-to-import }

1. **Settings** (設定)を開き、次に **Import from another tool** (ほかのツールからインポート)を開きます(または `/import` に移動します)。
2. `properties.conf` を追加し、あれば `earnapp.txt` と `proxyrack.txt` も追加します。
   ツールは **Tell from the files** (ファイルから判断)のままにするか、InternetIncome を選びます。
3. 表を確認します。必要なサービスにチェックを入れ、不足と表示された値を入力します。
   Repocket にはアカウントのメールアドレスが必要です。InternetIncome はこれを尋ねませんでした。
4. **Save the ticked services** (チェックしたサービスを保存)を押し、同じページからそれらをワーカーに
   デプロイします。

## 引き継がれるもの { #what-comes-over }

| InternetIncome のアプリ | 読み込むキー | CashPilot のサービス | 引き継がれるもの |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API キー(メールアドレスを追加してください) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | トークン |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`、`proxyrack.txt` | ProxyRack | API キー、デバイスの UUID |
| `iproyals` | `IPROYALS_EMAIL`、`IPROYALS_PASSWORD` | IPRoyal Pawns | メールアドレス、パスワード |
| `honeygain` | `HONEYGAIN_EMAIL`、`HONEYGAIN_PASSWORD` | Honeygain | メールアドレス、パスワード |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | ユーザー ID |
| `earnfm` | `EARN_FM_API` | Earn.fm | API キー |
| `earnapp` | `EARNAPP=true`、`earnapp.txt` | EarnApp | デバイス ID |
| `bitping` | `BITPING_EMAIL`、`BITPING_PASSWORD` | Bitping | メールアドレス、パスワード |
| `mysterium` | `MYSTERIUM=true` | Mysterium | オンになります。下の Mysterium の注記を参照してください |

値が空なのはアプリがオフだったという意味で、そのアプリは表示されません。

次のアプリは一覧に表示されますが、引き継がれません。

| InternetIncome のアプリ | 理由 |
|---|---|
| `urnetwork` | InternetIncome はセッショントークンを使います。CashPilot は URnetwork にメールアドレスとパスワードでサインインします。 |
| `grass` | Grass はブラウザー拡張として動きます。CashPilot は Grass のダッシュボードのアクセストークンを使って、追跡するだけです。 |
| `titan`、`ebesucher`、`wipter` | CashPilot はこれらを追跡しますが、デプロイするコンテナはありません。 |
| `peer2profit` | 提供が終了しています。 |

CashPilot にないアプリ(antGain、Adnade など)の設定は、読み込まなかったものとして
名前で表示されます。

## 引き継がれないもの { #what-never-comes-over }

- **`DEVICE_NAME`。** CashPilot は各デバイスに、それが動くワーカーの名前を付けるので、
  2 つのワーカーが同じ名前を報告することはありません。古いデバイスは、各プロバイダーのダッシュボードで削除するまで、
  オフラインとして表示されたままです。
- **プロキシ**(`USE_PROXIES`、`proxies.txt`)。それぞれを **Fleet** (フリート)ページの **Proxies** (プロキシ)
  セクションで追加し、その後サービスのコピーをそのプロキシ経由で動かします。プロキシを
  追加しただけでは何も起動しません。`USE_PROXIES=true` では、InternetIncome はサービスをプロキシ経由でだけ動かしていました。
  インポートを保存しても何も起動しません。プロキシ経由のコピーには、まず同じサービスがワーカーに
  デプロイされている必要があり、デプロイするとワーカー自身の回線で動きます。そのため、その回線を決して
  使ってはいけないサービスはチェックしないままにしてください。[プロキシ経由の
  コピー](../proxies.md)を参照してください。
- **`BROWSER_USERNAME` と `BROWSER_PASSWORD`**。InternetIncome 自身のブラウザーの
  ログイン情報です。

## 収益の追跡 { #earnings-tracking }

Honeygain、IPRoyal Pawns、Bitping では、コンテナのログイン情報がアカウントのログイン情報でもあるので、
すでに **Settings** (設定)で設定していない限り、CashPilot が収益用の認証情報も入力します。ほかのすべてのサービスでは、
**Settings** (設定) > **Earnings collection** (収益の収集)で収益用のログイン情報を追加してください。

## Mysterium { #mysterium }

インポートすると Mysterium はオンになりますが、CashPilot は新しい識別情報で新しいノードを起動します。
古いノードのキーストアと未精算の収益は、InternetIncome の `mysterium-data` フォルダーに残ります。
先にそれを精算するか、[Mysterium のガイド](../guides/mysterium.md)に従って識別情報を引き継いでください。

## 安全性 { #safety }

- ファイルの中身が実行されたり展開されたりすることはなく、中のアドレスが取得されることもありません。
- ファイルは 1 回読み込まれるだけで、保持されません。保存したものは、CashPilot のほかの
  すべての認証情報と同じく、暗号化して保存されます。
- シークレットはページ上で **set** (設定済み)としか表示されません。
- 保存したインポートは、**Forget** (削除)を押すまでインポートのページに残るので、後でさらに
  ほかのワーカーにデプロイできます。
