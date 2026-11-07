# 実験ラボの確認記録

2026年11月7日。配布用アプリは `index.html`、教材の閲覧・印刷は `materials.html`。下記の開発用ツールは、配布先で使うための前提ではない。

## 確認した操作

macOS上のChromium 151.0.7922.34で、ネットワーク無効のブラウザ環境から `file://` で直接開いた。

- Aのスライダーで最強AP・推定が変わり、初期値に戻る。
- Bで編集した値から平均・偶数個の中央値・標準偏差が計算される。範囲外・不正値はエラーとなり、前の結果を新しい結果として残さない。
- CでAPごとのON/OFFと全欠損を比較できる。シード・シナリオをそろえたリセットで同じ値と結果に戻る。
- Dで同一データの最強AP・AP別平均・簡易フィンガープリントを切り替えられる。
- Eで定数の変更が結果を変え、見本に戻る。実ファイルの小関数を編集した場合もモデルの結果が変わることを数値テストで確認した。
- 日本語の予想・結果メモを含むCSVを、ローカルへダウンロードできる。画面のコピー用CSVと内容が一致する。
- 1280pxと375px幅で表示を確認した。全実験の375px幅でページ全体の横方向のはみ出しはなかった。
- 教材の日本語表示、ワークシート3種・1種の印刷対象切替を確認した。HTML・JavaScriptからのHTTP/HTTPSリクエストは0件。

計算モデルの10テストでは、大小・同値、偶数個中央値、標準偏差、再現シード、AP欠損、距離・候補差、Eのソース編集と復元、CSVの引用符と式風文字列の扱いを確認した。

## 開発者が再確認する方法

リポジトリ直下で、数値テストは次のコマンドで実行する。

```bash
node --test student-lab/tests/model.test.mjs
```

ブラウザの再確認には、開発者の環境だけにPlaywright 1.65.0とChromiumを導入する。配布物へ依存フォルダーを入れない。

```bash
npm install --prefix .cache/lab-qa --no-audit --no-fund playwright@1.65.0
node .cache/lab-qa/node_modules/playwright/cli.js install chromium --only-shell
PLAYWRIGHT_MODULE=.cache/lab-qa/node_modules/playwright/index.mjs node student-lab/tests/offline-browser.mjs
```

GitHub ActionsではUbuntuとWindowsのホストで同じテストを実行する。ブランチのチェック結果を確認する。[Offline student lab の実行結果](https://github.com/suzur4/wifi-location-estimation/actions/workflows/student-lab.yml)

## 当日の端末で確認する項目

学校のWindows実機、管理ポリシー、通常のEdge画面、物理プリンターは未検証。授業前に配布フォルダーを展開し、JavaScriptの動作、ローカルファイルの閲覧、CSV保存または紙への記録、必要なワークシートの印刷を実際の端末で確認する。使用端末の制限がある場合は教材の紙の代替手順を使う。
