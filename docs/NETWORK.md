# AP情報取得方式の比較と実機接続の準備

現在、学校の管理権限・機器情報・許可は提供されていない。実装が使うのは模擬・CSV・公開データのみである。本書のネットワーク方式は将来のアダプター設計であり、接続済みを意味しない。

## 取得の向きが違う

PCが測る「周囲の複数APの下りRSSI」と、APが測る「接続PCの上りRSSI」は別の特徴量である。送信電力、アンテナ、帯域、接続状態が異なるので、同じモデルへ混ぜない。SNMPのFDBやRADIUSは接続の手がかりであり、複数APのRSSI指紋を必ず得られるわけではない。

SSIDはネットワーク名、BSSIDは無線BSSの識別子である。同じSSID/LANでも、BSSIDまたはコントローラーのAP IDと設置エリアの対応を管理すれば識別できる。ただし1台の物理APが帯域・SSID別に複数BSSIDを持つ場合や、AP交換でIDが変わる場合があるため、物理AP・無線機・BSSを区別した台帳が必要となる。

| 方式 | 得られる可能性のある情報 | RSSI | 追加ソフト | 条件・注意 |
|---|---|---|---|---|
| AP管理API | クライアント、接続AP、時刻、機種によってRSSI | 製品依存。多くはAP側受信値 | 教員PCには不要な候補 | API/契約/スコープ/レート制限/対象AP/時刻の意味を確認 |
| SNMP FDB | MACからbridge portへの対応、状態 | BRIDGE-MIBのFDBにはない | PCには不要 | ポートがAP直結か、上位スイッチか、トンネル終端かを要確認 |
| RADIUS Accounting | セッション開始・終了・更新、NAS識別子、実装によりCalled-Station-Id等 | 標準の指紋RSSIとして期待しない | PCには不要な候補 | 802.1X/Accounting有効化、更新頻度、ローミング時の挙動が必要 |
| Windows Native WiFi | BSSIDとRSSIなどのBSS情報 | PC側で取得可能 | スクリプト/アプリ/管理配布等が必要 | Windows版・位置情報同意・ポリシー・ドライバの確認が必要 |
| CSV | 許可を得て測った情報の共通入力 | ファイルに含む場合のみ | 収集方法による | エリア正解・日時・方式・仮名端末/セッションIDを明記 |
| シミュレーション | 仮想AP・仮想RSSI・正解ラベル | 完全な模擬値 | 不要 | 学校性能の証拠にはならない |

## 標準文書から確認できたこと

[RFC 4188](https://www.rfc-editor.org/rfc/rfc4188.html)の`dot1dTpFdbAddress`はMAC、`dot1dTpFdbPort`はその送信元フレームを観測したbridge portである。0は未学習の可能性がある。そこに無線RSSIは定義されていない。FDBから所在を求めるには管理者が確認したトポロジーとAP接続ポート対応が必要で、コントローラー集約構成などではAPまで絞れない可能性がある。RSSI用のメーカー固有MIBがあっても別能力として扱う。

[RFC 2866](https://www.rfc-editor.org/rfc/rfc2866.html)はRADIUS Accountingを定義する。[RFC 3580 §3.20/3.21](https://www.rfc-editor.org/rfc/rfc3580.html#section-3.20)はCalled-Station-IdにAP/bridgeのMACと、既知ならSSID、Calling-Station-Idに端末MACを使う形式を示す。実装の出力内容と鮮度は別途確認する。認証・Accountingログだけから現在の周囲RSSIを復元できるとは仮定しない。

[MicrosoftのWlanGetNetworkBssList](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlangetnetworkbsslist)はBSS一覧取得のNative APIである。[位置情報アクセスの変更](https://learn.microsoft.com/en-us/windows/win32/nativewifi/wi-fi-access-location-changes)では、位置情報への同意がなければ対象APIが`ERROR_ACCESS_DENIED`等を返すことが説明されている。実機のOS版と学校のポリシーを確認する。

ブラウザ向け[Network Information API仕様](https://wicg.github.io/netinfo/)が公開するのは接続種類や推定帯域・RTT等であり、BSSIDやAPごとのRSSIの列挙APIは含まれない。この仕様範囲に基づき、本プロジェクトでは通常ブラウザ単体によるWi-Fi指紋収集を前提にしない。Geolocationで位置を得られても、校内エリアのRSSI測定とは別である。

## 将来アダプターの契約

推定器へ渡す前に、各アダプターは共通`Observation`へ変換する。`source`を`ap_api:<vendor>:uplink`、`windows_native:downlink`など方向を含めた別名にする案である。接続APしか分からない場合はRSSIを作らず、`readings={}`と`connected_ap`を用いて接続AP方式だけに渡す。取得不能や古い値は`unknown`へ伝播させる。

設定の提案（未実装であり有効な認証情報ではない）:

```yaml
network:
  enabled: false
  mode: ap_api  # snmp_fdb / radius_export / windows_native
  allowed_hosts: []
  poll_seconds: 60
  max_age_seconds: 180
  credentials_env: WIFI_CONNECTOR_SECRET
  source_direction: uplink
```

| モード | 設定項目 | 必要権限・対応条件 |
|---|---|---|
| ap_api | HTTPS base URL、対象サイト/AP ID、認証方式、読み取りscope、タイムアウト、ページング | 管理者が許可した読み取り専用API資格。メーカー公式仕様とRSSI単位の確認 |
| snmp_fdb | 対象ホスト、SNMPv3 user、auth/priv方式、秘密の環境変数名、VLAN/context、MIB/OID | 管理者が許可した最小read view。ポート/AP台帳、FDB agingの把握。v1/v2cのcommunityをコードへ保存しない |
| radius_export | 許可済みエクスポートファイル/連携先、NAS/AP対応、属性名、更新間隔 | RADIUS管理者の許可、必要項目のみを仮名化した抽出。サーバー全ログを取り込まない |
| windows_native | OS版、インターフェース指定、測定周期、同意状態、仮名端末ID | 学校と本人の許可、位置情報同意、管理配布方針。無断実行しない |

明示設定だけで権限が得られるわけではない。学校の承認・本人同意と対象ホストのallowlistを別途確認する。ネットワーク機能を実装する時も既定値は無効とし、曖昧な設定で自動探索しない。

## 許可後の小規模PoC手順

1. 管理者から許可された実験用AP/PCと区域を1つ選び、実験ID・期間・削除日を決める。
2. APのAPI/ログ/FDBで接続先のみ判定できるか確認する。指紋に必要な観測が取れなければ、方式を切り替えて理由を記録する。
3. 固定地点で複数端末・複数日時の匿名測定を取り、端末を動かさず静止セッションを区切る。
4. 正解エリアを人手記録し、学習/検証/最終テストを端末または日時で分離する。
5. 非公開、スリープ、切断、ローミング、未登録AP、障害、期限切れを試す。最後に取得情報を削除する。
6. 誤表示率と不明率、管理負担を学校側と確認し、本番可否を別途判断する。
