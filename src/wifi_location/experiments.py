"""Reproducible comparisons; tune on validation, report on untouched test groups.

Run: python -m wifi_location.experiments --output results/latest --seed 42
All synthetic results must remain labelled simulation, including plot titles.
"""

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from time import perf_counter

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from .algorithms import Engine
from .filters import preprocess
from .models import Observation
from .selection import select_aps, strongest_aps
from .simulation import AP_AREAS, AREAS, generate
from .sources import write_csv, load_uji

CONFIGS = [
    ("A", "strongest_ap", "none", "all", 5),
    ("B", "knn", "none", "all", 5),
    ("C", "knn", "median", "all", 5),
    ("D", "knn", "ema", "all", 5),
    ("E", "knn", "kalman", "all", 5),
    ("F", "rank", "none", "all", 5),
    ("G", "knn", "median", "discriminative", 5),
    ("H", "gaussian", "median", "all", 5),
    ("I", "connected_ap", "none", "all", 5),
    ("J", "1nn", "none", "all", 1),
    ("K", "weighted_knn", "none", "all", 5),
    ("L", "knn", "mean", "all", 5),
    ("M", "knn", "robust_mean", "all", 5),
    ("N", "knn", "none", "all", 3),
]


def split_data(data: list[Observation], mode="session", seed=42):
    """Group batches including all areas to keep shared session drift together."""
    if mode == "session":
        batches = sorted({o.session_id.split("-")[1] for o in data})
        order = np.random.default_rng(seed).permutation(batches).tolist()
        n = len(order)
        groups = [set(order[:int(n*.6)]), set(order[int(n*.6):int(n*.8)]), set(order[int(n*.8):])]
        key = lambda o: o.session_id.split("-")[1]
    elif mode == "date":
        dates = sorted({o.timestamp.date() for o in data})
        if len(dates) < 3:
            raise ValueError("not enough independent groups for split")
        groups = [set(dates[:-2]), {dates[-2]}, {dates[-1]}]
        key = lambda o: o.timestamp.date()
    elif mode == "device":
        devices = sorted({o.device_id for o in data})
        if len(devices) < 3:
            raise ValueError("not enough independent groups for split")
        groups = [{devices[0]}, {devices[1]}, set(devices[2:])]
        key = lambda o: o.device_id
    else:
        raise ValueError(f"unknown split {mode}")
    result = tuple([o for o in data if key(o) in group] for group in groups)
    if any(not part for part in result):
        raise ValueError("not enough independent groups for split")
    return result


def evaluate(engine, observations):
    """Evaluate known-area classification; unknown-area detection is separate.

    Reject absent/unknown ground truth instead of treating an abstention as
    both a correct area display and an unknown result in the accounting.
    """
    if not observations:
        raise ValueError("evaluation data must be nonempty")
    if any(not observation.area or not observation.area.strip() or observation.area == "unknown"
           for observation in observations):
        raise ValueError("evaluation requires known, nonempty ground-truth area labels")
    predictions, durations = [], []
    for observation in observations:
        start = perf_counter()
        result = engine.predict(observation, now=observation.timestamp)
        durations.append((perf_counter()-start)*1000)
        predictions.append(result)
    n = len(observations)
    correct = sum(pred.area == obs.area for obs, pred in zip(observations, predictions))
    unknown = sum(pred.area == "unknown" for pred in predictions)
    wrong = n - correct - unknown
    # Unknown is never counted correct in these known-area test sets.
    return {"accuracy": correct/n, "false_display_rate": wrong/n, "unknown_rate": unknown/n,
            "precision": correct/(n-unknown) if n > unknown else None,
            "latency_ms": float(np.mean(durations)), "count": n,
            "reasons": dict(Counter(p.reason for p in predictions))}, predictions


def tune(training, validation, algorithm="knn", k=5, selected=None):
    candidates = []
    for distance in [16.0, 24.0, 32.0]:
        for margin in [0.0, .1, .25]:
            model = Engine(training, AP_AREAS, algorithm=algorithm, k=k,
                           selected_aps=selected, max_distance=distance, min_margin=margin)
            metrics, _ = evaluate(model, validation)
            utility = metrics["accuracy"] - 2*metrics["false_display_rate"]
            candidates.append((utility, -metrics["false_display_rate"], -distance, margin, distance))
    best = max(candidates)
    return {"max_distance": best[4], "min_margin": best[3]}


