# 実験ラボの確認記録

配布用アプリは `index.html`、教材の閲覧・印刷は `materials.html`。この文書は確認済みの環境・操作と再確認手順を示す。下記の開発用ツールは、配布先で使うための前提ではない。

## 確認済みの環境

`student-lab` ブランチの基準版 `a4befe0` では、GitHub ActionsのUbuntu・Windowsの両ジョブが成功した。モデルの11テストに加え、Chromiumを通信無効で起動し、アプリと教材を `file://` で直接開いて操作している。[CI実行42371103360](https://github.com/suzur4/wifi-location-estimation/actions/runs/42371103360)

|環境|確認内容|結果|
|---|---|---|
|GitHub Actions・Ubuntu 24.04・Node.js 24|モデル11テスト、オフラインChromiumでのブラウザ確認|合格|
|GitHub Actions・Windowsホスト（`windows-latest`）・Node.js 24|モデル11テスト、オフラインChromiumでのブラウザ確認|合格|
|macOS・Chromium 151.0.7922.34（2026年11月8日に再確認）|`file://` でのオフライン操作、狭い画面、教材と印刷対象|確認済み|

Windowsの結果はCIホスト上の自動検証であり、学校の管理対象PCや通常のEdge画面での検証を意味しない。最新コミットの結果は[Offline student labの実行一覧](https://github.com/suzur4/wifi-location-estimation/actions/workflows/student-lab.yml)で確認する。

## 確認した操作

計算モデルと、ネットワーク無効でのブラウザ検査で、次の操作・判定・表示を確認した。

- Aのスライダーで最強AP・推定が変わり、初期値に戻る。
- Bで編集した値から平均・偶数個の中央値・標準偏差が計算される。範囲外・不正値はエラーとなり、前の結果を新しい結果として残さない。
- CでAPごとのON/OFFと全欠損を比較できる。シード・シナリオをそろえたリセットで同じ値と結果に戻る。
- Dで同一データの最強AP・AP別平均・簡易フィンガープリントを切り替えられる。
- Eで定数の変更が結果を変え、見本に戻る。実ファイルの小関数を編集した場合もモデルの結果が変わることを数値テストで確認した。
- 日本語の予想・結果メモを含むCSVを、ローカルへダウンロードできる。画面のコピー用CSVと内容が一致する。
- 1280pxと375px幅で表示を確認した。全実験の375px幅でページ全体の横方向のはみ出しはなかった。
- 教材の日本語表示、ワークシート3種・1種の印刷対象切替を確認した。HTML・JavaScriptからのHTTP/HTTPSリクエストは0件。

計算モデルの11テストでは、大小・同値、偶数個中央値、標準偏差、再現シード、AP欠損、距離・候補差、Eのソース編集と復元、Windows形式の改行、CSVの引用符と式風文字列の扱いを確認する。EはCRLFのソースと貼り付け入力もテスト対象に含む。

## 開発者が再確認する方法

Node.js 24とnpmを用意し、`student-lab/` が見えるリポジトリのルートで実行する。配布ZIPだけを使う生徒にはこの準備は不要。数値テストのコマンドはmacOS・Linux・Windows共通である。

```bash
node --test student-lab/tests/model.test.mjs
```

成功時は `tests 11`、`pass 11`、`fail 0` と表示される。ブラウザの再確認には、開発者の環境だけにPlaywright 1.65.0とChromiumを導入する。初回の依存取得にはネットワーク接続が必要だが、ブラウザ確認中はスクリプトが通信を無効にする。`.cache/lab-qa` は配布する `student-lab/` の外に置く。

### macOS・Linux

```bash
npm install --prefix .cache/lab-qa --no-audit --no-fund playwright@1.65.0
node .cache/lab-qa/node_modules/playwright/cli.js install chromium --only-shell
PLAYWRIGHT_MODULE=.cache/lab-qa/node_modules/playwright/index.mjs node student-lab/tests/offline-browser.mjs
```

Linuxでブラウザ用のOSライブラリが不足する場合は、開発端末の管理者権限で `node .cache/lab-qa/node_modules/playwright/cli.js install --with-deps chromium --only-shell` を実行してから再確認する。CIではこのオプションで依存も導入している。

### Windows PowerShell

```powershell
npm.cmd install --prefix .cache/lab-qa --no-audit --no-fund playwright@1.65.0
node .cache/lab-qa/node_modules/playwright/cli.js install chromium --only-shell
$env:PLAYWRIGHT_MODULE = (Resolve-Path .cache/lab-qa/node_modules/playwright/index.mjs).Path
node student-lab/tests/offline-browser.mjs
```

ブラウザ確認に成功するとJSONが表示され、`offline` と `fileProtocol` が `true`、`remoteRequests` が `0` になる。Windows上では `windowsTested` も `true` になる。途中で検査に失敗した場合は、最初のエラーと失敗した操作を確認する。ブラウザ確認は通常のプリンターへの出力までは行わない。

## 当日の端末で確認する項目

学校のWindows実機、管理ポリシー、通常のEdge画面、物理プリンターは未検証。授業前に配布フォルダーを展開し、JavaScriptの動作、ローカルファイルの閲覧、CSV保存または紙への記録、必要なワークシートの印刷を実際の端末で確認する。使用端末の制限がある場合は教材の紙の代替手順を使う。
