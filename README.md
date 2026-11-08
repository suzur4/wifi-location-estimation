# Wi-Fi位置推定 実験ラボ — 高校生向け教材

この `student-lab` ブランチは、仮想の電波データで位置推定の考え方を学ぶ教材の配布・開発用です。ブラウザで開く実験A〜E、6つの学習教材、記録用ワークシート、先生・進行役向け資料を収録しています。データはすべて模擬値で、実在する教員の位置や学校の測定値は扱いません。

## 始める

1. ZIPで受け取った場合は、フォルダー全体を展開します。
2. このリポジトリを取得した場合は、`student-lab/index.html` をダブルクリックします。教材専用の配布ZIPでは、展開先の `README.md` と同じフォルダーにある `index.html` を開きます。
3. 「実験A」のスライダーを1つ動かし、推定が変わることを確かめます。
4. [生徒向け操作ガイド](student-lab/README.md)に沿って、予想・条件・結果を記録します。教材とワークシートは同じフォルダーの `materials.html` で閲覧・印刷できます。

利用にはEdgeやChromeなどのブラウザを使います。Python、Node.js、npm、管理者権限、インターネット接続は不要です。GitHub上のHTMLはソース表示になるため、ファイル一式を取得してから開いてください。学校PCでは、ローカルHTMLの閲覧・CSV保存・印刷が許可されていることを授業前に確認します。

## 学べることと資料

|目的|入口|
|---|---|
|RSSI、平均・中央値、AP数、推定方式、判定条件を比べる|[生徒向け操作ガイド](student-lab/README.md)|
|Wi-Fi・実験計画・データ分析・プログラミングを学ぶ|[教材1](student-lab/docs/01_WIFI_BASICS.md)から[教材4](student-lab/docs/04_PROGRAMMING.md)|
|カルマンフィルタと有限オートマトンの役割を学ぶ|[教材5](student-lab/docs/05_KALMAN_AND_FSM.md)|
|他の課題に応用する、HTMLの判定関数を編集する|[教材6](student-lab/docs/06_APPLICATIONS.md)・[発展演習](student-lab/exercises/CHANGE_A_RULE.md)|
|班の予想・結果・考察を残す|[実験記録](student-lab/worksheets/EXPERIMENT.md)・[振り返り](student-lab/worksheets/REFLECTION.md)・[発表](student-lab/worksheets/PRESENTATION.md)|
|授業を準備・進行する|[活動概要](student-lab/teacher-guide/OVERVIEW.md)・[60分案](student-lab/teacher-guide/SESSION_PLAN.md)・[よくある質問](student-lab/teacher-guide/FAQ.md)|

実験C・Dは同じシナリオとシードの模擬観測を使い、条件をそろえて比較できます。計算や判定ルールは学習用に簡略化されています。模擬結果から実際の学校での精度は判断できません。

## 配布と開発

配布するのは `student-lab/` 一式です。`index.html`、`materials.html` と資料の位置関係を保ってください。配布先ではサーバーの起動や依存パッケージの導入は行いません。

開発者の確認にはNode.js 24を使用します。リポジトリのルートで次を実行すると計算モデルの11テストを確認できます。

```bash
node --test student-lab/tests/model.test.mjs
```

Windows・UbuntuのCIで、モデルの11テストと、通信を無効にしたChromiumでの `file://` 操作確認が合格しています。確認した操作、開発者用Playwrightの導入・実行方法、学校実機で未確認の項目は[検証記録](student-lab/docs/VERIFICATION.md)を参照してください。[対応するCI実行](https://github.com/suzur4/wifi-location-estimation/actions/runs/42371103360)

教材のMarkdownを修正するときは、`student-lab/materials.html` に埋め込まれた同じ資料も更新し、表示と印刷対象の切り替えを確認します。

## サーバーアプリ・研究実験を使う場合

教員PCエリア案内Webアプリ、Pythonによる比較実験、FSMの統合実装は `main` ブランチで管理しています。このブランチに残る本体コード・文書は、最新の運用手順として使わず、以下の `main` の資料を参照してください。

- [mainのREADMEと起動方法](https://github.com/suzur4/wifi-location-estimation/blob/main/README.md)
- [Vivobook・Ubuntuサーバー設置ガイド](https://github.com/suzur4/wifi-location-estimation/blob/main/docs/SERVER.md)
- [WebアプリのFSM設計・有効化](https://github.com/suzur4/wifi-location-estimation/blob/main/docs/FSM_DESIGN.md)
- [FSM比較実験の手順](https://github.com/suzur4/wifi-location-estimation/blob/main/docs/FSM_EXPERIMENTS.md)

この教材の学習用モデルは本体のPython推定エンジンとは別実装です。教材を開くだけで学校APへの接続や測定値の収集が始まることはありません。
