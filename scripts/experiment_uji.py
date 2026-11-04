"""Small independent UJIIndoorLoc building/floor benchmark, no school data.

Official training file is grouped by labelled reference location before
subsampling. Official validation file is reserved as the final temporal test.
Rows have no verified stationary session, so temporal filtering is not used.
"""

from collections import defaultdict
import json
from pathlib import Path
import numpy as np
import pandas as pd

from wifi_location.algorithms import Engine
from wifi_location.experiments import evaluate
from wifi_location.sources import load_uji

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/"data/ujindoorloc"
    original=load_uji(folder/"trainingData.csv")
    official_test=load_uji(folder/"validationData.csv")
    meta=pd.read_csv(folder/"trainingData.csv",usecols=["BUILDINGID","FLOOR","SPACEID","RELATIVEPOSITION"])
    keys=[tuple(row) for row in meta.to_numpy().tolist()]
    rng=np.random.default_rng(42)
    shuffled=sorted(set(keys))
    rng.shuffle(shuffled)
    validation_groups=set(shuffled[:int(len(shuffled)*.2)])
    training=[o for o,key in zip(original,keys) if key not in validation_groups]
    validation=[o for o,key in zip(original,keys) if key in validation_groups]
    def capped(data,n):
        by_area=defaultdict(list)
        for o in data:
            by_area[o.area].append(o)
        return [group[int(i)] for area,group in sorted(by_area.items())
                for i in rng.permutation(len(group))[:n]]
    training=capped(training,80)
    validation=capped(validation,30)
    results=[]
    for algorithm in ["1nn","knn","weighted_knn","gaussian"]:
        candidates=[]
        for distance in [8,16,24]:
            for margin in [0,.1,.25]:
                metrics,_=evaluate(Engine(training,{},algorithm=algorithm,max_distance=distance,min_margin=margin),validation)
                candidates.append((metrics["accuracy"]-2*metrics["false_display_rate"],-distance,margin))
        chosen=max(candidates)
        params={"max_distance":-chosen[1],"min_margin":chosen[2]}
        metrics,_=evaluate(Engine(training,{},algorithm=algorithm,**params),official_test)
        results.append({"algorithm":algorithm,**params,**metrics})
        print(algorithm,metrics,flush=True)
    summary={"experiment_id":"uji-building-floor-seed42-cap80", "source":"ujindoorloc",
             "citation":"Torres-Sospedra et al. (2014), DOI 10.24432/C5MS59", "license":"CC BY 4.0",
             "task":"building/floor classification; not school areas or coordinate error",
             "split":"official training location-group split, then max80 train/max30 validation per class; entire official validation held out as test",
             "counts":[len(training),len(validation),len(official_test)],"input_ap_columns":520,
             "model_features":len({ap for o in training for ap in o.readings}),"missing":100,
             "preprocessing":"none; no trustworthy stationary sequence metadata",
             "seed":42,"metrics":results}
    output=ROOT/"results/uji"
    output.mkdir(parents=True,exist_ok=True)
    (output/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False))
    pd.DataFrame(results).to_csv(output/"metrics.csv",index=False)
    lines=["# UJIIndoorLoc 独立ベンチマーク","", "データソース: UJIIndoorLoc。学校の実測ではない。Android由来データを模擬データやWindows測定と混ぜていない。",
           "", "建物/階の分類を行う。学校の6エリア分類と対象が異なるため、正解率を直接比較しない。公式trainingを基準地点（建物/階/SPACEID/RELATIVEPOSITION）で分離して学習・閾値検証し、公式validation全件を最終テストとして使用した。",
           f"学習/閾値検証/テスト={summary['counts']}。学習はクラスごと最大80件、閾値検証最大30件に固定シードで間引いた小規模実験。全データ学習のベンチマーク記録を再現するものではない。",
           f"入力は520 AP列。間引き後の学習集合で一度でも観測されたAP {summary['model_features']}個を特徴量に使う。未検出100は欠損として除き、距離計算では欠損を-100dBmに置換。共通AP最小2。独立した静止セッションの並びを確認できないため平滑化しない。データのラベルが同じでも時間フィルタを適用して連結しない。",
           "", "|方式|正解率|誤表示率|不明率|表示正答率|ms/件|距離閾値|差閾値|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        precision=f"{r['precision']:.3f}" if r['precision'] is not None else "未定義"
        lines.append(f"|{r['algorithm']}|{r['accuracy']:.3f}|{r['false_display_rate']:.3f}|{r['unknown_rate']:.3f}|{precision}|{r['latency_ms']:.3f}|{r['max_distance']}|{r['min_margin']}|")
    lines += ["", "閾値は公式training内の検証集合で正解率−2×誤表示率を最大化して選んだ。公式validationは選択に使っていない。欠損が多い学習AP集合での全次元RMSは観測APだけの距離と意味が異なり、未知判定の一般性は保証されない。",
              "", "引用: [UCI UJIIndoorLoc](https://archive.ics.uci.edu/dataset/310/ujindoorloc)、[DOI](https://doi.org/10.24432/C5MS59)、CC BY 4.0。データの条件と取得ハッシュは data/ujindoorloc/README.md および download.json を参照。",
              "", "再実行: `.venv/bin/python scripts/experiment_uji.py`。データ未取得の場合は先に `scripts/download_uji.py` を実行する。"]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")


if __name__=="__main__":
    main()
