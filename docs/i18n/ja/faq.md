---
source_hash: 915470497dbc
---
# よくある質問 { #faq }

**帯域の共有は安全ですか?**

帯域共有のサービスは、一般に正当なトラフィック(市場調査、広告の検証、価格比較、コンテンツ配信)をあなたの回線経由で流します。とはいえ、あなたは自分の IP アドレスを共有することになるので、登録する前に各サービスの利用規約とプライバシーポリシーをよく確認してください。一部のサービスでは、住宅用 IP ではなく VPS で動かすという選択肢もあります。**これは法的な助言ではありません。利用するつもりのサービスに直接確認し、必要であれば、あなたの法域について独立した法律の専門家に相談してください。**

**どれくらい稼げますか?**

収益は、地域、ISP、デバイスの数、動かすサービスによって大きく変わります。ダッシュボードは実際の収益を時系列で追跡するので、構成を最適化できます。おおまかな目安として(約束ではありません)、10〜15 のサービスを動かす自宅のサーバー 1 台で月に約 $30〜$100 になり、それより少なく、ゼロになることもあります。サーバーを増やしたり、GPU コンピュートを加えたりすると、その分増えます。

**VPS やクラウドサーバーで動かせますか?**

住宅用 IP が必要で、VPS やデータセンターの IP には支払わない(またはアカウントを停止する)サービスもあります。カタログでは、必要なものの欄に「住宅用 IP」と記載されています。VPS で使えるサービスは、自宅のハードウェアを増やさずに規模を広げるのによい方法です。

**認証情報はどのように保存されますか?**

すべてのサービスの認証情報は、`/data/.fernet_key` に保存された Fernet 鍵を使い、SQLite データベースの中で保存時に暗号化されます。この鍵は初回起動時に自動で生成されます。データベースのファイルは、マウントされた Docker ボリューム(`cashpilot_data:/data`)にあります。認証情報がサービスのコンテナ自身以外のどこかに送られることはありません。

これは `CASHPILOT_SECRET_KEY` とは別の鍵である点に注意してください。`CASHPILOT_SECRET_KEY` はログインセッションに署名するだけです。

### 暗号化キーのバックアップ { #backing-up-the-encryption-key }

認証情報を復旧できるかどうかは、`/data/.fernet_key` しだいです。このファイルを失うと、すべての認証情報を入力し直す必要があります。このファイルがなければ、保存された値を復号する方法はないからです。

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

ファイルは常に環境変数より優先されるので、すでに鍵があるインスタンスで `CASHPILOT_ENCRYPTION_KEY` を設定しても何も変わらず、安全です。この変数が採用されるのは鍵ファイルがないときだけで、それはまさに復元の場合です。

`/data` が書き込めない、またはマウントされていないために、CashPilot が鍵をディスクにまったく書けない場合、CashPilot は起動を拒否します。次の再起動で消える鍵で認証情報を暗号化するよりはよいからです。本当にそうしたい場合は、`CASHPILOT_ALLOW_EPHEMERAL_KEY=true` を設定してください。

<a id="forgot-password"></a>

### パスワードやユーザー名を忘れた場合 { #forgot-password-or-username }

CashPilot にはメールによるリセットはありません。サーバーを運用している人が、CashPilot UI コンテナのコンソールからパスワードをリセットします。サービス、収益、保存した認証情報には影響しません。これらはパスワードではなく `/data/.fernet_key` で暗号化されているからです。

