---
source_hash: 7f8476aeb8b6
---
# CashFactory からの移行 { #moving-from-cashfactory }

CashPilot は CashFactory の `.env` を読み込み、サービスのログイン情報を引き継げるので、
もう一度入力する必要はありません。CashPilot が保存する前に、すべてをあなたが確認します。

## 始める前に { #before-you-start }

CashPilot のオーナーアカウントと、少なくとも 1 つの CashPilot ワーカーが必要です。

あるマシンで同じサービスを CashPilot からデプロイする前に、そのマシンの CashFactory を止めてください。
1 つの回線の後ろにある 2 つのコピーは 1 つとして稼ぐだけで、同じ EarnApp の
デバイス ID を 2 つ同時に動かしてはいけません。CashFactory のフォルダーで `docker compose down` を実行してください。
その
[compose ファイル](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
は、Docker ソケットをマウントするコンテナも 3 つ起動します。Portainer(31 行目)
と 2 つの Watchtower のコンテナ(141 行目と 264 行目)です。これらもなくなっていることを確認してください。`docker ps` に
どれも表示されないはずです。

## 使うファイル { #which-file-to-use }

CashFactory のフォルダーにある `.env` ファイルを使ってください。
[サンプル](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env)
をもとに入力したものです。

Docker Compose はこのファイルを読み、一重引用符で囲まれていない値の `$` を展開します。
そうした値はファイルに見えているものとは違うので、CashPilot は推測せず、
入力し直すよう求めます。

## インポートの手順 { #how-to-import }

1. **Settings** (設定)を開き、次に **Import from another tool** (ほかのツールからインポート)を開きます(または `/import` に移動します)。
2. `.env` ファイルを追加するか、その内容を貼り付けます。ツールは **Tell from the files** (ファイルから判断)のままにするか、
   CashFactory を選びます。
3. 表を確認します。必要なサービスにチェックを入れ、不足と表示された値を入力します。
4. **Save the ticked services** (チェックしたサービスを保存)を押し、同じページからそれらをワーカーに
   デプロイします。

## 引き継がれるもの { #what-comes-over }

| CashFactory のアプリ | 読み込むキー | CashPilot のサービス | 引き継がれるもの |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | デバイス ID。リンク済みのデバイスが稼ぎ続けます |
| `honeygain` | `HONEYGAIN_EMAIL`、`HONEYGAIN_PASSWD` | Honeygain | メールアドレス、パスワード |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`、`IPROYALPAWNS_PASSWD` | IPRoyal Pawns | メールアドレス、パスワード |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | トークン |
| `repocket` | `RP_EMAIL`、`RP_API_KEY` | Repocket | メールアドレス、API キー |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | ユーザー ID |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | デバイスの UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API キー |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | なし: 提供が終了しています |

サンプルのプレースホルダー(`<email>`、`sdk-node-<md5sum>`)のままの値は
未設定として扱われ、プレースホルダーしかないサービスは表から除外されます。

## 引き継がれないもの { #what-never-comes-over }

- **`DEVICE_NAME`。** CashPilot は各デバイスに、それが動くワーカーの名前を付けるので、
  2 つのワーカーが同じ名前を報告することはありません。古いデバイスは、各プロバイダーのダッシュボードで削除するまで、
  オフラインとして表示されたままです。
- **Bitping。** CashFactory は Bitping のログイン情報を `.env` ではなく Docker のボリュームに保持するので、
  インポートで読むものがなく、Bitping の行は表示されません。ログイン情報は
  Bitping のデプロイフォームで入力してください。
- **Portainer と Watchtower。** CashPilot は自分のコンテナを自分で管理・更新します。

## 収益の追跡 { #earnings-tracking }

Honeygain と IPRoyal Pawns では、コンテナのログイン情報がアカウントのログイン情報でもあるので、
すでに **Settings** (設定)で設定していない限り、CashPilot が収益用の認証情報も入力します。ほかのすべてのサービスでは、
**Settings** (設定) > **Earnings collection** (収益の収集)で収益用のログイン情報を追加してください。

## 安全性 { #safety }

- ファイルの中身が実行されたり展開されたりすることはなく、中のアドレスが取得されることもありません。
- ファイルは 1 回読み込まれるだけで、保持されません。保存したものは、CashPilot のほかの
  すべての認証情報と同じく、暗号化して保存されます。
- シークレットはページ上で **set** (設定済み)としか表示されません。
- 保存したインポートは、**Forget** (削除)を押すまでインポートのページに残るので、後でさらに
  ほかのワーカーにデプロイできます。