def run(output: Path, seed=42, filter_parameters=None):
    output.mkdir(parents=True, exist_ok=True)
    filter_parameters = filter_parameters or {"window": 5, "alpha": .35, "q": 1, "r": 16, "initial_variance": 25}
    # Validate settings before writing output artifacts.
    preprocess([], "kalman", **filter_parameters)
    data = generate(seed=seed, sessions=12, samples_per_area=16)
    write_csv(output / "observations.csv", data)
    digest = hashlib.sha256((output / "observations.csv").read_bytes()).hexdigest()
    parameter_hash=hashlib.sha256(json.dumps(filter_parameters,sort_keys=True).encode()).hexdigest()[:6]
    experiment_id = f"sim-{seed}-{digest[:10]}-{parameter_hash}"
    train, validation, test = split_data(data, seed=seed)
    manifest = {"experiment_id": experiment_id, "source": "simulation", "seed": seed,
                "data_sha256": digest, "observations": len(data), "split": "stationary batch; all areas grouped",
                "training_sessions": sorted({o.session_id for o in train}),
                "validation_sessions": sorted({o.session_id for o in validation}),
                "test_sessions": sorted({o.session_id for o in test}),
                "counts": [len(train), len(validation), len(test)],
                "software": {name: version(name) for name in ["numpy","pandas","scikit-learn","matplotlib"]},
                "code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                    for name in ["algorithms.py","filters.py","simulation.py","selection.py","experiments.py"]},
                "parameters": {"sessions": 12, "samples_per_area": 16, **filter_parameters,
                    "min_aps": 2, "max_age_seconds": 180},
                "tuning": "validation utility = correct/N - 2*wrong_display/N; grid distance=16,24,32 margin=0,.1,.25",
                "created_at": datetime.now(timezone.utc).isoformat()}
    rows, predictions = [], {}
    fitted = {}
    for identifier, algorithm, method, selection, k in CONFIGS:
        a, b, c = [preprocess(part, method, **filter_parameters) for part in [train, validation, test]]
        aps = select_aps(a, selection, n=3) if selection != "all" else None
        params = tune(a, b, algorithm, k, aps)
        model = Engine(a, AP_AREAS, algorithm=algorithm, k=k, selected_aps=aps, **params)
        metrics, pred = evaluate(model, c)
        row = {"id": identifier, "algorithm": algorithm, "preprocessing": method,
               "selection": selection, "k": k, "selected_aps": aps, **params, **metrics}
        rows.append(row)
        predictions[identifier] = pred
        fitted[identifier] = (model, c)
        print(f"{identifier}: {algorithm}/{method} correct={metrics['accuracy']:.3f} wrong={metrics['false_display_rate']:.3f} unknown={metrics['unknown_rate']:.3f}", flush=True)

    # Extra generalization checks use a fixed predeclared configuration, not a
    # configuration picked after seeing the primary test outcomes.
    generalization = []
    for mode in ["device", "date"]:
        a,b,c = [preprocess(part, "median", **filter_parameters) for part in split_data(data, mode, seed)]
        params = tune(a,b)
        metrics, _ = evaluate(Engine(a, AP_AREAS, **params),c)
        generalization.append({"split": mode, "algorithm": "knn", "preprocessing": "median",
                               "counts": [len(a),len(b),len(c)], **params, **metrics})

    model, test_filtered = fitted["C"]
    stress = []
    for count in [0,1,2]:
        changed = [replace(o,readings=dict(list(o.readings.items())[count:])) for o in test_filtered]
        metrics,_ = evaluate(model,changed)
        stress.append({"drop_first_n_aps":count, **metrics})
    challenge_base = test_filtered[0]
    challenges = {
        "no_readings": replace(challenge_base,readings={},connected_ap=None),
        "unmapped": replace(challenge_base,readings={"AP_UNKNOWN":-40},connected_ap=None),
        "far_pattern": replace(challenge_base,readings={ap:-15 for ap in AP_AREAS}),
        "stale": replace(challenge_base,timestamp=challenge_base.timestamp-timedelta(seconds=181)),
    }
    reliability = {key: asdict(model.predict(obs,now=challenge_base.timestamp)) for key,obs in challenges.items()}

    ap_curve=[]
    a,b,c = [preprocess(part,"median", **filter_parameters) for part in [train,validation,test]]
    for selection in ["all","strongest","stable","discriminative"]:
        for n in range(1,5):
            if selection == "strongest":
                aa,cc = [[replace(o,readings=strongest_aps(o.readings,n)) for o in part] for part in [a,c]]
                selected=None
            else:
                aa,cc=a,c
                selected=select_aps(a,selection if selection != "all" else "all",n)[:n]
            metrics,_ = evaluate(Engine(aa,AP_AREAS,selected_aps=selected,min_aps=min(2,n),
                                      max_distance=24,min_margin=.1),cc)
            ap_curve.append({"selection":selection,"ap_count":n,"min_aps":min(2,n),**metrics})

    # Threshold curve is on validation ONLY. Do not tune after seeing test plots.
    thresholds=[]
    for margin in np.linspace(0,.8,9):
        metrics,_=evaluate(Engine(a,AP_AREAS,min_margin=float(margin),max_distance=24),b)
        thresholds.append({"margin":float(margin),**metrics})
    variations=[]
    first=[o for o in data if o.session_id==data[0].session_id]
    for method in ["none","mean","median","robust_mean","ema","kalman"]:
        filtered=preprocess(first,method, **filter_parameters)
        per_ap=[float(np.std([o.readings[ap] for o in filtered if ap in o.readings])) for ap in AP_AREAS]
        variations.append({"method":method,"mean_within_stationary_session_std_dbm":float(np.mean(per_ap))})

    summary={**manifest,"metrics":rows,"generalization":generalization,"missing_ap_stress":stress,
             "reliability_checks":reliability,"filter_variation":variations}
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    for name,records in [("metrics",rows),("generalization",generalization),("ap_selection",ap_curve),
                         ("thresholds_validation",thresholds),("filter_variation",variations),("missing_aps",stress)]:
        pd.DataFrame(records).to_csv(output/f"{name}.csv",index=False)
    prediction_rows=[]
    for identifier,preds in predictions.items():
        for obs,pred in zip(test,preds):
            prediction_rows.append({"experiment":identifier,"session_id":obs.session_id,
                "timestamp":obs.timestamp.isoformat(),"truth":obs.area,"prediction":pred.area,"reason":pred.reason})
    pd.DataFrame(prediction_rows).to_csv(output/"predictions.csv",index=False)
    plots(output,data,rows,predictions["C"],test,ap_curve,thresholds,experiment_id,filter_parameters)
    report(output,summary)
    return summary


