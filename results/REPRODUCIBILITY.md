# 再現性確認

2026-11-04、同じseed=42で2回実行。observations.csvとpredictions.csvがバイト単位で一致。14条件すべての正解率・誤表示率・不明率・表示正答率・理由別件数・選択閾値が一致した。推定時間と生成時刻は比較対象外。1-NNの同距離競合判定修正後も予測結果は一致。

観測SHA256: `f5c7adb0e5be1a1bbdb4c439a97a9beb6a1b795402c158c066b3ad75376c2407`

## アンカー三辺測位の比較

2026-11-23、シード42〜46で`python -m wifi_location.trilateration_experiments`（三辺測位・予測＋補正・一致表示と切り分け2種）を同じmacOS環境で2回実行。`metrics.csv`・`metrics_by_seed.csv`・`REPORT.md`・`summary.json`がバイト単位で一致した。OSや数値ライブラリが違うと浮動小数の最下位桁が変わりうるため、別環境では小数第6位程度までの一致を目安とする。`simulation.generate`に環境変化の引数を加えたが、場所ごとの影響（`shadowing_db`）は別の乱数列を使うため、既定値での`generate(42)`の出力は変更前と同一（`tests/test_trilateration.py`で、受信APの並び・ラベルは完全一致、RSSIは許容誤差付きで確認）。
