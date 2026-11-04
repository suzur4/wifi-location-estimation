# UJIIndoorLoc 公開データ

2026-11-04に[UCI公式ページ](https://archive.ics.uci.edu/dataset/310/ujindoorloc)の説明・ライセンス・引用元を確認し、公式ZIPを取得した。学校の測定データではない。

- データセットDOI: [10.24432/C5MS59](https://doi.org/10.24432/C5MS59)
- 配布元: [UCI公式ZIP](https://archive.ics.uci.edu/static/public/310/ujiindoorloc.zip)
- ライセンス: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode)。再配布・改変時は著者とデータセットへのクレジット、ライセンスへのリンク、変更点を示す。
- 引用: Joaquín Torres-Sospedra, Raúl Montoliu, Adolfo Martínez-Usó, Tomar J. Arnau, Joan P. Avariento, Mauri Benedito-Bordonau, Joaquín Huerta. “UJIIndoorLoc: A New Multi-building and Multi-floor Database for WLAN Fingerprint-based Indoor Localization Problems.” IPIN, 2014。著者表記はUCIの引用欄に従う。
- 収集条件: 2013年、Universitat Jaume Iの3建物、4階以上、約110,000㎡、20人以上・25種類のAndroid端末。学校Windows PCの条件ではない。
- 公式分割: `trainingData.csv` 19,937行、`validationData.csv` 1,111行。公式のvalidation/testを最終評価に使う場合、モデルや閾値の調整はtraining内部の別分割で行う。
- 520個の`WAP001`〜`WAP520`はRSSI特徴。`100`はAP未検出であり強い受信値ではない。実RSSIは-104〜0 dBm。
- 他の列: LONGITUDE, LATITUDE, FLOOR, BUILDINGID, SPACEID, RELATIVEPOSITION, USERID, PHONEID, TIMESTAMP。座標は掲載値を勝手に緯度経度として地図へ描かない。元データのPHONEID等を実在する教員情報に結び付けない。

今回のローダーはBUILDINGID/FLOORを粗いエリアラベルにし、100を観測辞書から除外する。各行を独立セッションとして扱い、並んだ行を移動軌跡や連続測定と仮定しない。UJIのAP側/端末側の指紋と、学校の指紋や模擬指紋は同じ学習集合へ混ぜない。

`python scripts/download_uji.py`で再取得できる。取得日時・サイズ・SHA-256は`download.json`に記録した。最初のsandbox内取得はDNS解決に失敗したが、公開配布元へのネットワーク許可で再実行し成功した。TLS検証を無効化していない。CSVは約43MBあるため、共有リポジトリではデータ本体を除外し、スクリプトと引用情報を配ることを推奨する。

## 今回確認した読み込み

Python 3.12のプロジェクト仮想環境で`load_uji`を両方の実CSVに実行した。training 19,937観測/検出RSSI 358,763値、validation 1,111観測/検出RSSI 18,304値、両方13 building/floorクラスとして読み込めた。100が観測RSSIに含まれないこと、各行のセッションIDが異なることをassertで確認した。この取り込み確認自体は分類精度の評価ではない。
