# ASUS V3607VU を研究用サーバーにする

Vivobook 16 V3607VU_V3607VU（ASUS国内製品名「ASUS Gaming V16 V3607VU」）の構成は **Ubuntu Server 26.04 LTS（amd64）、アプリ用CPython 3.13.18、Node.js 24、systemd、SQLite** です。Ubuntu 26.04の標準Pythonは3.14系列です。OSの管理ツールはシステムのPythonを使い、アプリと更新スクリプトは指定した3.13.18で仮想環境を作ります。[Ubuntuの配布](https://releases.ubuntu.com/26.04/)・[OS標準Pythonのパッケージ](https://packages.ubuntu.com/resolute/python3)・[CPython 3.13.18の公式配布](https://www.python.org/downloads/release/python-31318/)

FastAPIとCPUで動く推定器を1プロセスで常駐させ、ビルド済みの画面を同じサーバーから配信します。Core 7 240Hとメモリ16 GBを使い、RTX 4050 6 GB用のCUDAやGPUドライバーの追加導入は手順から省いています。処理対象は架空データで、サーバーのRealtek 8852BEは通信用です。無線カードを認識しても、それだけで教員PCからの測定値が集まることはありません。校内に設置する段階では、収集方法・公開先・権限・保持期間を学校と別途決めます。[情報管理](SECURITY.md)・[学校への確認事項](SCHOOL_QUESTIONS.md)

| 用途 | 設定 |
|---|---|
| サーバーへの接続 | 許可された家庭・検証用LANで管理PCからSSH。ブラウザはSSHトンネルを通して利用 |
| Web・API | systemdが起動。Vivobook側の `127.0.0.1:8000` で待ち受ける |
| アプリとデータ | アプリは `/opt/wifi-location/releases`。SQLiteはリリースの外の `/var/lib/wifi-location/demo.sqlite3` |
| AP | Cisco AIR-AP1832I-Q-K9C（申告型番）。現在の管理方式、台数・設置場所、取得できる測定項目は管理者に確認する。[APの確認手順](NETWORK.md) |
| GitHub | サーバー専用の読み取り専用Deploy keyでprivateリポジトリの `main` を取得。初回以降は `sudo wifi-location-update` |
| 電源とネットワーク | 付属ACアダプターと、有線LANでの常時接続を優先。本体に端子がなければUbuntuで認識するUSB-LANアダプターを使用 |

## 1. OSのインストール先を決める

Ubuntu 26.04を導入済みなら、手順1の末尾でOSとSSHの接続を確認し、手順2へ進みます。

**Windowsから常設する専用機に切り替える場合**は、Windowsの必要なファイルを外部媒体にバックアップし、実際に開けることを確認します。デバイス暗号化・BitLockerを使用中なら回復キーを別の場所に保管し、Windowsへ戻すための回復手段も用意してください。インストーラーの「Use an entire disk」は選択したディスクのWindows・回復パーティションを含むデータを消去します。対象ストレージの型番と容量を最後の確認画面で照合してください。

**Windowsを使い続ける場合**は、仮想化ソフトで新しい仮想ディスクを作り、その中へ同じUbuntu Serverを入れて試せます。16 GB機なら開始時の割当例は4仮想CPU、メモリ8 GB、仮想ディスク64 GBです。SSHで接続できるよう仮想ネットワークを設定し、手順3では `--no-laptop` を指定します。ふた・電池・物理Wi-Fiの管理はWindows側で行います。仮想ディスク上での成功と物理無線カードの検証は別に記録してください。

1. 公式配布ページの `ubuntu-26.04…-live-server-amd64.iso` を選び、署名付き `SHA256SUMS` で照合します。実機なら中身を消してよいUSBメモリにISOを書き込み、UEFIの起動メニューからUSBを選びます。VMならそのISOを仮想ドライブに割り当てます。[Ubuntu 26.04の配布](https://releases.ubuntu.com/26.04/)・[署名とハッシュの検証](https://documentation.ubuntu.com/security/software-integrity/image-verification/)
2. ACアダプターを接続し、初回は有線のDHCPを使います。無線がインストーラーで認識されなくても、有線があれば更新済みのカーネルとファームウェアを入れられます。LANでのアドレスを固定したい場合は管理しているルーターでDHCP予約を設定します。
3. 通常のUbuntu Serverを選び、管理者ユーザー（例 `operator`）を作り、「Install OpenSSH server」を有効にします。管理PCのSSH公開鍵を自分のGitHubアカウントに登録済みなら、インストーラーの「Import SSH key」でそのユーザー名を指定できます。ストレージの暗号化を選び起動時のパスフレーズ入力が必要になった場合は、再起動後に現地で解除できる保守時間を確保します。
4. 再起動してVivobook本体のコンソールで以下を実行し、Ubuntuの版、CPUアーキテクチャ、LANアドレス、SSHホスト鍵の指紋を確認します。

```bash
. /etc/os-release && echo "$PRETTY_NAME"
dpkg --print-architecture
ip -br -4 addr
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

以下は管理PCがmacOSまたはLinuxの場合の例です。ユーザー名と `192.168.1.20` を実機の値に置き換えます。初回接続時は管理PCに表示されるEd25519の指紋と、本体で見た指紋が一致することを確認します。

```bash
ssh -o HostKeyAlgorithms=ssh-ed25519 operator@192.168.1.20
```

インストール時に公開鍵を取り込まずパスワードで接続した場合は、管理PCで `ssh-copy-id -i ~/.ssh/id_ed25519.pub operator@192.168.1.20` を実行して管理PCの公開鍵を追加できます。ファイル名は使用する公開鍵に合わせます。

## 2. 認証済みの管理PCからセットアップ用ファイルを渡す

**このリポジトリを既に読める管理PC**のローカルクローンで以下を実行します。一時アーカイブに入れるのはGitHubの `main` に保存済みの `deploy/` だけです。初回の鍵登録前にも使えます。以前24.04用のファイルをVivobookに転送した場合も、この手順で新しいインストーラーを取得します。macOSの例は `shasum -a 256`、Linuxなら `sha256sum` を使えます。

```bash
git remote get-url origin
git fetch origin main
git log -1 --format='%h %s' FETCH_HEAD
bundle_dir=$(mktemp -d)
bundle="$bundle_dir/wifi-location-deploy.tar.gz"
git archive --format=tar.gz -o "$bundle" FETCH_HEAD deploy/
shasum -a 256 "$bundle"
scp "$bundle" operator@192.168.1.20:~/
```

`origin` が `suzur4/wifi-location-estimation` を指すことを確認してください。初回の転送にはUSBで同じアーカイブをVivobookのホームにコピーする方法も使えます。Vivobookで次を実行し、展開前のSHA-256が管理PCと一致することを確かめてください。

```bash
cd ~
sha256sum wifi-location-deploy.tar.gz
mkdir -p ~/wifi-location-bootstrap
tar -xzf wifi-location-deploy.tar.gz -C ~/wifi-location-bootstrap
cd ~/wifi-location-bootstrap
bash deploy/setup-server.sh --help
```

## 3. Vivobookで取得用の鍵を作り、起動する

アプリとGitHubの取得鍵は `/opt` 配下に置きます。導入前に `stat -c '%U %a %n' /opt` で権限を確認してください。専用機での想定は `root 755 /opt` です。他のユーザーが `/opt` を書き換えられる場合はセットアップが停止します。

Vivobookの `~/wifi-location-bootstrap` で、まずアプリ用Pythonを選びます。**既に3.13.18が入っている場合**は、実体のバージョンとパスを確認し、そのパスでセットアップします。サービス起動後も使えるよう、管理者が所有し一般ユーザーが書き換えられない場所に置いた通常版のCPythonを使います。ホーム配下の開発用仮想環境しかない場合は次の新規導入手順を使ってください。

```bash
cd ~/wifi-location-bootstrap
app_python=$(command -v python3.13)
"$app_python" -I -c 'import sys; print(sys.executable, sys.version)'
# CPython 3.13.18 と確認できた管理者所有の実行ファイルを指定する
sudo bash deploy/setup-server.sh --python "$app_python"
```

**新規導入の場合**は次の2行で、公式ソースから3.13.18を `/opt/wifi-location-python/3.13.18` に導入し、セットアップします。1行目は通常の管理ユーザーで実行します。ソースのSHA-256を公式配布値と照合し、ビルドは一般ユーザーで行い、パッケージ導入と完成版の配置にsudoを使います。Ubuntuの `/usr/bin/python3` はOSが管理します。インストール先には、サービスの再起動・更新・旧版への切り戻しで使う実行ファイルがあるため、運用中は保持してください。[ソース配布・SHA-256](https://www.python.org/downloads/release/python-31318/)

```bash
cd ~/wifi-location-bootstrap
bash deploy/install-python.sh && sudo bash deploy/setup-server.sh
```

同梱スクリプトで3.13.18を導入済みの場合、再セットアップ時は `sudo bash deploy/setup-server.sh` だけを実行します。初回は本体を操作できる状態で進めます。パッケージ配布元とGitHubへの通信が必要です。既存のUbuntu 24.04で運用を続ける場合は、従来どおり同じセットアップコマンドでOSのPython 3.12を使います。

1. セットアップがVivobook上でSSH鍵ペアを生成します。表示された `ssh-ed25519` で始まる**公開鍵1行**をコピーします。再表示は `sudo -H -u wifiloc-fetch cat /opt/wifi-location/fetch/.ssh/github_deploy_ed25519.pub` です。この鍵はVivobookがGitHubからコードを読むときに使用します。
2. 管理PCのGitHubでこのリポジトリの **Settings → Deploy keys → Add deploy key** を開きます。Titleを `V3607VU server` などにし、公開鍵を貼り、**Allow write accessはオフ**で登録します。個人の秘密鍵やPATをVivobookへコピーする必要はありません。[このリポジトリのDeploy keys](https://github.com/suzur4/wifi-location-estimation/settings/keys)・[GitHubのDeploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
3. Vivobook側でEnterを押すと接続確認と初回取得が進みます。途中で終了した場合は鍵を登録後に同じセットアップコマンドを再実行します。接続時にはGitHub公式のEd25519ホスト公開鍵と照合します。鍵の変更を通知されたら公式発表と新しい指紋を確認してセットアップファイルを更新します。標準の接続先は `ssh.github.com:443`。これはTCP 443上のSSHで、HTTPS限定のプロキシでは制限される場合があります。通常のSSHが許可された回線では `--github-port 22` も選べます。[GitHubのホスト鍵](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)・[SSHの443番接続](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)
4. テストとフロントエンドのビルドに成功するとサービスが起動します。専用の `wifiloc-fetch` がソースを取得し、`wifiloc` がビルド・実行します。管理トークンとDBの場所を決めるファイルは `/etc/wifi-location/wifi-location.env` です。カーネル変更後などに再起動を案内された場合は保守時間に `sudo reboot` し、再びSSHで接続します。

起動を確かめるには、**Vivobook側**で次を実行します。`is-enabled` が `enabled`、`is-active` が `active`、ヘルスが `"status":"ok"`、トップページがHTTP 200なら、サービスと画面を配信できています。`--status` の実行中コミットをGitHubの `main` と照合できます。

```bash
systemctl is-enabled wifi-location.service
systemctl is-active wifi-location.service
sudo wifi-location-update --status
sudo -u wifiloc /opt/wifi-location/current/.venv/bin/python -I -V   # Python 3.13.18
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/
```

## 4. 管理PCのブラウザで開く

**管理PC側**でトンネルを開いている間、ブラウザから [http://127.0.0.1:18000/](http://127.0.0.1:18000/) に接続できます。ブラウザ側を18000番にしているので、既存の開発用8000番と両立します。終了はそのターミナルでCtrl+Cです。

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:8000 operator@192.168.1.20
```

管理画面のトークンは、別のSSHセッションで `sudo grep '^WIFI_ADMIN_TOKEN=' /etc/wifi-location/wifi-location.env` を実行して本人の端末で確認します。トークンはこのトンネルで開いた画面に入力してください。初期の測定は3分で期限を迎えるので、動作を試すときは管理画面の「模擬データを更新」を使います。

### 信頼できる検証用LANに生徒用画面を出す場合

模擬データを同じLANの端末に表示したい場合だけ、管理者が許可した**プライベートIPv4サブネット1つ**を指定します。下例の `192.168.1.0/24` は実際の許可範囲に置き換えます。セットアップは既存nginxにこのアプリ専用の設定を追加します。事前にnginxが必要です。新規導入の場合は管理用SSHの許可元と受信ファイアウォールを確認したうえで `sudo apt install nginx` を実行します。Ubuntuパッケージの初期サイトが別途80番で起動する場合があるため、有効サイトと実際の待受を確認してください。専用機の初期サイトを使わない場合は管理者がそのサイトを無効化します。

```bash
cd ~/wifi-location-bootstrap
sudo bash deploy/setup-server.sh --lan 192.168.1.0/24
sudo nginx -t
sudo ss -ltnp
sudo ufw status verbose
```

UFWが有効で、8080番の規則が必要な場合は `sudo ufw allow from 192.168.1.0/24 to 192.168.1.20 port 8080 proto tcp` で指定範囲だけを許可します。許可した端末から例として `http://192.168.1.20:8080/` を開き、名簿・掲示を確認します。nginxは一覧に必要な読み取りAPIだけを通します。管理・研究画面は上のSSHトンネルで開きます。LAN表示をやめるときは `sudo bash deploy/setup-server.sh --no-lan` を実行し、上記のUFW規則も自分で追加した場合は `sudo ufw delete allow from 192.168.1.0/24 to 192.168.1.20 port 8080 proto tcp` で取り除きます。

## 5. GitHubから次の版を取得する

管理PCで通常どおり変更をGitHubの対象ブランチへ保存します。Vivobookで次を実行すると、新しいコミットを別のディレクトリに取得・展開し、依存を導入し、テスト・ビルドの成功後に `current` を切り替えます。ネットワーク切断やビルド失敗なら切り替え前の版が動き続けます。起動に失敗した場合は、以前の版があるときに復帰を試みます。常設中のDBはリリース間で共有されます。

```bash
sudo wifi-location-update
sudo wifi-location-update --status
sudo journalctl -u wifi-location.service -n 50 --no-pager
```

更新は初期状態では手動です。自動反映してよい検証機では `--auto-update` を付けてセットアップすると、更新タイマーが約15分間隔で取得します。直ちにタイマーを止めるには `sudo systemctl disable --now wifi-location-update.timer`、以降のセットアップでも停止を維持する設定は `--no-auto-update` です。明示的に前の版へ戻す場合は、タイマーを止めてから `sudo wifi-location-update --rollback` を実行し、再度ヘルスと画面を確認します。ロールバックで切り替わるのはアプリです。DB形式に互換性のない変更を入れるときは更新前のDBバックアップも必要です。

`deploy/` 配下のインストーラー・systemd設定自体が変更された版では、手順2から新しいセットアップ用ファイルを取り直し、内容を確認してセットアップを再実行します。アプリの自動更新権限を与える対象は慎重に選んでください。対象ブランチへpushできる人のコードがVivobookで実行されます。

## 6. 無線・電源を実機で確認する

26.04のカーネルとファームウェアを使います。有線に接続した状態で次を確認します。機種名だけでは無線チップや搭載ドライバーを断定できないので、`lspci -nnk` のPCI ID、`Kernel driver in use`、カーネルログを併せて見てください。[Ubuntu 26.04のカーネル](https://packages.ubuntu.com/resolute/linux-generic)・[linux-firmware](https://packages.ubuntu.com/resolute/linux-firmware)

```bash
uname -r
lspci -nnk | grep -A3 -Ei 'network controller|ethernet controller'
ip -br link
apt-cache policy linux-generic linux-firmware
sudo journalctl -k -b --no-pager | grep -Ei 'rtw89|firmware'
```

`lspci` は `pciutils` パッケージに含まれます。RealtekのPCI IDが `10ec:b852` または `10ec:b85b` ならLinuxの `rtw89_8852be`、`10ec:b520` なら `rtw89_8852bte` の照合対象です。ドライバー名・ファームウェア読込・インターフェースの3点を実機で確かめてください。未認識の場合は有線で `sudo apt update`、`sudo apt install linux-generic linux-firmware pciutils` を実行し、保守時間に再起動して比較します。無線の設定は本体コンソールから行い、SSHで接続している経路を確保します。[Linuxの8852BE用ドライバー](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw89/rtw8852be.c)・[8852BTE用ドライバー](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw89/rtw8852bte.c)

純正ACアダプターを使い、排気口が開く硬い台に置きます。初回はふたを開けてビルドし、発熱・ファン・充電状態を確認します。常設時のふた閉じ・スリープ抑制は `deploy/conf/`、充電上限と停電時の動作は `deploy/laptop-power.sh` にあります。充電上限は対応する機体で標準80%、バッテリー放電中に残量15%以下でシャットダウンします。復電後の自動起動は実機・UEFIの設定に依存するため、無人運用前に復帰方法を現地で確認します。

セットアップの選択は `/etc/wifi-location/setup.conf` に保存します。無線が不安定な場合は、まず有線に切り替えてログを確認し、該当するRealtekカードで `--wifi-workaround` を付けて再実行する方法があります。充電上限は `--charge-limit 60` のように変更できます。OSの再起動が必要な更新は現地で予定を決めて適用し、自動再起動を許可する場合は `--auto-reboot` を選びます。SSHのパスワード認証を止める `--ssh-keys-only` は、別ターミナルから管理ユーザーの鍵だけでログインできることを確認してから使用します。[Ubuntuの自動更新](https://ubuntu.com/server/docs/how-to/software/automatic-updates/)

```bash
systemctl list-timers --all battery-guard.timer
sudo journalctl -u battery-charge-limit.service -b -n 10 --no-pager
ls /sys/class/power_supply/
```

## トラブル時の切り分け

| 症状 | Vivobookでの確認 |
|---|---|
| GitHubの取得が失敗 | `sudo -H -u wifiloc-fetch git ls-remote git@github-deploy:suzur4/wifi-location-estimation.git refs/heads/main` を実行。SHAとブランチ名が返れば、鍵・接続先・privateリポジトリの読取権限は有効。失敗時は表示されたSSHエラー、公開鍵の登録先、許可された送信先ポートを確認 |
| アプリを更新できない | 手動更新なら端末の最初のエラー、自動更新なら `sudo journalctl -u wifi-location-update.service -n 100 --no-pager`。依存取得の通信、`df -h /opt /var/lib`、テスト結果を確認して再実行 |
| ブラウザで開けない | 手順3のヘルスとトップページをVivobook自身で確認。成功なら管理PCのSSHトンネルの接続先・ローカルポートを確認。失敗なら `sudo systemctl status wifi-location.service` とサービスログを確認 |
| 無線が切れる | USB有線で運用を継続し、PCI ID・カーネル・`rtw89` ログと切断時刻を記録。カードの切断とアプリ停止はヘルスで切り分ける |
| SSHホスト鍵の変更が表示される | OS再導入などの記録を確認し、本体コンソールで取り直した指紋と照合。GitHub向けホスト鍵はGitHubの公式指紋で確認 |
| サーバーを廃止・紛失 | GitHubの対象リポジトリでそのDeploy keyを削除。管理トークンを交換し、別保管したDBバックアップを管理方針に沿って扱う |

この手順で別途確認する項目は、V3607VU実機での無線安定性、温度、対応する充電上限、再起動・停電後の復帰、GitHubへの実機固有鍵の登録と実機での初回取得です。学校側に関わる接続や測定は学校との合意後の工程です。

## SQLiteの保存と復元

次は標準のDBパスを使う例です。更新前に稼働中のDBのスナップショットを作ります。`.backup` は書き込み中でも整合したコピーを取得できます。出力先には教員設定や最新の測定も含まれるので、保管先と削除日を決め、ディスク故障に備える場合は別の媒体へコピーしてください。[SQLiteのオンラインバックアップ](https://www.sqlite.org/backup.html)

```bash
sudo apt install sqlite3
sudo install -d -m 0700 -o wifiloc -g wifiloc /var/backups/wifi-location
snapshot=$(sudo -u wifiloc mktemp /var/backups/wifi-location/demo-XXXXXXXX.sqlite3)
db=/var/lib/wifi-location/demo.sqlite3
sudo -u wifiloc sqlite3 -readonly "$db" ".backup $snapshot" &&
  sudo -u wifiloc sqlite3 -readonly "$snapshot" 'PRAGMA quick_check' &&
  printf '保存先 %s\n' "$snapshot"
```

`quick_check` の結果が `ok` であることを確認します。復元時は管理者用のSSHセッションで `snapshot` に戻したいファイルの絶対パスを設定し、現在のDBも別名でバックアップします。次の手順は更新処理と同じロックを取り、アプリを止めてからDBの内容を置き換えます。ロックを取得できない場合は実行中の更新が完了した後に再度実行してください。

```bash
sudo flock -n /run/wifi-location-update.lock bash -eu -c '
  test -s "$1"
  test "$(runuser -u wifiloc -- sqlite3 -readonly "$1" "PRAGMA quick_check")" = ok
  systemctl stop wifi-location.service
  runuser -u wifiloc -- sqlite3 "$2" ".restore \"$1\""
  systemctl start wifi-location.service
' restore "$snapshot" "$db"
curl --retry 10 --retry-connrefused --retry-delay 1 -fsS http://127.0.0.1:8000/api/health
```

復元したDBと互換性のある版のアプリを使い、画面で登録内容を確認します。復元処理が途中で失敗した場合は、エラーと選んだスナップショットを確認し、復元に成功してからサービスを再開してください。
