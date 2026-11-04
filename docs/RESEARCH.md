# 技術調査と研究上の位置づけ

確認日: 2026-11-04。以下は一次資料の内容と、今回の提案を分けた記録である。文献の位置推定精度を学校での性能として引用しない。

## 確認した文献

- Paramvir Bahl and Venkata N. Padmanabhan, “RADAR: An In-Building RF-based User Location and Tracking System”, IEEE INFOCOM, 2000。著者の[Microsoft Research掲載ページ](https://www.microsoft.com/en-us/research/publication/radar-an-in-building-rf-based-user-location-and-tracking-system/)と[論文PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/infocom2000.pdf)。複数基地局の信号強度の測定と電波伝搬モデルを組み合わせる研究である。掲載ページでは現在の著者名表記がVictor Bahl / Venkat Padmanabhanになっている。今回のプロジェクトはエリア分類だけを行い、文献タイトルにある追跡機能を実装しない。
- Moustafa Youssef and Ashok Agrawala, “The Horus WLAN Location Determination System”, MobiSys, 2005。[USENIX一次配布PDF](https://www.usenix.org/legacy/event/mobisys05/tech/full_papers/youssef/youssef.pdf)、[ACM DOI 10.1145/1067170.1067193](https://doi.org/10.1145/1067170.1067193)。確認した冒頭3ページでは、オフラインの電波指紋とオンラインの照合、RSSI分布を使う確率的方法、時間変動と連続サンプルの相関を説明している。Windowsの実装には独自NDISドライバを使っており、この論文から現行Windowsでブラウザのみの収集が可能とは結論できない。
- Joaquín Torres-Sospedra et al., “UJIIndoorLoc: A New Multi-building and Multi-floor Database for WLAN Fingerprint-based Indoor Localization Problems”, International Conference on Indoor Positioning and Indoor Navigation (IPIN), 2014。[UCI公式ページ](https://archive.ics.uci.edu/dataset/310/ujindoorloc)、データセットDOI [10.24432/C5MS59](https://doi.org/10.24432/C5MS59)。複数建物・複数階を含む比較用データを提供する。詳細な利用条件は[data/ujindoorloc/README.md](../data/ujindoorloc/README.md)。

## 今回の仮説と実装

RSSI指紋は「各APがどの程度強く見えるか」を並べた特徴である。似た指紋を持つ既知エリアを探す。1-NNは最も近い1測定、k-NNは近いk測定の投票、距離重み付きk-NNは近い測定に大きな票を与える。欠測は固定値で表すが、共通して観測したAP数も確認する。欠測パターンや端末オフセットだけで誤分類する可能性があり、独立評価が必要である。

順位方式はAPの強さの順序を比較する。全APに同じオフセットが加わる場合には強さの順序が変わりにくいという仮説がある。一方、AP数が少ないと異なるエリアでも同じ順位になる。ガウス型分類はエリア・APごとに平均と分散を推定し、AP間を独立と仮定して相対スコアを計算する。Horusの全機能の再現ではなく、確率モデルの単純な比較対象である。校正していないため「95%の確率で正しい」などとは表示しない。

接続APと最強APは機器対応や学習コストの低い基準である。4APで6エリアを分類すると、APに割り当てたエリア以外の判定が困難になる。複数階へ電波が届くこと、接続が切り替わりにくいこともある。最強APがそのエリアにあるとは保証しない。

これらの基準方式は比較候補の支持を計算せず、単一候補へ`score=1`を返す。これは確信度100%を意味しない。鮮度・既知APなどの入力検査は行うが、指紋距離・候補差による未知検出は持たないため、実験表の距離/差の閾値を変えてもこの2方式の結果は変わらない。常時表示する弱い基準として比較し、未知の場所で安全に棄却できる方式とは扱わない。

1-NNも1票だけなので、通常は候補差が1になり、0〜0.25の差閾値を変えても変わらない。現在の実装では、同じ最近傍距離（数値許容差1e-9）に異なるエリアが並ぶ場合を`ambiguous`として棄却する。距離が少し異なる2つの候補が近い場合の安全性は保証しない。1-NNの主な未知判定は指紋距離と観測数であり、k-NNの複数票による候補差と同じものではない。

## RSSI前処理

平均は小さいゆらぎを減らすが外れ値に弱い。中央値と外れ値を抑えた平均は一時的な大きなゆらぎに頑健な候補となる。EMAは過去値を指数的に小さく重み付けする。どれも因果的に過去だけを使う。異なる測定地点の間を平滑化しない。

一次元カルマンの状態を、静止セッション内のAPごとの真のRSSI `x_t` とする。

- 状態モデル: `x_t = x_(t-1) + w_t`, `w_t ~ N(0,Q)`。
- 観測モデル: `z_t = x_t + v_t`, `v_t ~ N(0,R)`。
- 予測分散: `P^- = P + Q`、ゲイン: `K = P^-/(P^-+R)`。
- 更新: `x = x^- + K(z-x^-)`、`P = (1-K)P^-`。

Qは真のRSSIが変化する許容度、Rは測定ノイズの分散、初期分散は開始時の不確かさを表す。初回測定で状態を初期化する。これは位置座標や速度の推定器ではない。Q/Rを大きくすれば必ず良くなるわけではなく、検証集合だけで比較する。初期値`Q=1,R=16,P0=25`は仮置きである。EKF/UKFを導入する非線形モデルは現段階で必要としていない。

## 研究の限界

模擬環境の壁減衰は簡易モデルであり、人体・机・複数経路・ローミング・無線帯域を十分に再現しない。UJIはAndroidによる大学建物のデータである。学校のWindows PCやAP側観測の性能は別に検証する。未見エリアの全種類を有限の未知検査で保証することもできない。実験結果と次の仮説は[RESULTS.md](RESULTS.md)に記録する。

## 今回実行した公開データ評価

UJIの小規模な建物/階分類は[results/uji/REPORT.md](../results/uji/REPORT.md)に記録した。UCI公式`trainingData.csv`を基準地点（建物・階・SPACEID・RELATIVEPOSITION）で学習/閾値検証に分割し、クラスごと学習最大80件、閾値検証最大30件に間引いた。学習1,040件・閾値検証390件で調整し、UCI公式`validationData.csv`全1,111件を最終テストに用いた。「公式validation」と「今回の閾値検証集合」は異なる。公式validationをモデルや閾値の選択には使っていない。

元CSVは520 WAP列を持つが、推定器は今回の学習集合で一度でも観測したAPだけを特徴にする。固定シード42の学習上限80件の条件では実際の距離計算は382 AP次元となる。多くのAPが欠測であるため、固定値-100による置換と全特徴RMSの値は、観測APだけで計算した距離とは異なる。未知判定の距離閾値は次元や観測密度が変わるデータへそのまま転用しない。時系列の連続性は確認できないため前処理を使わず、模擬データの6エリア正解率との直接比較は行わない。
