# 市川昴高校 教員PCエリア案内・研究プロトタイプ

Wi-Fiの受信強度（RSSI）からPCのおおまかな所在エリアを推定する研究用アプリです。架空の先生を検索するWeb画面、推定方式の比較実験、Ubuntuサーバーへの設置・更新手順を収録しています。

**学校で測ったデータや実在する教員情報は使っていません。推定対象はPCであり、先生本人の現在地を保証しません。** 現在の入力は模擬データ・CSV・公開データで、学校のAPから自動収集する機能は未実装です。

## 目的に合わせて始める

|目的|使うもの・入口|
|---|---|
|PCエリア案内を自分のPCで動かす|この`main`ブランチ。下の「ローカルで起動する」|
|Vivobookに常設する|[サーバー設置・更新ガイド](docs/SERVER.md)。Ubuntu 26.04、CPython 3.13.18、Node.js 24を使用|
|RSSIやFSMを比較実験する|このブランチ。下の「実験を再現する」|
|高校生向けのオフライン実験を行う|別の[student-labブランチ](https://github.com/suzur4/wifi-location-estimation/tree/student-lab)。HTMLを開くだけで使用可能|

FSM（有限状態機械）による表示判定は`main`に統合済みです。既定では無効で、必要に応じて有効にできます。`student-lab`は独立した教材で、サーバーの更新先は`main`です。

## ローカルで起動する

開発用にはPython 3.12とNode.js 24、Gitを用意します。Python 3.13.18もCIで検証しています。パッケージが許容するPython範囲（3.11以上3.15未満）と検証済みの版は異なります。Nodeの許容範囲は[package.json](frontend/package.json)、固定した依存は[requirements.lock](requirements.lock)と[package-lock.json](frontend/package-lock.json)を参照してください。

このリポジトリはprivateです。読み取り権限のあるGitHubアカウントでGitの認証を済ませてから取得します。以降のコマンドはリポジトリのルートで実行してください。

```bash
git clone --branch main https://github.com/suzur4/wifi-location-estimation.git
cd wifi-location-estimation
```

### macOS / Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn wifi_location.api:app --host 127.0.0.1 --port 8000 --workers 1
```

### Windows（PowerShell）

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
npm --prefix frontend ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn wifi_location.api:app --host 127.0.0.1 --port 8000 --workers 1
```

以降の`.venv/bin/python`はWindowsでは`.\.venv\Scripts\python.exe`に読み替えます。サーバーアプリのWindows実機動作は未確認です。教材のWindows CI検証とは対象が異なります。

依存の初回取得にはインターネット接続が必要です。ビルド後にサーバーを起動し、[PCエリア案内](http://127.0.0.1:8000)を開きます。[API仕様](http://127.0.0.1:8000/docs)も確認できます。停止はCtrl+Cです。フロントエンドをビルドしていない場合はAPIだけが動きます。

### 最初の操作

1. 新規DBの初回起動で架空の先生6名が登録されます。名前・よみがな・教科で検索できます。「掲示用一覧」は大きな文字の表示です。
2. 起動したターミナルの「管理画面のトークン」をコピーし、「管理（開発用）」で接続します。
3. 「模擬データを更新」で新しい測定を投入します。初期データには非公開・期限切れ・測定不足の例も含まれます。
4. 「実験データ」では保存済みの模擬実験とUJIIndoorLocの集計結果を切り替えられます。

測定は**180秒で表示期限切れ**になります。生徒画面の「今すぐ更新」はサーバーの表示を再取得する操作で、測定を新しくしません。自動取得は30秒間隔で、非表示のタブでは停止します。通信が止まっても、画面側の鮮度判定で古いエリアを隠します。

管理トークンは未設定なら起動ごとに生成され、ブラウザではメモリ内だけに保持されます。再読み込み後は再入力してください。固定する場合は`WIFI_ADMIN_TOKEN`に空白を含まない半角英数字・記号の十分長い値を指定します。16文字未満では警告が出ます。常設サーバーの秘密の保存方法は[設置ガイド](docs/SERVER.md)に従ってください。

### 開発時の画面更新

バックエンドを8000番で動かしたまま、別ターミナルで`npm --prefix frontend run dev`を実行し、表示されたURLを開きます。Viteが`/api`を8000番へ転送します。

## FSMを試す

FSMは、新しい観測で同じ候補を連続して確認してからエリアを表示します。候補変更・確認中・期限切れでは場所を隠し、非公開の設定を最優先にします。起動中のサーバーを停止してから、macOS / Linuxでは次のように起動します。

```bash
WIFI_FSM_ENABLED=1 WIFI_FSM_CONFIRMATIONS=3 \
  .venv/bin/python -m uvicorn wifi_location.api:app --host 127.0.0.1 --port 8000 --workers 1
```

PowerShellでは`$env:WIFI_FSM_ENABLED = '1'`、`$env:WIFI_FSM_CONFIRMATIONS = '3'`を設定して通常の起動コマンドを実行します。`/api/config`の`fsm.enabled`が`true`であることを確認できます。

確認回数が3なら、同じ候補を支持する新しい観測が3回必要です。画面の再取得や同じ観測の再送では回数は増えません。「模擬データを更新」は毎回異なる観測を生成するため、3回押しても候補が変わると未確定になります。状態はプロセスのメモリ内にあり、再起動すると未確定に戻ります。**1ワーカーで運用してください。** 無効に戻すには`WIFI_FSM_ENABLED=0`で再起動します。

[FSMの設定・状態遷移](docs/FSM_DESIGN.md)に詳しい仕様と設定値を、[FSMの結果](docs/FSM_RESULTS.md)に誤表示・位置不明・待ち時間の比較を記載しています。模擬実験では誤表示が減る一方で、位置不明と表示待ち時間が増えました。Webにはカルマンフィルタの時系列処理を組み込んでいません。

## 保存先とアクセス設定

|設定|既定値・意味|
|---|---|
|`WIFI_DB_PATH`|`data/demo.sqlite3`。教員情報、設定、教員ごとの最新観測を保存|
|`WIFI_RETENTION_SECONDS`|`3600`秒。保持期間を過ぎた観測を起動時・一覧取得時・1分ごとの処理で削除。180秒の表示期限とは別|
|`WIFI_ADMIN_TOKEN`|未設定なら起動時に生成。管理APIのBearerトークン|
|`WIFI_ALLOWED_HOSTS`|`127.0.0.1,localhost,[::1]`。許可するHost名の一覧。ネットワークの接続元制限とは別|
|`WIFI_FSM_ENABLED`|`0`。`1`でFSMを有効化。その他のFSM設定は[設計書](docs/FSM_DESIGN.md)を参照|

非公開にした先生の最新観測は削除され、非公開中の測定保存も止まります。移動履歴テーブルは作りません。全員を削除しても再起動で架空データが復活することはありません。DBやログ、バックアップの扱いは[情報管理](docs/SECURITY.md)を参照してください。

生徒用APIには端末ID・AP・RSSIを返さず、研究画面には模擬・公開データの集計だけを返します。管理トークン、Host検査、入力検査などは実装済みです。学校の本人認証・役割管理・同意管理は未実装であり、実測データで運用するには[学校への確認事項](docs/SCHOOL_QUESTIONS.md)の合意が必要です。

## Vivobookをサーバーにする

対象はASUS Vivobook 16 V3607VU（Intel Core 7 240H、16GB、RTX 4050 6GB、Realtek 8852BE）、指定OSはUbuntu Server 26.04 LTS、アプリ用PythonはCPython 3.13.18です。OS標準Pythonとアプリ用Pythonを分け、systemdで単一プロセスを起動します。Ubuntu 24.04 / Python 3.12の設置経路もあります。

[サーバー設置・更新ガイド](docs/SERVER.md)の順に、管理PCから`deploy/`を転送し、専用の読み取り専用Deploy keyをGitHubへ登録します。初回設置後はVivobook上で`sudo wifi-location-update`を実行して`main`を取得・更新できます。ガイドにはSSHトンネル、必要な場合のLAN配信、バックアップ・復元、ランタイムの更新、FSMの切り替えも記載しています。

申告されたAPはCisco AIR-AP1832I-Q-K9Cです。[ネットワーク・AP確認手順](docs/NETWORK.md)で管理方式と取得可能な情報を確認します。Vivobook実機と学校のAPでの接続試験は未実施です。

## 実験を再現する

環境構築後、リポジトリのルートで実行します。RSSIとFSMの例は`results/local-*`へ出力します。UJIのスクリプトは出力先が`results/uji/`に固定されており、保存済み結果を更新します。手元で変更した結果がある場合は、先に別の場所へ保存してください。

|実験|比較内容・保存済み結果|
|---|---|
|RSSI推定器・前処理|4 AP・6エリア、1,152観測。学習672・調整192・テスト288件。A〜Nの14条件。[方法](docs/EXPERIMENTS.md) / [結果](docs/RESULTS.md)|
|FSM|既存k-NN、連続判定、FSM、カルマン併用の5条件。学習・調整・最終評価のシードを分離。[方法](docs/FSM_EXPERIMENTS.md) / [結果](docs/FSM_RESULTS.md)|
|UJIIndoorLoc|公開データによる13種類の建物・階の分類。学校の6エリアとは独立。[データ条件](data/ujindoorloc/README.md) / [結果](results/uji/REPORT.md)|

```bash
.venv/bin/python -m wifi_location.experiments --seed 42 --output results/local-rssi
.venv/bin/python -m wifi_location.fsm_experiments --output results/local-fsm
.venv/bin/python scripts/download_uji.py
.venv/bin/python scripts/experiment_uji.py
```

各出力ディレクトリの`REPORT.md`から数値・CSV・図を確認できます。最初の2つは実ネットワークを使いません。UJIのダウンロードは公開UCIサーバーから行います。元CSVはGitに含めていないため、初回は取得が必要です。出典、CC BY 4.0の利用条件、SHA-256はデータ説明に記載しています。

パラメータを調整する場合は調整用集合だけを使い、最終テストの成績を見て設定を選ばないでください。シミュレーションや公開データの成績は、学校での精度を保証しません。

### CSVを推定器へ渡す

長形式CSVの必須列は`timestamp,area,ap_id,rssi,source,device_id,session_id`、任意列は`connected_ap`です。日時にはタイムゾーン、RSSIにはdBm値を指定します。1観測の複数APを複数行に分け、同じ日時・端末・セッション・方式でまとめます。APがない観測はAP/RSSIの両方を空欄にします。不正値・重複AP・矛盾するメタデータは行番号付きエラーになります。

上のRSSI実験を実行した後の例です。

```python
from wifi_location.sources import read_csv
from wifi_location.algorithms import Engine
from wifi_location.simulation import AP_AREAS

observations = read_csv("results/local-rssi/observations.csv")
training = [o for o in observations if o.session_id.startswith("sim-s00-")]
query = next(o for o in observations if o.session_id.startswith("sim-s01-"))
model = Engine(training, AP_AREAS, algorithm="knn", k=3)
print(model.predict(query, now=query.timestamp))
```

このオフライン例は測定時点を鮮度判定の基準にします。Webは現在時刻を使います。模擬・公開・実測を異なる`source`として区別し、異なる収集元を混ぜた学習は拒否します。Webの観測投入APIは模擬データ専用です。

## 検証する

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

FSM統合時の`cc7e3b9`では、[GitHub Actions](https://github.com/suzur4/wifi-location-estimation/actions/runs/42429938418)でPythonテスト222件、画面のテスト57件、ビルドが成功しました。Pythonは3.12と3.13.18で検証し、Ubuntu 24.04 / 26.04の使い捨てVMではsystemd起動、Web/API、権限分離、LAN配信、SQLiteのバックアップ・復元も確認しています。

現在のテスト構成、過去のブラウザ確認、未確認の実機条件は[検証記録](docs/VERIFICATION.md)を参照してください。画面のテスト件数はブラウザでの全操作の確認を意味しません。

## ドキュメントとコード

|知りたいこと|参照先|
|---|---|
|実装範囲と構成|[要件](docs/REQUIREMENTS.md)、[構成](docs/ARCHITECTURE.md)、[画面設計](docs/UI_DESIGN.md)|
|FSMの動作・設定・評価|[設計](docs/FSM_DESIGN.md)、[実験条件](docs/FSM_EXPERIMENTS.md)、[結果](docs/FSM_RESULTS.md)|
|設置と運用|[サーバー](docs/SERVER.md)、[ネットワーク](docs/NETWORK.md)、[情報管理](docs/SECURITY.md)|
|研究の根拠と残る課題|[技術調査](docs/RESEARCH.md)、[出典](docs/SOURCES.md)、[開発計画](docs/NEXT_STEPS.md)|
|提供資料と経緯|[研究メモ原文](ichikawa_subaru_wifi_location_research_memo.md)、[実装との対応](docs/MEMO_ALIGNMENT.md)、[初期設計判断](docs/IMPLEMENTATION_PLAN.md)、[2026-11-05の改善記録](docs/IMPROVEMENTS.md)|

推定器・API・FSMは`src/wifi_location/`、React画面は`frontend/src/`、Pythonテストは`tests/`、サーバー用スクリプトは`deploy/`にあります。保存済みの研究成果は`results/latest/`、`results/fsm/`、`results/uji/`で、それぞれの実行条件と一緒に管理しています。