def plots(output,data,metrics,predictions,test,ap_curve,thresholds,experiment_id,filter_parameters):
    plt.rcParams.update({"figure.figsize":(10,5),"axes.spines.top":False,"axes.spines.right":False,
                         "axes.prop_cycle":plt.cycler(color=["#007f87","#d98139","#576ea0","#8a5b8d"])})
    condition=f"SIMULATION | {experiment_id} | 4 APs / 6 areas / seed-fixed"
    def save(name,title):
        plt.title(title+"\n"+condition,fontsize=10)
        plt.tight_layout()
        plt.savefig(output/f"{name}.png",dpi=140)
        plt.close()
    first=[o for o in data if o.session_id==data[0].session_id]
    for ap in AP_AREAS:
        plt.plot(range(len(first)),[o.readings.get(ap,np.nan) for o in first],marker=".",label=ap)
    plt.xlabel("Sample in one stationary session (3 s intervals)");plt.ylabel("RSSI (dBm)");plt.legend()
    save("01_rssi_series","Raw RSSI; gaps = AP missing")
    plt.boxplot([[o.readings[ap] for o in data if ap in o.readings] for ap in AP_AREAS],tick_labels=list(AP_AREAS))
    plt.ylabel("RSSI (dBm)");save("02_rssi_distribution","RSSI distribution across synthetic areas")
    for method in ["none","mean","median","kalman"]:
        filtered=preprocess(first,method, **filter_parameters)
        plt.plot([o.readings.get("AP_A",np.nan) for o in filtered],marker=".",label=method)
    plt.xlabel("Sample (causal filters, stationary session)");plt.ylabel("AP_A RSSI (dBm)");plt.legend()
    save("03_filters","Mean / median / Kalman comparison")
    plt.bar([r["id"] for r in metrics],[r["accuracy"] for r in metrics]);plt.ylim(0,1)
    plt.xlabel("Experiment ID (see metrics.csv)");plt.ylabel("Correct / all test samples")
    save("04_accuracy","Held-out stationary session accuracy")
    labels=AREAS+["unknown"]
    matrix=confusion_matrix([o.area for o in test],[p.area for p in predictions],labels=labels)
    plt.imshow(matrix,cmap="Blues");plt.colorbar(label="Count")
    plt.xticks(range(len(labels)),labels,rotation=35,ha="right");plt.yticks(range(len(labels)),labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            plt.text(j,i,str(matrix[i,j]),ha="center",va="center",color="white" if matrix[i,j]>matrix.max()/2 else "black",fontsize=8)
    plt.xlabel("Displayed result");plt.ylabel("True synthetic area");save("05_confusion","C: k-NN + median confusion matrix")
    for method in sorted({r["selection"] for r in ap_curve}):
        rows=[r for r in ap_curve if r["selection"]==method]
        plt.plot([r["ap_count"] for r in rows],[r["accuracy"] for r in rows],marker="o",label=method)
    plt.xticks([1,2,3,4]);plt.ylim(0,1);plt.xlabel("Selected AP count (N=1 allows one AP)");plt.ylabel("Correct / all test samples");plt.legend()
    save("06_ap_count","AP selection sensitivity; fixed thresholds, exploratory")
    for key in ["false_display_rate","unknown_rate"]:
        plt.plot([r["margin"] for r in thresholds],[r[key] for r in thresholds],marker="o",label=key)
    plt.xlabel("Minimum score margin (not probability)");plt.ylabel("Fraction of validation samples");plt.ylim(0,1);plt.legend()
    save("07_thresholds","Validation-only reliability threshold trade-off")


def report(output,summary):
    p=summary["parameters"]
    lines=["# 模擬データ比較実験レポート","",f"実験ID: `{summary['experiment_id']}`。データソース: **simulation**。学校の実測結果ではない。","",
      "## 目的・仮説","","RSSI前処理と単純な分類器の効果を、セッションを分離して比較する。中央値などが外れ値の影響を減らすと仮定するが、常に改善するとは仮定しない。","",
      "## データ・条件","",f"4 AP・6エリア、{summary['observations']}観測。学習/検証/テスト={summary['counts']}。固定シード={summary['seed']}。",
      "壁・階による減衰、ノイズ、外れ値、8%のAP欠損、端末オフセット、日付/セッション変動を含む独自の模擬モデル。同じ減衰式で生成した学習・テストの結果は実環境の精度を予測しない。",
      "同じ静止測定バッチの全エリアを同一集合に入れた。フィルタは端末・セッションごとにリセットし、過去と現在だけを使う。検証集合だけで閾値を選択し、テスト集合で比較を行った。",
      f"平均/中央値/頑健平均の窓{p['window']}、EMA alpha={p['alpha']}、Kalman Q={p['q']},R={p['r']},初期分散{p['initial_variance']}。kは表を参照。距離は欠損を-100 dBmにしたRSSIのRMS。最小共通AP数2。Gは学習集合のエリア間/エリア内分散比で3 APを選択。",
      "", "## 指標の定義","","正解率=正しく表示した数/N、誤表示率=誤った既知エリアの表示数/N、位置不明率=unknown数/N。表示正答率=正しく表示した数/表示した数（表示0なら未定義）。このテスト集合は既知エリアのみ。スコアは較正確率ではない。推定時間はこのPCでのモデル構築を除く平均時間。","",
      "## 定量結果","","|ID|方式|前処理|k|正解率|誤表示率|不明率|表示正答率|ms/件|距離閾値|差閾値|","|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary["metrics"]:
        precision=f"{row['precision']:.3f}" if row["precision"] is not None else "未定義"
        lines.append(f"|{row['id']}|{row['algorithm']}|{row['preprocessing']}|{row['k']}|{row['accuracy']:.3f}|{row['false_display_rate']:.3f}|{row['unknown_rate']:.3f}|{precision}|{row['latency_ms']:.3f}|{row['max_distance']}|{row['min_margin']}|")
    lines += ["","## 端末・日時の分離","","固定構成Cを、それぞれ独立した端末/日付分割で再学習・検証した。各評価内でテストデータを閾値選択に使っていない。"]
    for row in summary["generalization"]:
        lines.append(f"- {row['split']}: 正解率 {row['accuracy']:.3f}、誤表示率 {row['false_display_rate']:.3f}、不明率 {row['unknown_rate']:.3f}。分割数 {row['counts']}。")
    lines += ["","## RSSI変動・AP欠損","","以下の標準偏差は最初の静止セッションでのAP別標準偏差の平均。全エリアを混ぜた変動幅ではない。"]
    lines += [f"- {r['method']}: {r['mean_within_stationary_session_std_dbm']:.3f} dBm" for r in summary["filter_variation"]]
    lines += [f"- APを先頭から{r['drop_first_n_aps']}個追加欠損: 正解率 {r['accuracy']:.3f}、不明率 {r['unknown_rate']:.3f}" for r in summary["missing_ap_stress"]]
    lines += ["","## 不明判定の確認","",* [f"- {k}: `{v['area']}` / `{v['reason']}`" for k,v in summary["reliability_checks"].items()],"","## グラフ",""]
    for path in sorted(output.glob("0*.png")):
        lines.append(f"![{path.stem}]({path.name})\n")
    lines += ["## 考察・制約","","最強/接続APの4エリアへの対応だけでは中間階の2エリアを表現できない。前処理が良くない結果も含め全方式を掲載した。結果の差には一つのシードと模擬モデルへの依存があり、統計的有意差や学校での性能は主張できない。",
      "順位方式も絶対RSSI距離による未知判定を併用し、同順位の決着に微小なRSSI距離項を使う。確率的分類はAP間独立と正規分布を仮定し、欠損置換の影響を受ける。",
      "接続/最強APは単一対応表の基準手法で候補差・距離閾値は適用されない。1-NNも通常の投票差は1で、距離が完全に同じ異なるラベルの場合だけ特別に不明とする。これらの表の差閾値を較正された信頼度と解釈しない。",
      "未知エリア検出は距離のヒューリスティックであり、既知エリアと類似した未知エリアを保証して検出するものではない。上の4例は健全性確認で、未知分布に対する検出率の評価ではない。",
      "AP数グラフは固定閾値の探索的感度分析で、方式選定には使わない。strongestは観測ごとの強いN AP、stable/discriminativeは学習データだけで選択。all曲線の部分集合はAP名順の比較用である。",
      "","## 次の実験","","複数シード、別の減衰モデル、未知エリアの独立収集で検証する。学校の許可後、別端末・別日付の静止測定で再較正する。公開AndroidデータとWindows/管理APIデータを混ぜず、取得方式差の影響を別途評価する。","",
      "再実行: `python -m wifi_location.experiments --seed 42 --output results/latest`。manifest/summaryと観測ハッシュで条件を照合できる。時間測定値と生成時刻は実行ごとに変動する。"]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("results/latest"))
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--window",type=int,default=5)
    parser.add_argument("--alpha",type=float,default=.35)
    parser.add_argument("--q",type=float,default=1)
    parser.add_argument("--r",type=float,default=16)
    parser.add_argument("--initial-variance",type=float,default=25)
    args=parser.parse_args()
    run(args.output,args.seed,{"window":args.window,"alpha":args.alpha,"q":args.q,"r":args.r,"initial_variance":args.initial_variance})


if __name__ == "__main__":
    main()