`python -m app.users` コマンドには CashPilot 2.3 以降が必要です。2.2 以前では `No module named app.users` で失敗します。先に更新してください。Docker Compose では、`drumsergio/cashpilot` と `drumsergio/cashpilot-worker` のタグを `2.3` 以降に変え(`2.2` や `2.2.9` のような固定はそのリリースにとどまります)、`docker compose up -d` を実行します([CashPilot の更新](getting-started.md#updating-cashpilot))。Unraid では、コンテナを更新してください。

1. アカウントを一覧表示します。忘れたユーザー名もこれでわかります。ユーザー名は大文字と小文字を区別します。

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. そのアカウントに新しいランダムなパスワードを設定します。`alice` は、ステップ 1 のユーザー名に置き換えてください。

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    オーナーがちょうど 1 人の場合は、ユーザー名を省略でき、コマンドはそのオーナーをリセットします。ユーザー名が `-` で始まる場合は、その前に `--` を付けてください: `reset-password -- -alice`。

    コマンドは新しいパスワードを 1 回だけ表示します。

3. ほかの誰かがそのアカウントにアクセスできた可能性がある場合は、今すぐ UI コンテナを再起動してください(`docker restart cashpilot-ui`)。そのユーザーとしてサインインしたままのブラウザーは、再起動して初めてサインアウトされます。パスワードを忘れただけなら、再起動は任意です。
4. 新しいパスワードでサインインし、アバターメニュー(右上)の **Change password** (パスワードを変更)から変更してください。

コンテナの名前は、CashPilot をどうインストールしたかによって変わります。

| インストール方法 | UI コンテナ |
|---|---|
| `docker-compose.yml`、CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot`(`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | 生成された名前。`docker ps` で表示されます |

Portainer、Unraid、CasaOS にも、コンテナのコンソールを開くボタンがあります。このコマンドは端末からの入力を必要としないので、そこでも動きます。

ユーザー名を変更するには:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

新しい名前は登録時のルールに従います。3〜32 文字の英字、数字、`_` または `-` です。表示を確認するには、サインアウトしてもう一度サインインしてください。

**不正アクセスが疑われる場合**、たとえば `/data/.secret_key` を含むバックアップをなくした場合は、パスワードのリセットだけでは足りません。その鍵を持つ人は有効なログイン Cookie に署名でき、リセットではそれを止められません。鍵を置き換え、UI コンテナを再起動してください。`&&` により、新しい鍵が用意できたときだけ再起動します。コマンドがエラーを表示したら、先にそれを直してください。

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

再起動後はすべてのブラウザーがサインアウトされ、全員が自分のパスワードでもう一度サインインします。保存した認証情報には影響しません。`CASHPILOT_SECRET_KEY` を自分で設定している場合、コマンドは拒否します。代わりに、その変数に新しいランダムな値を入れて、コンテナを作り直してください。イメージから `docker run` で実行したものはその変数を見られず、拒否できないので、UI コンテナに対して `docker exec` を使ってください。

新しい鍵は偽造された Cookie を無効にしますが、攻撃者が中にいる間にしたことは元に戻りません。さらに 2 つの手順があります。

1. `docker exec cashpilot-ui python -m app.users list` を実行します。見覚えのないアカウントは、ダッシュボードから削除してください。
2. なくしたコピーが `/data` 全体を含んでいた場合は、プロバイダーのアカウントのパスワードを変更してください。`.fernet_key` と `cashpilot.db` がそろうと、保存したすべての認証情報を復号できます。

後で、鍵を入れ替える前に作ったバックアップを復元する場合は、その `.secret_key` を除外するか([バックアップと復元](backup-restore.md#restore))、もう一度入れ替えて再起動してください。そうしないと古い鍵が戻ってきます。復元したデータベースは、そこに含まれていたアカウントとパスワードも戻すので、アカウントの確認と必要なパスワードのリセットをもう一度行ってください。

**UI コンテナが起動しない場合**は、同じイメージから、同じデータに対してコマンドを実行します。まず、UI の `/data` があるホストのフォルダーを見つけます。これは停止中のコンテナでも、名前付きボリュームでもバインドマウントでも(Unraid、CasaOS、Runtipi)使えます。

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

次に、そのフォルダーをマウントし、使っているイメージのタグを指定します。

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

一覧に自分のアカウントが表示されることを確認してから、`list` の代わりに `reset-password alice` を付けて同じ行を実行します。

データベースのないパスを指定すると「no database」のエラーになり、コマンドはそこで何も作らず、何も変えません。それでも Docker がその名前の空のフォルダーやボリュームを残すことがあるので、削除してください。

データボリュームは**削除しないでください**。`/data/.fernet_key` が消え、それとともに保存したすべての認証情報も消えます。`users` テーブルの行も**削除しないでください**。

**CashPilot を完全に削除するには?**

`docker compose down -v` が削除するのは、CashPilot 自身のコンテナだけです。CashPilot がデプロイしたサービスは動き続け、そのデータ、フェンスで囲まれたネットワーク、ファイアウォールのテーブルも残ります。[CashPilot を完全に削除する](uninstall.md)では、そのすべてを削除し、何が完全に失われるかを説明し、何も残っていないことを確認する方法を示します。

**セキュリティはどうですか?**

CashPilot がデプロイするサービスは、それぞれ専用のコンテナで動き、Linux のケーパビリティはすべて外されています(いくつかのサービスは、自分で宣言したものだけを戻します)。また `--security-opt no-new-privileges` が設定されているので、中のプロセスが権限を得ることはできません。コンテナからは、サービスが宣言したボリューム以外のホストのファイルシステムは見えません。新規インストールでは、ワーカーがコンテナをフェンスで LAN、ホスト、tailnet、クラウドのメタデータから切り離すので、コンテナが届くのはインターネットだけで、ローカルのものには届きません([ネットワークの分離](isolation.md))。Podman ではフェンスを使えません。収益アプリは Podman の既定のネットワークで動き、LAN に届いてしまいます。**Fleet** (フリート)ページにもそう表示されます([ネットワークの分離](isolation.md)に選択肢があります)。1.70 より前のリリースからアップグレードしたインストールでは、**Fleet** (フリート)ページで **Turn on isolation** (分離をオンにする)をクリックするまで、収益アプリは LAN に届く Docker の既定のブリッジにとどまります。2.0.7 以降は Mysterium もフェンスの内側で動きます。2.0.6 までにデプロイしたノードは、再デプロイするまでホストのネットワークにとどまります([Mysterium ノードをフェンスの内側へ移す](mysterium-fence.md))。代わりに自分のブリッジにファイアウォールを設定する方法は、[ホームネットワークを守る](home-network-security.md)で説明しています。サービスの認証情報は、Fernet の対称暗号で保存時に暗号化されます。UI は Docker にアクセスできません。配布している compose ファイルでは、ワーカーに生の Docker ソケットが渡されることはありません。ワーカーは `cashpilot-socket-proxy` を通じて Docker に接続し、このプロキシは特権コンテナと、`/` またはソケットのバインドを拒否します(ただし、そのどちらか、またはソケットより上のフォルダーを `CASHPILOT_PROXY_BIND_MOUNTS` か `CASHPILOT_COMPOSE_DIR` に入れた場合は別で、プロキシはそれをそのまま受け入れます)。さらに、ワーカーが扱えるのを、オーナーのラベルが付いたコンテナ、ボリューム、ネットワークに限ります([セキュリティの既定値](security-defaults.md))。Unraid のテンプレートと TrueNAS のアプリは、今もワーカーに生のソケットをマウントします。これはホストの root 権限と同じです([アプリストア](app-stores.md))。

とはいえ、完全に安全な構成はありません。外部のトラフィックを自分のネットワーク経由で流すサードパーティーのソフトウェアを動かしていることに変わりはありません。Docker による分離は、これらのサービスをホストで直接動かす場合に比べて攻撃対象領域を大きく減らしますが、すべてのリスクをなくすわけではありません。CashPilot は専用のマシンか VLAN で動かし、Docker とホストの OS を最新に保ち、デプロイする前に各サービスのオープンソースのコードを確認することをおすすめします。

**サービスのコンテナがクラッシュしたらどうなりますか?**

CashPilot はコンテナの正常性を常に監視しています。サービスのコンテナが予期せず終了すると、自動で再起動されます。ダッシュボードには、動いているすべてのサービスの稼働時間と正常性が表示されます。

**再デプロイ後に Mysterium ノードが起動しません。なぜですか?**

最も多い原因は、その UDP の範囲にあるポートを、ホストのほかのプログラムがすでに使っていることです。Docker は範囲内のすべてのポートを確保する必要があるので、使用中のポートが 1 つでもあると起動できません。空いたままになる範囲の選び方は、[UDP ポートの範囲を選ぶ](mysterium-fence.md#choosing-the-udp-port-range)で説明しています。

**プロキシ経由のコピーは動いているのに、何も稼ぎません。なぜですか?**

プロキシが、その収益アプリのサーバーへの接続を拒否しているか、ポート 80 と 443 しか許可していないのかもしれません。CashPilot の **Test** (テスト)が確認するのは、プロキシがインターネットに届くことだけです。収益アプリ自身のホストとポートを確認する方法は、[プロキシ経由で収益アプリのサーバーを調べる](proxies.md#probe-an-earners-servers-through-the-proxy)で説明しています。

**どのサービスが重く、どこで動かすべきですか?**

最も多くのリソースを使うのは、ストレージノード、リレーと VPN の出口、GPU の処理です。[小さなマシンの予算を立てる](fleet.md#budgeting-a-small-box)では、それらを一覧にし、決める前に各コンテナを測る方法を示しています。

<a id="worker-lost-docker"></a>

### Docker の更新後にワーカーが Docker を見失った場合 { #the-worker-lost-docker-after-a-docker-update }

**見える症状。** ワーカーは **Fleet** (フリート)ページでオンラインのままですが、CashPilot はそのコンテナを起動、停止、更新できません。**Fleet** (フリート)ページでは、ワーカーの隣に **Docker unreachable** (Docker に接続できません)と表示されます。10 分後、ワーカーのヘルスチェックが失敗します(`docker ps` でワーカーが `unhealthy` と表示されます)。30 分後、ベルと通知で、ワーカーが Docker に接続できないことが知らされます。`docker logs cashpilot-socket-proxy` には `upstream Docker socket unreachable` と表示され、最新の compose ファイルでは、約 3 分以内に `docker ps` でプロキシが `unhealthy` と表示されます。収益アプリは動き続けます。

**原因。** 配布している compose ファイルは、ソケットファイル `/var/run/docker.sock` を `cashpilot-socket-proxy` にバインドします。ファイルのバインドが保持するのは、その 1 つのファイルです。Docker の更新(たとえば `unattended-upgrades` が新しい `docker-ce` をインストールするとき)は Docker を再起動し、Docker は同じパスに新しいソケットファイルを作ります。Docker の live-restore がオンだと、プロキシはその再起動の間も動き続け、古いファイルを保持したままになります。古いファイルでは何も応答しません。

**すぐできる対処。** そのマシンでプロキシを再起動します。

```bash
docker restart cashpilot-socket-proxy
```

再起動すると新しいソケットがバインドされ、ワーカーは次のハートビートで再び Docker を見つけます。ワーカーを再起動する必要はありません。Unraid と TrueNAS ではワーカー自身がソケットを持つので、ワーカーを再起動してください。

**恒久的な対処。** ソケットファイルではなく、ソケットのフォルダーをバインドします。フォルダーのバインドでは、置き換えられたソケットがすぐに見えます。compose ファイルの `cashpilot-socket-proxy` サービスで、`- /var/run/docker.sock:/var/run/docker.sock:ro` の行を下のバインドに置き換え、その `environment` に `SOCKGUARD_UPSTREAM_SOCKET` の行を追加します。

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

その後、`docker compose up -d` を実行します。同じ変更は `docker-compose.worker.yml` と `docker-compose.fleet.yml` でも使えます。Compose がこれらのファイルを読むのは名前を指定したときだけなので、`COMPOSE_FILE` ですでにそのファイルを指定している場合を除き、`docker compose -f docker-compose.worker.yml up -d` または `docker compose -f docker-compose.fleet.yml up -d` を実行してください。

- `recursive: disabled` は必須です。`/var/run` にはほかのマウントもあります。たとえば `/run/docker/netns` にある Docker のネットワーク名前空間や `/run/user/...` です。再帰的なバインドは、それらをすべてプロキシに持ち込みます。再帰的でないバインドは、フォルダーそのものだけを見せます。
- `SOCKGUARD_UPSTREAM_SOCKET` はプロキシに新しいパスを使わせます。ポリシーのブロックとそのフィンガープリントはそのままです。環境変数がポリシーの `upstream.socket` を上書きするからです。この変数がないとプロキシは起動しません(`upstream socket not found (/var/run/docker.sock)`)。
- `cashpilot-migrate` はファイルのバインドのままでかまいません。`docker compose up` のたびに起動し直すので、常に最新のソケットを受け取ります。同じフォルダーのバインドを使わせる場合は、その `environment` に `DOCKER_HOST=unix:///host-run/docker.sock` を追加してください。ワーカー 2.8.4 以降はこの変数を読みます。プロキシのソケットを指定してはいけません。マイグレーターにはホスト自身のソケットが必要です。
- フォルダーのバインドは、Docker のものだけでなく、`/var/run` にあるすべてのソケットをプロキシに渡します。一般的なサーバーでは、systemd 自身のソケット、D-Bus、Tailscale や snapd などのツールのソケットが含まれます。`read_only` は、プログラムがソケットに接続するのを止めません。また、プロキシは root で動きます。Docker ソケットへのアクセスはすでにホストの root 権限を与えるので、侵害されたプロキシが新たに得るものはわずかです。プロキシに Docker ソケットだけを持たせたい場合は、ファイルのバインドのままにして、Docker の更新後にプロキシを再起動してください。そのタイミングは上のアラートが知らせます。
- Docker Compose 2.30.0 以降が必要です。それより古いリリースは `Additional property recursive is not allowed` でファイル全体を拒否します。確認するには `docker compose version` を実行してください。Debian 13 がパッケージにしている Compose は 2.26.1 なので、Debian では Docker 自身のリポジトリから Compose をインストールしてください。アプリ内の更新は独自の Compose 2.33 を使うので、変更したファイルを読めます。
- Linux でしか動きません。macOS と Windows の Docker Desktop が仮想マシンに対応付けるのは `/var/run/docker.sock` だけです。そこでは `/var/run` は Mac や PC 上のフォルダーで、中に Docker ソケットはありません。
- rootless の Docker では、ソケットは別のマウントである `/run/user/<your uid>` にあります。そのフォルダーを `source` に使ってください。
- Podman では、ファイルのバインドのままにしてください。Podman ではフォルダーのバインドをテストしていません。

配布しているファイルはファイルのバインドのままです。フォルダーのバインドには Compose 2.30 と Linux が必要で、CashPilot は古い Compose のリリースと Docker Desktop にも対応しているからです。新しくダウンロードした compose ファイルにはあなたの変更が入っていないので、ファイルを置き換えた後にもう一度変更してください。
