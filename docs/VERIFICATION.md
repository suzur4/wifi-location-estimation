# 検証範囲と再確認手順

現行 `main` の検証と、過去の版で行った確認を分けて記録する。以下の最新CIは、FSMを統合したコミット [`cc7e3b9`](https://github.com/suzur4/wifi-location-estimation/commit/cc7e3b90c5524f7ac48b1253ac993bfd20ad50b2) が対象である。試験には模擬データと公開研究データを使い、学校ネットワークや実在教員の情報は使っていない。

## 現行mainの自動検証

[GitHub Actions実行 42429938418](https://github.com/suzur4/wifi-location-estimation/actions/runs/42429938418) は全5ジョブ成功。定義は [checks.yml](../.github/workflows/checks.yml) にある。

|環境・対象|結果|確認した範囲|
|---|---|---|
|Ubuntu 24.04 / Python 3.12|222件成功、警告1件|推定・入力・API・FSM・実験・配備スクリプトの回帰試験、依存整合性|
|Ubuntu 26.04 / Python 3.13.18|222件成功、警告1件|同じPython試験と依存整合性|
|Node 24 / フロントエンド|57件成功、本番ビルド成功|Vitest/jsdomによる画面操作・通信・鮮度判定、TypeScript検査、Viteビルド|
|Ubuntu 24.04 / systemd配備|成功|リリース作成、サービス起動・再起動、DB保持・バックアップ復元、LANアクセス制限|
|Ubuntu 26.04 / systemd配備|成功|公式CPython 3.13.18のソースビルドと、その実行環境による同じ配備試験|

Pythonの警告はStarlette/httpxのテストクライアント互換性に関する将来廃止警告。試験失敗ではないが、依存更新時の確認対象とする。

### 自動検証で扱う契約

- **推定と研究データ**：欠測・未登録AP・競合候補・非有限値・古い時刻、CSVの重複列や列数不一致、学習/検証/テストの分離、未来の測定を使わない前処理、評価指標の分母。
- **APIと保存**：管理認証、Host検査、本文上限、生徒APIの公開項目、非公開時の観測削除・受信拒否、保存の原子性、保持期間、旧DB移行、設定の再起動後保持。
- **FSM**：候補変更時の旧エリア非表示、必要回数・既知AP数・支持差、180秒境界、GETで回数を増やさないこと、同時刻/逆順観測、未来時刻、非公開の優先、設定変更・再起動・別DB接続更新による証拠の破棄、一括更新失敗時の整合性。無効時の従来動作も確認する。
- **画面**：名前・よみがな・教科検索、非公開情報の抑制、通信停止中の鮮度失効、遅れた応答の無視、管理トークンのメモリ保持、操作後のフォーカス、保存済み処理の誤再送防止。

配備試験は使い捨てのGitHubホストVM上で実際のsystemdユニットを動かす。[試験スクリプト](../.github/scripts/check-server.sh) はWebサービスの実行Python、更新後のDB保持、SQLiteバックアップ/復元、Web実行ユーザーが配備鍵を読めないことも確認する。LAN用nginxでは生徒向けGETが通り、管理・研究API、書き込み、許可外の送信元が拒否されることをHTTPで検査する。

このCIではGitHubの代わりにローカルGitリモートを使い、LANもVM内の試験用インターフェースを使う。Vivobook実機の起動・無線・温度管理、実際のGitHub Deploy Key登録、校内LANとの接続を確認したものではない。

## 自分の環境で再確認する

[README](../README.md) の環境構築後、リポジトリ直下で実行する。

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

実験の再実行は [基本実験](EXPERIMENTS.md) と [FSM比較実験](FSM_EXPERIMENTS.md)、サーバー構成の確認は [サーバー構築](SERVER.md) を参照する。既存の結果を上書きせず別の出力先で比較し、実行時間と決定的な評価値を区別する。`.github/scripts/check-server.sh` は破棄可能なCIホスト専用であり、普段使うPCや稼働中のサーバーで実行しない。

実ブラウザでは、架空データの一覧・管理操作・FSMの確認待ちから確定への変化、通信を止めた状態での180秒経過、非公開への切り替え、スマートフォン幅、キーボード操作を確認する。**FSM統合後のmainに対する実ブラウザ通し操作は未実施**。上表のフロントエンド試験はjsdom、配備試験はHTTP検査であり、これを代替したとは扱わない。

## 実験結果と教材の検証を区別する

|対象|保存した証拠|適用範囲|
|---|---|---|
|基本の模擬実験 A〜N、UJIIndoorLoc|[結果](RESULTS.md)、[再現性確認](../results/REPRODUCIBILITY.md)、[2026-11-05の再実行比較](verification/improvement-regression.json)|模擬seed42の予測4,032行・観測CSVは再実行で一致。UJIを含む指標も実行時間を除き一致。学校での性能ではない|
|FSMの5方式比較|[条件](FSM_EXPERIMENTS.md)、[結果](FSM_RESULTS.md)、[出力](../results/fsm/REPORT.md)|学習・調整・評価シードを分離。最終評価は各方式3,510イベント。FSMと単純連続判定の表示結果は一致し、FSM固有の精度優位性は確認していない|
|独立教材 `student-lab`|コミット [`a4befe0`](https://github.com/suzur4/wifi-location-estimation/commit/a4befe017985da27fb7fd2a745bf46de66efd8bc)、[教材CI 42371103360](https://github.com/suzur4/wifi-location-estimation/actions/runs/42371103360)|Windows/UbuntuのChromiumで `file://`・オフライン操作を確認。モデル試験、A〜E比較、CSV、リセット、375px幅、日本語教材、印刷選択を検査。mainのWebアプリや学校Windows実機の検証ではない|

`student-lab` は別ブランチの教材であり、mainのテスト件数へ加算しない。

## 未確認の範囲

Vivobook実機（Realtek無線・スリープ復帰・発熱を含む）、Cisco APの管理方式と収集連携、学校のWindows PC・管理下ブラウザ・実プリンター、実在教員を使うPoC、長時間負荷、実際の利用者による視認性・読み上げソフトの確認は未実施。本番認証・権限・TLS・運用の受入れも未完了である。[未解決課題](NEXT_STEPS.md) と [学校への質問](SCHOOL_QUESTIONS.md) に進め方をまとめる。

## 過去の版での確認

以下は当時の版に対する記録であり、現行版を同じ条件で再試験したことを示さない。変更前の再現手順、変異テスト、旧ブラウザ操作の詳細は [改訂前の記録](https://github.com/suzur4/wifi-location-estimation/blob/cc7e3b90c5524f7ac48b1253ac993bfd20ad50b2/docs/VERIFICATION.md) に残している。

|日付|記録|
|---|---|
|2026-11-04|macOS / Python 3.12.14 / Node 24.21.0。初期64件・画面15件、その後113件・画面43件が成功。ビルド済み画面をFastAPIで配信し、検索・登録・非公開・研究画面・掲示表示・390px/375px幅を実ブラウザで確認|
|2026-11-05 品質改善|Python 131件・画面53件とビルド成功。模擬/UJIの再実行比較を保存。この日の実ブラウザ確認はローカルURLのアクセス許可が拒否されたため中止。これは過去の実行制約であり、現在の検証を妨げているという意味ではない|
|2026-11-05 入力・鮮度修正|Python 142件・画面54件とビルド成功。巨大Content-Length、CSV列、管理一覧の鮮度境界を修正。npm監査と固定Python依存39件のpip-auditで、当日の登録情報に基づく既知脆弱性0件|

2026-11-04の最終画面写真：[一覧](screenshots/directory-plain.jpg)・[掲示](screenshots/display-plain.jpg)・[研究](screenshots/research-plain.jpg)・[管理](screenshots/admin-plain.jpg)・[モバイル](screenshots/mobile-plain.jpg)。すべて当時の架空データであり、現在の測定やFSM統合後の画面証拠ではない。

専用セキュリティ診断は2026-11-05に確定した（scan ID `c29d7c33-b0f9-4d78-ab2c-e26b9247e78a`）。対象は修正前コミット `58f5772baeaef30c300bc236ea7bbd0cb1c2bfe8`。独立レビューworkerが利用上限で完了せず、親による主要コードの確認に切り替えた。確認済み4領域の報告対象は0件だが、補助文書・全テスト・過去成果物の網羅的精査は未完了のため `partial` である。レポート・脅威モデル・範囲JSONはCodex Securityの診断成果物に保存した。

修正コミット `96ab942e599925234f704d89ab1f5019aafdd713` の回帰試験・依存監査、今回のmainのCI成功は、それぞれ別の証拠である。過去の部分診断を現行コード全体の再診断として扱わない。実装上の制御と運用条件は [情報管理とプライバシー](SECURITY.md) を参照する。
