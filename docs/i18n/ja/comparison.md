---
source_hash: b48a8fc19aa4
---
# CashPilot とほかのツールの比較 { #how-cashpilot-compares }

このページでは、複数の不労所得アプリを Docker で動かすほかのオープンなプロジェクトと CashPilot を比較します。どのプロジェクトも 2026-11-04 に確認し、CashPilot は 2026-11-28 にもう一度確認しました。ほかのプロジェクトについての各セルは、その根拠となるファイルに固定のコミットでリンクしているので、自分で確かめられます。セルが間違っているか古くなっている場合は、[issue を作成](https://github.com/GeiserX/CashPilot/issues)してください。

## 比較したプロジェクト { #projects-compared }

| プロジェクト | 確認したもの | 2026-11-04 時点のスター数 | ライセンス |
|---|---|---|---|
| [money4band][m4b-tree] | リリース 5.0.0、タグのコミット `af9d903`(2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `65e900d` 時点の `main`(2026-10-20)と、その 3.0.0-beta.9 バイナリについての README の記述 | 238 | プロプライエタリ、[独自ライセンス v1.4][igm-license] |
| [InternetIncome][ii-tree] | `db9338a` 時点の `main`(2026-11-03) | 257 | LICENSE ファイルなし。[README][ii-license] は元のものの複製を認め、改変した複製の配布を禁じています |
| [CashFactory][cf-tree] | `0ff4bd0` 時点の `main`(2025-04-08) | 410 | [LICENSE][cf-license-file] ファイルは GPL-3.0 ですが、[README][cf-license] は改変した複製の配布を禁じています |
| [home-assistant-passive-income][ha-tree] (HA アドオン) | リリース 2.0.6、`bf4b9f4`(2026-11-03) | 105 | Unlicense |
| CashPilot | リリース v3.0.1、`47a07fb`(2026-11-27) | 77 | GPL-3.0 |

money4band には 2 つのコードラインがあります。既定のブランチ `main`(`3bfafb1`)には今も 4.x のコードがあり、そこでの最後のコード変更は 2026-03-03 でした。リリース 5.0.0 は別の履歴からビルドされています。最新のリリースで配布されているのがそれなので、5.0.0 と比較しています。

IGM の Web UI、フリート管理、インストーラーのバイナリはクローズドソースで、リポジトリにはありません。セルがそれらに依存する場合は「README の記述」と書き、README の該当行にリンクしています。IGM の列のそれ以外はすべて、リポジトリにあるシェルスクリプトと compose ファイルによるものです。

対象外としたもの: [earning-machine](https://github.com/jf-m/earning-machine) と [passiveMachine](https://github.com/Xpl0itU/passiveMachine) は 2024 年以降コミットがありません。GitHub で検索しても、複数のアプリを動かすもので保守されているものはほかに見つからず、単一のアプリのイメージだけでした。

## 要点 { #short-version }

- **InternetIncome、money4band、IGM、そして v1.69.0 以降の CashPilot は、プロキシを通じて多くの IP で稼げます。** 最初の 3 つは各アプリをプロキシごとに 1 つ動かし、プロキシは InternetIncome の主要な機能です。CashPilot は、ワーカーにすでにデプロイしたサービスの追加のコピーを、それぞれ SOCKS5、HTTP CONNECT、または Tailscale の出口ノードのプロキシを通じて動かします([プロキシ経由のコピー](proxies.md))。
- **InternetIncome は 23、IGM は 20、CashPilot のワーカーは <!-- n:docker -->21<!-- /n --> のアプリを起動します。** CashPilot が全体で追跡するサービスはより多く(<!-- n:live -->50<!-- /n -->)、自分では動かさないブラウザー拡張、デスクトップ、GPU のサービスも追跡しています。v1.64.0 以降は、指定した任意のイメージを[カスタムサービス](custom-services.md)として動かすこともできます。
- **money4band と IGM は毎日の報酬をあなたの代わりに受け取り、Watchtower でアプリのイメージを最新に保ちます。** CashPilot はどちらもしません。イメージを取得し直すのは、デプロイまたは再デプロイしたときだけです。
- **プロバイダーのアカウントから残高を読み取り、履歴を残すのは、ここでは CashPilot だけです。** money4band 5.0.0 が表示するのは、あなたのアカウントではなく、自身のカタログに基づく見積もりです。ほかのものは各プロバイダーのダッシュボードにリンクしています。
- **多くのサーバーに 1 つの UI を持つオープンソースのものは、ここでは CashPilot だけです。** IGM の README はフリート管理をうたっていますが、そのコードはクローズドなバイナリの中にあります。
- **v1.70.0 以降、収益アプリのコンテナを既定で LAN から切り離すのは、ここでは CashPilot だけです。制限はあります。** 新規インストールと、Docker の既定のブリッジに収益アプリがないアップグレード済みのインストールではオンです。収益アプリがすでにそのブリッジにあるアップグレード済みのインストールでは、分離をオンにするまでそこにとどまります。また、`CASHPILOT_CONTAINER_NETWORK` で指定したネットワークには CashPilot はフェンスを設けません([分離](isolation.md#modes))。2.0.7 以降は Mysterium もフェンスの内側で動きます。2.0.6 までにデプロイしたノードは、再デプロイするまでフェンスのないままホストのネットワークにとどまります([フェンスの内側の Mysterium](mysterium-fence.md))。

## 横並びの比較 { #side-by-side }

CashPilot の列は v3.0.1 を説明しています。この列の各セルは短く、詳細とコードへのリンクは[表の下の注記](#cashpilot-notes)にあります。ほかの列は、上の表のコミットを説明しています。

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA アドオン |
|---|---|---|---|---|---|---|
| 起動できるアプリ([数え方](#how-we-counted)を参照) | ワーカーが動かすものが <!-- n:docker -->21<!-- /n -->、加えて[カスタムイメージ](custom-services.md)。全体で追跡するのは <!-- n:live -->50<!-- /n --> | 15([カタログ][m4b-catalog])。README は 35 としていますが、これはコミュニティのアプリと廃止したアプリを[含みます][m4b-readme-35] | 20([apps.json][igm-apps]) | 23([スクリプト][ii-script]) | 11([compose ファイル][cf-compose]) | 10([アドオンのフォルダー][ha-tree]) |
| インストール方法 | Docker Compose: UI が 1 つと、各サーバーにワーカー([フリート](fleet.md)) | Python の CLI、または compose ファイルを書き出すビルド済みバイナリ([リリース][m4b-tree]) | `curl \| sh` のインストーラー([README][igm-install])がクローズドなバイナリをダウンロードし、同じリリースの SHA256SUMS ファイルとだけ照合します([インストーラー][igm-installer-sums]) | `sudo docker run` を呼ぶ 1,608 行の bash スクリプト 1 つ([スクリプト][ii-script]) | 静的な compose ファイルと、sudo で実行する `setup.sh`([セットアップ][cf-setup]) | Home Assistant のアドオンリポジトリ。Home Assistant OS または Supervised が必要 |
| 多くのサーバーを 1 つの画面で | あり([フリート](fleet.md)) | なし、デバイスごとに 1 つのスタック | README ではありとしているが、クローズドなバイナリの中([README][igm-features]) | なし | なし | なし |
| 多くのプロキシや IP | あり、SOCKS5、HTTP CONNECT、または Tailscale の出口ノードのプロキシ経由([プロキシ経由のコピー](proxies.md)、[注記](#cashpilot-notes)) | あり([README][m4b-features]、[コード][m4b-multiproxy]) | あり([README][igm-features]、[compose][igm-proxy]) | あり、主要な機能([README][ii-readme-top]) | なし | なし |
| 収益 | <!-- n:collectors -->20<!-- /n --> のコレクターがあなたのプロバイダーのアカウントから残高を読み取り、履歴を残します | アカウントのデータではなく、カタログの範囲からの見積もり([コード][m4b-earnings]) | スクリプトには見当たらない | なし | なし | なし |
| 支払い | 残高が減ったときに支払いを提案し、確認すると記録します([スキーマ][cp-payouts]) | なし | なし | なし | なし | なし |
| 毎日の報酬の受け取り | なし | あり、サイドカー([README][m4b-features]) | あり([README][igm-features]、[compose][igm-sidecars]) | なし | なし | なし |
| 保存時の認証情報 | UI のデータベースに暗号化(Fernet)して保存([注記](#cashpilot-notes)) | 暗号化(Fernet)。鍵ファイルはデータディレクトリにあります([コード][m4b-crypto]) | 暗号化(openssl による AES-256)。鍵ファイルは保管庫の隣にあります([コード][igm-encryptor]) | `properties.conf` に平文。一部のパスワードは `docker run` の引数として渡されます([スクリプト][ii-password-arg]) | `.env` に平文([ファイル][cf-env]) | アドオンのオプション。Supervisor が `/data/options.json` に保存します([HA のドキュメント][ha-options]) |
| 収益アプリのコンテナの設定 | すべてのケーパビリティを外す、`no-new-privileges`、pids の上限。特権は拒否([注記](#cashpilot-notes)) | 特権でないすべてのサービスに `no-new-privileges`([コード][m4b-nnp])。プロキシのコンテナは `NET_ADMIN` 付きの特権コンテナ([テンプレート][m4b-tun]) | アプリのサービスには何も設定なし。Mysterium には `NET_ADMIN`([compose][igm-hosting-myst])。プロキシのコンテナには `NET_ADMIN` と、`no-new-privileges` と pids の上限([compose][igm-proxy]) | Ebesucher は `seccomp=unconfined` で動きます([スクリプト][ii-seccomp])。プロキシのコンテナと Mysterium には `NET_ADMIN` | 設定なし | 特権、ホストネットワーク、Docker API へのアクセスを求めるアドオンはなし([設定の例][ha-config]) |
| Docker ソケットのマウント先 | ソケットプロキシ(読み取り専用)と、1 回だけ動く移行用のコンテナ([注記](#cashpilot-notes)) | Watchtower([テンプレート][m4b-watchtower]) | Watchtower。読み取り専用で `no-new-privileges` 付き([compose][igm-watchtower]) | 再起動用のヘルパーコンテナ 5 つ([スクリプト][ii-sock-helper])と Watchtower([スクリプト][ii-watchtower]) | Portainer(すべてのインターフェースでポート 8000、9000、9443 に公開、[compose][cf-portainer])と、2 つの Watchtower([compose][cf-watchtower-ps]、[compose][cf-watchtower-efm]) | なし |
| イメージのタグ | <!-- n:docker -->21<!-- /n --> の収益アプリのイメージのうち <!-- n:pinned -->9<!-- /n --> つはバージョンかダイジェストに固定。残りは追従 | 15 のアプリのイメージはすべて `:latest`([例][m4b-image])。プロキシのコンテナは v2.6.0、Watchtower は `:1` に固定 | タグなしなので、Docker は `latest` を使います([compose][igm-hosting])。タグを設定しているのは一部の ARM 向けビルドだけ | ほとんどが `:latest`([例][ii-seccomp])。EarnApp は `:lite`、Honeygain は amd64 でプロキシ経由のとき 0.6.6 に固定([スクリプト][ii-honeygain])、Traffmonetizer は ARM でアーキテクチャごとのタグ。Watchtower は `:nightly` | `:latest` またはタグなし。EarnApp だけ `:lite`([compose][cf-compose]) | アドオンごとに 1 つのバージョン。毎日の CI ジョブで更新([ワークフロー][ha-bump]、[例][ha-dockerfile]) |
| アプリのイメージの更新 | デプロイまたは再デプロイのたびに取得し直す。自動更新ツールはなし | Watchtower([テンプレート][m4b-watchtower]) | 4 時間ごとに Watchtower([compose][igm-watchtower]) | オンにすれば 1 日 1 回 Watchtower([スクリプト][ii-watchtower]) | 2 つの Watchtower がそれぞれ 1 つのアプリだけを対象にします。PacketStream([compose][cf-watchtower-ps])と EarnFM([compose][cf-watchtower-efm])。ほかの 9 つのアプリは更新されません | Home Assistant のアドオンの更新 |
| LAN の分離 | 新規インストールでは既定でオン([分離](isolation.md#lan-isolation-by-default)、[注記](#cashpilot-notes)) | 独自のブリッジのサブネット([設定][m4b-subnet])。LAN は遮断しません | マージされたものはなし | 見当たらない | 見当たらない | 見当たらない |
| ARM | arm64 の UI とワーカー。デプロイのたびにプラットフォームを確認します([ARM](arm.md)) | arm64 と armv7 のバイナリ([リリース][m4b-release]) | README では amd64 と arm64、制限付きで arm32 に対応するとしており、QEMU を設定します([README][igm-arch]) | amd64 専用のイメージには binfmt のエミュレーションが必要([README][ii-arm]) | README には Raspberry Pi では動かないとあります([README][cf-raspberry]) | アドオンごと。ProxyRack は amd64 のみ([設定][ha-proxyrack]) |
| UI | Web UI と、Desktop、Android、MCP、Home Assistant のクライアント | CLI、メニュー、既定で 127.0.0.1 にバインドされるローカルの Web ダッシュボード([コード][m4b-bind]) | CLI、メニュー、README によれば LAN から届くポート 4747 の Web UI([README][igm-webui]) | なし、スクリプトのみ | ポート 80 のブックマークページと Portainer([README][cf-ui]) | Home Assistant のアドオンのパネル |
| 最新のリリース | v3.0.1、2026-11-27 | 5.0.0、2026-07-25 | 3.0.0-beta.9、2026-09-23 | バージョン付きのリリースなし | v1.10、2024-07-17 | 2.0.6、2026-11-03 |
| アプリ以外の外部への通信 | 更新の確認、パブリック IP の確認、為替レート、オンチェーンの残高。CDN からのフォントと Chart.js([注記](#cashpilot-notes)) | 更新の確認のために GitHub のリリース([コード][m4b-updater])。イメージのタグを確認するために Docker Hub と ghcr.io([コード][m4b-registry])。IP のチェックを実行したときは、パブリック IP のために `api.ipify.org`、`ifconfig.me`、または `icanhazip.com`、IP のスコアのために平文の HTTP で `ip-api.com`([コード][m4b-ipscore]) | GitHub のリリース([コード][igm-version])。パブリック IP のために `api.ipify.org`、`ifconfig.me`、または `icanhazip.com`([コード][igm-ifconfig])。IP のスコアのために平文の HTTP で `ip-api.com`([コード][igm-ipscore])。クローズドなバイナリは確認していません | 見当たらない | 見当たらない | 見当たらない |

### CashPilot の列についての注記 { #cashpilot-notes }

- **多くのプロキシや IP。** v1.69.0 以降、CashPilot はワーカーにデプロイ済みのサービスの追加のコピーを、それぞれ専用のプロキシ経由で動かします。SOCKS5 と HTTP CONNECT が運ぶのは TCP だけです。トンネルはプロキシのポートへの TCP しか外に出さないので、SOCKS5 の UDP リレーは捨てられます。Tailscale の出口ノードは UDP も運びます。収益アプリはトンネルのコンテナのネットワーク名前空間を共有します([コード][cp-proxy-deploy])。その名前空間が外に出すのは、ループバック、トンネル、トンネル自身のプロキシへの接続(そのアドレスとポートへの TCP、または tailscaled のマーク付きパケット)だけです([トンネルのファイアウォール][cp-tunnel-fw])。そのため、プロキシが落ちると収益アプリは止まり、通信が漏れることはありません([仕組み](proxies.md#how-it-works))。ホストネットワーク、公開ポート、ボリューム、デバイス、GPU、または `NET_ADMIN`、`NET_RAW`、`SYS_ADMIN` が必要なサービスや、規約でプロキシを禁じているサービスは、プロキシ経由では動かせません。そのため、<!-- n:docker -->21<!-- /n --> のうち <!-- n:noproxy -->10<!-- /n --> はサーバー自身の IP でしか稼げません([動かせないもの](proxies.md#what-cannot-run-through-a-proxy))。
- **収益。** ブラウザーからコピーした Cookie やトークンが必要なコレクターもあり、その一部は期限切れになります。どれがそうかは各サービスのガイドに書いてあります。
- **保存時の認証情報。** UI は暗号化の鍵ファイルをデータベースと同じデータボリュームに置きます([コード][cp-fernet])。収益アプリの認証情報はコンテナの環境変数として各ワーカーに届くので、そのワーカーの Docker の設定(`docker inspect`)では平文です。
- **収益アプリのコンテナの設定。** ワーカーはすべてのケーパビリティを外し、カタログがそのサービスに挙げているものを戻します。`no-new-privileges` と pids の上限を設定し、特権コンテナを拒否します([コード][cp-hardening]、[コード][cp-privileged]、[セキュリティの既定値](security-defaults.md))。Mysterium は、フェンスで囲まれたブリッジ上の専用のネットワーク名前空間で、`NET_ADMIN`、`SETUID`、`SETGID` 付きで、ダイジェストで固定したイメージで動きます([カタログ][cp-myst])。オプションの gVisor ランタイムを使うと、ユーザー空間のカーネルを加えられます([ランタイム](security-defaults.md#container-runtimes-gvisor-where-it-works))。
- **Docker ソケット。** v1.71.0 以降、ソケットをマウントするのはソケットプロキシだけです。sockguard 2.4.7 で、ダイジェストで固定し、読み取り専用です([compose][cp-sock])。ワーカーはフィルターをかけたコピーを受け取り、これは特権コンテナ、`/` やソケットのバインド、カタログにないケーパビリティやデバイスを拒否します([ソケットプロキシ](security-defaults.md#docker-socket-proxy))。1 回だけ動く `cashpilot-migrate` コンテナもソケットをマウントします。これは古いリリースが作ったものにプロキシのオーナー分離用のラベルを付け、プロキシが起動する前に終了します([compose][cp-migrate])。収益アプリがソケットを受け取ることはありません([コード][cp-mounts])。このプロキシはまだ root の境界ではありません。`CASHPILOT_COMPOSE_DIR` か `CASHPILOT_PROXY_BIND_MOUNTS` を設定していると、許可されたフォルダーに仕込まれたシンボリックリンクが、2 回のデプロイでホストの `/` に届きます([詳細](security-defaults.md#docker-socket-proxy))。Unraid と TrueNAS の掲載版は、今もワーカーに生のソケットをマウントします([アプリストア](app-stores.md))。
- **LAN の分離。** v1.70.0 以降、新規インストールと、Docker の既定のブリッジに収益アプリがないアップグレード済みのインストールでは既定でオンです。ワーカーは収益アプリを専用のブリッジに置き、そのブリッジ用のファイアウォールのテーブルを書き込みます([コード][cp-fence])。このテーブルは、プライベートの範囲、tailnet の範囲、クラウドのメタデータ、ホストが接続しているサブネット、ホスト自身への通信を捨てます。パブリック IP の検出がオンなら、自宅のパブリック IP への通信も捨てます([分離](isolation.md#lan-isolation-by-default))。収益アプリがすでに既定のブリッジにあるアップグレード済みのインストールは、**Turn on isolation** (分離をオンにする)を押すまでそこにとどまります。`CASHPILOT_ISOLATION=off` でオフになります。`CASHPILOT_CONTAINER_NETWORK` を設定すると、CashPilot はそのネットワークにフェンスを書き込まず、ファイアウォールのルールはあなたが管理します。Podman ではフェンスはなく、フリートのページにそのことが表示されます([モード](isolation.md#modes)、[コード][cp-fence-mode])。2.0.7 以降は Mysterium もフェンスで囲まれます。2.0.6 までにデプロイしたノードは、再デプロイするまでホストのネットワークにとどまります([フェンスの内側の Mysterium](mysterium-fence.md))。チェックで収益アプリが何に届くかを確認できます([チェック](isolation-check.md))。
- **外部への通信。** アプリそのもののほかに、CashPilot は次の相手と通信します。
    - GitHub のリリース。1 日 1 回、更新の確認のため(`CASHPILOT_UPDATE_CHECK=off` で停止、[コード][cp-update])。
    - `api.ipify.org`、`ifconfig.me`、または `icanhazip.com`。各ワーカーから 1 時間に 1 回、パブリック IP のため(`CASHPILOT_EGRESS_DETECT=off` で停止、[コード][cp-egress])。
    - CoinGecko と Frankfurter。為替レートのため([コード][cp-rates])。
    - mempool.space、api.kaspa.org、公開の Ethereum、Ethereum Classic、Polygon、Solana の RPC ノード。[オンチェーンの残高](onchain.md)のため。
    - iptoasn.com。ネットワーク名の表のため。多くても週に 1 回で、[アクティビティ](activity.md#network-names-and-countries)をオンにしたワーカーがあるときだけです([コード][cp-ipgeo])。
    - 各プロバイダー。コレクターのため。

    ブラウザーは Google Fonts([テンプレート][cp-cdn])と jsDelivr の Chart.js([テンプレート][cp-chartjs])を読み込みます。

読んだコードの中で、利用状況のテレメトリーを送るプロジェクトはありません。IGM のクローズドなバイナリは読めませんでした。

ここにあるどのプロジェクトも、アプリの認証情報を環境変数としてコンテナに渡します。InternetIncome は一部をコマンドの引数としても渡します。そのため、アプリを動かすホストでは、認証情報は Docker のコンテナの設定(`docker inspect` の `Env` と `Args`)に平文で入っており、Docker にアクセスできる人なら誰でも読めます。「保存時の認証情報」の行が説明しているのは、保存されたコピーだけです。

## 数え方 { #how-we-counted }

- **CashPilot。** カタログのサービスのうち、状態が active または beta で Docker イメージがあるもの。GPU コンピュートとマイニングプールは数えていません。このページの数は `scripts/generate_readme_tables.py` から来ており、ずれると CI が失敗します。
- **money4band 5.0.0。** `config/catalog/supported/` にあるアプリごとの JSON ファイル 1 つ: 15。README の「35 apps」には、既定でオフのコミュニティのカタログ([設定][m4b-community])、Docker イメージのないアプリ、廃止したアプリも含まれています。
- **IGM。** `apps.json` のエントリー: 20、すべて有効。プロキシのコンテナ、Watchtower、受け取り用のサイドカーは数えていません。
- **InternetIncome。** `internetIncome.sh` にある `# Starting ... container` のコメントブロックのうち、プロキシと Watchtower のブロックを除いたもの: 24。Ebesucher の Chrome と Firefox のブロックは 1 つのアプリで、同じ EarnFM のアカウントを使う EarnFM と EarnFM Fleetshare も 1 つです。Depin extensions のブロックは Grass と Gradient を起動するので([スクリプト][ii-depin])、2 つのアプリです。合計 23。README の表には 27 のアプリがありますが、一部は登録用のリンクだけです。
- **CashFactory。** `docker-compose.yml` にある収益を得るサービス: 11。Portainer、Web サーバー、2 つの Watchtower は数えていません。1 つのサービスはコメントアウトされています。
- **HA アドオン。** 設定ファイルのあるアドオンのフォルダー: 10。

各一覧の各アプリが今も支払いをしているかどうかは確認していません。

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
