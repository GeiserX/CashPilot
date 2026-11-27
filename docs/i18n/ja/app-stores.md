---
source_hash: e99e2c0c80bb
---
# アプリストア { #app-stores }

CashPilot は、いくつかのホームサーバー向けシステムのアプリストアからインストールできます。
どのリスティングも、ダッシュボード(`drumsergio/cashpilot`)と、サービスのコンテナを起動・停止する
ワーカー(`drumsergio/cashpilot-worker`)をインストールします。このリポジトリにある CasaOS と
Runtipi のパッケージだけは、`docker-compose.yml` の Docker ソケットプロキシもインストールするので、
そのワーカーが生の Docker ソケットを持つことはありません。Unraid のテンプレート、TrueNAS のアプリ、
CasaOS アプリストアへの未マージのプルリクエストにあるパッケージは、今もワーカーに Docker
ソケットを直接マウントします。

どのストアを使っても、ダッシュボードは LAN か VPN の中に置いてください。ダッシュボードは
ワーカーに命令でき、ワーカーはホストの Docker を操作します。ワーカー自身がソケットを持つ場合、
それはホストの root 権限と同じです。

## 現在掲載中 { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Apps タブで **CashPilot** を検索し、2 つのテンプレートをどちらもインストールします。
`cashpilot`(ダッシュボード)と `cashpilot-worker` です。両方に同じ
`CASHPILOT_API_KEY` を設定してください。

テンプレートの提供元は https://github.com/GeiserX/docker-templates で、
`latest` イメージタグに従います。そのため Community Applications のユーザーは、テンプレートを変えなくても
リリースごとに更新を受け取れます。

### TrueNAS SCALE { #truenas-scale }

CashPilot は TrueNAS の **community** トレインにあります。Apps を開き、次に Discover Apps を開いて、
**CashPilot** を検索してください。

アプリの定義は
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot
で管理されており、正確なイメージダイジェストを固定しています。新しいリリースへの更新は TrueNAS 自身のボットが行うので、
最新の CashPilot から数リリース遅れていることがあります。

## レビュー待ち { #waiting-for-review }

### CasaOS { #casaos }

CasaOS アプリストアへのプルリクエストが提出されています。
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

マージされるまでは、カスタムアプリとしてインストールしてください。CasaOS で App Store、
次に Custom Install、次に Import を選び、次のファイルの内容を貼り付けます。
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

CasaOS 0.4.5 以降が必要です。このリリースから、アプリマネージャーが Docker Compose 2.23 をもとに
作られており、ファイルからソケットプロキシのポリシーを読み込めます。
それより古いものはポリシーを捨ててしまい、ワーカーが Docker に接続できなくなります。

このファイルは正確なリリースを固定しています。インポートする前に、2 つのイメージタグ
(`drumsergio/cashpilot` と `drumsergio/cashpilot-worker`)を、次のページにある最新の
リリースに設定してください。
https://github.com/GeiserX/CashPilot/releases
ファイル内のプロキシのポリシーは `main` に従います。ワーカーの状態ページにポリシーが
古いと表示されたら、ファイルをもう一度インポートしてください。

## 準備済み、未提出 { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

パッケージは
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
に用意してありますが、まだ Runtipi のアプリストアには入っていません。今使うには、Runtipi のドキュメントに従って、
自分で管理するカスタムアプリストアに追加してください。
https://runtipi.io/docs/guides/create-your-own-app-store

## 提供していないもの { #not-offered }

Umbrel には別のワーカー設計が必要です。Umbrel のアプリはホストのソケットではなく、
Docker-in-Docker のコンテナを通じて Docker に接続するからです。これはまだ
テストしていないので、Umbrel のパッケージはまだありません。

ほかのシステムでは、[はじめに](getting-started.md)のとおり、リポジトリの `docker-compose.yml` を使ってください。
