# 確認した一次資料

確認日: 2026-11-04。Firecrawlで公式ページ/PDFを取得。論文の数値を今回の性能へ転用しない。将来の実機接続仕様は機器の公式ドキュメントで追加確認する。

| 資料 | 確認した範囲と利用先 |
|---|---|
| [UJIIndoorLoc / UCI](https://archive.ics.uci.edu/dataset/310/ujindoorloc) | CC BY4.0、DOI、引用、520 WAP、100未検出、端末・建物・分割条件。データ説明と入力設計 |
| [UJI Dataset DOI](https://doi.org/10.24432/C5MS59) | UCIページに掲載された識別子。文献引用 |
| [RADAR / Microsoft Research](https://www.microsoft.com/en-us/research/publication/radar-an-in-building-rf-based-user-location-and-tracking-system/) | 著者・INFOCOM2000・概要。信号強度による測位の先行研究 |
| [RADAR 原論文PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/infocom2000.pdf) | 検索結果に掲載された著者表記・タイトル。PDF自体の全文検討は未実施 |
| [Horus / USENIX一次配布PDF](https://www.usenix.org/legacy/event/mobisys05/tech/full_papers/youssef/youssef.pdf) | 冒頭3ページを取得。著者、指紋、確率的手法、時間相関、当時の収集実装 |
| [Horus ACM DOI](https://doi.org/10.1145/1067170.1067193) | ACM公式検索結果で論文タイトルを確認。USENIX PDFと対応 |
| [Microsoft: Wi-Fi access/location changes](https://learn.microsoft.com/en-us/windows/win32/nativewifi/wi-fi-access-location-changes) | 位置情報同意、影響するAPI、ERROR_ACCESS_DENIED。Windows収集条件 |
| [Microsoft: WlanGetNetworkBssList](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlangetnetworkbsslist) | Native WiFiのBSS一覧取得API。ブラウザ機能と区別 |
| [RFC4188 BRIDGE-MIB](https://www.rfc-editor.org/rfc/rfc4188.html) | FDB address/port/status定義。FDBはRSSIを提供しない |
| [RFC2866 RADIUS Accounting](https://www.rfc-editor.org/rfc/rfc2866.html) | Accountingの範囲。接続記録とRSSI指紋を区別 |
| [RFC3580 IEEE802.1X RADIUS](https://www.rfc-editor.org/rfc/rfc3580.html) | §3.20/3.21 AP/端末の識別形式。実装依存性の注意 |
| [WICG Network Information API](https://wicg.github.io/netinfo/) | APIの公開フィールド。BSSID/RSSI列挙を通常ブラウザに仮定しない根拠 |
| [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) | lifespan推奨、startup/shutdown eventsとの併用不可 |
| [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) | TestClient、httpx、pytestの公式例 |
| [Vite Getting Started](https://vite.dev/guide/) | 取得時点のNode20.19+/22.12+要件。実際の固定バージョンはfrontend/package-lock.json |

Web上の仕様と、今回の設計判断は別である。学校APの対応、実機Windowsの権限状態、測位精度は未確認。利用したライブラリの正確なインストール版はロックファイル・実験条件に記録する。

## 後から提供された企画資料

[研究メモ原文（2026-11-03、暫定版Ver.0.1）](../ichikawa_subaru_wifi_location_research_memo.md)は2026-11-04の実装開始後に受領し、変更せず保存した。これはユーザー提供の企画資料で、記載された全参考文献を一次確認したという意味ではない。[現在の実装との対応・相違](MEMO_ALIGNMENT.md)を別に整理した。
