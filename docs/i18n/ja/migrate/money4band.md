---
source_hash: 374e39e6eac9
---
# money4band からの移行 { #moving-from-money4band }

CashPilot は money4band の設定を読み込み、サービスのログイン情報を引き継げるので、
もう一度入力する必要はありません。CashPilot が保存する前に、すべてをあなたが確認します。

## 始める前に { #before-you-start }

CashPilot のオーナーアカウントと、少なくとも 1 つの CashPilot ワーカーが必要です。ワーカーは、
今 money4band が動いているマシンでも、別のマシンでもかまいません。

あるマシンで同じサービスを CashPilot からデプロイする前に、そのマシンの money4band を止めてください。
1 つの回線の後ろにある 2 つのコピーは 1 つとして稼ぐだけで、同じ EarnApp や
ProxyRack のデバイス ID を 2 つ同時に動かしてはいけません。money4band のメニューの **Stop apps stack** を使うか
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))、
そのフォルダーで `docker compose down` を実行してください。追加のプロキシの
インスタンスを設定していた場合は、それぞれも止めてください。

## 使うファイル { #which-file-to-use }

money4band のフォルダーにある `config/user-config.json` を使ってください。money4band は
**Setup Apps** を実行したときにこのファイルを書き出し、あなたが入力したものがそのまま入っています。
その隣にある `.env` はこのファイルから生成されたもので、これも使えます。money4band 3.x で手で編集した
`.env` も同じく使えます。どちらもあなたのディスクにだけ残ります。money4band の
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
にこれらが記載されています。

JSON ファイルを優先してください。`.env` では、Docker Compose が引用符で囲まれていない値の `$` を展開するので、
`$` を含むパスワードはファイルに見えているものとは違います。CashPilot は
推測しません。その値を入力し直すよう求めます。

## インポートの手順 { #how-to-import }

1. **Settings** (設定)を開き、次に **Import from another tool** (ほかのツールからインポート)を開きます(または `/import` に移動します)。
2. `user-config.json` を追加するか、その内容を貼り付けます。ツールは **Tell from the files** (ファイルから判断)のままにするか、
   money4band を選びます。
3. 表を確認します。必要なサービスにチェックを入れ、不足と表示された値を入力します。
4. **Save the ticked services** (チェックしたサービスを保存)を押し、同じページからそれらをワーカーに
   デプロイします。

## 引き継がれるもの { #what-comes-over }

フィールド名は、money4band の
[user-config テンプレート](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
と、その
[ジェネレーター](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
が書き出す `.env` の名前(`<APP>_<FLAG>`、たとえば `REPOCKET_APIKEY`)から来ています。

| money4band のアプリ | CashPilot のサービス | 引き継がれるもの |
|---|---|---|
| `earnapp` | EarnApp | デバイス ID(`uuid`)。リンク済みのデバイスが稼ぎ続けます |
| `honeygain` | Honeygain | メールアドレス、パスワード |
| `iproyalpawns` | IPRoyal Pawns | メールアドレス、パスワード |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | トークン |
| `repocket` | Repocket | メールアドレス、API キー |
| `earnfm` | Earn.fm | API キー |
| `proxyrack` | ProxyRack | API キー、デバイスの UUID |
| `proxylite` | ProxyLite | ユーザー ID |
| `bitping` | Bitping | メールアドレス、パスワード |
| `mystnode` | Mysterium | オンになります。下の Mysterium の注記を参照してください |

money4band でオフにしたアプリは、チェックなしで表示されます。オフで、テンプレートの
プレースホルダー(`yourHONEYGAINMail`)とポートの一覧しか入っていないアプリは除外されるので、
手を付けていない `user-config.json` では表は空になります。

次のアプリは一覧に表示されますが、引き継がれません。

| money4band のアプリ | 理由 |
|---|---|
| `proxybase` | money4band は ProxyBase の古いクライアントをユーザー ID で動かします。CashPilot が動かすのは現在のクライアントで、proxybase.org の Access Token が必要です。 |
| `urnetwork` | money4band はセッショントークンを保持します。CashPilot は URnetwork にメールアドレスとパスワードでサインインします。 |
| `grass` | Grass はブラウザー拡張として動きます。CashPilot は Grass のダッシュボードのアクセストークンを使って、追跡するだけです。 |
| `gradient`、`dawn`、`teneo`、`titan`、`spide`、`wipter` | CashPilot はこれらを追跡しますが、デプロイするコンテナはありません。 |
| `packetshare`、`peer2profit`、`speedshare` | 提供が終了しています。 |

それ以外のアプリは **CashPilot has no such service** (CashPilot にそのサービスはありません)と表示されます。

## 引き継がれないもの { #what-never-comes-over }

- **デバイス名。** CashPilot は各デバイスに、それが動くワーカーの名前を付けるので、
  2 つのワーカーが同じ名前を報告することはありません。古いデバイスは、各プロバイダーのダッシュボードで削除するまで、
  オフラインとして表示されたままです。
- **プロキシ。** それぞれを **Fleet** (フリート)ページの **Proxies** (プロキシ)セクションで追加し、その後サービスのコピーをそのプロキシ経由で動かします。
  プロキシを追加しただけでは何も起動しません。
  インポートを保存しても何も起動しません。プロキシ経由のコピーには、まず同じサービスがワーカーに
  デプロイされている必要があり、デプロイするとワーカー自身の回線で動きます。そのため、その回線を決して
  使ってはいけないサービスはチェックしないままにしてください。[プロキシ経由のコピー](../proxies.md)を参照してください。
- **Watchtower と通知。** CashPilot は自分のコンテナを自分で更新します。
- **money4band のダッシュボードとそのポート。**

## 収益の追跡 { #earnings-tracking }

Honeygain、IPRoyal Pawns、Bitping では、コンテナのログイン情報がアカウントのログイン情報でもあるので、
すでに **Settings** (設定)で設定していない限り、CashPilot が収益用の認証情報も入力します。ほかのすべてのサービスでは、
**Settings** (設定) > **Earnings collection** (収益の収集)で収益用のログイン情報を追加してください。

## Mysterium { #mysterium }

インポートすると Mysterium はオンになりますが、CashPilot は新しい識別情報で新しいノードを起動します。
古いノードのキーストアと未精算の収益は、money4band の `.data/mysterium-node` フォルダーに残ります
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json))。先にそれを精算するか、
[Mysterium のガイド](../guides/mysterium.md)に従って識別情報を引き継いでください。

3.x の `.env` からは、Mysterium を動かしていたかどうかがわかりません。そのテンプレートは常に
ダッシュボードのポートを記載しているからです。3.x のファイルからは Mysterium はインポートされないので、
動かしていた場合はカタログから追加してください。

## 安全性 { #safety }

- ファイルの中身が実行されたり展開されたりすることはなく、中のアドレスが取得されることもありません。
- ファイルは 1 回読み込まれるだけで、保持されません。保存したものは、CashPilot のほかの
  すべての認証情報と同じく、暗号化して保存されます。
- シークレットはページ上で **set** (設定済み)としか表示されません。
- 保存したインポートは、**Forget** (削除)を押すまでインポートのページに残るので、後でさらに
  ほかのワーカーにデプロイできます。
