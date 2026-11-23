"""Compare anchor trilateration with fingerprinting under the same simulated conditions.

Run: python -m wifi_location.trilateration_experiments --output results/trilateration
Thresholds are tuned on validation groups and reported on untouched test groups.
Every number here comes from the simulator, not from the school.
"""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .algorithms import Engine
from .experiments import evaluate, split_data
from .simulation import AP_AREAS, AP_COORDS, AREA_POSITIONS, AREAS, generate
from .hybrid import Agreement, ModelFingerprint
from .trilateration import Trilaterator

SEEDS = [42, 43, 44, 45, 46]
# Labelled samples per area used to build or recalibrate a model; None means all training data.
BUDGETS = [1, 2, 6, None]
# A moved shelf in front of AP_B and a thicker partition, applied after the model was built.
CHANGED = {"ap_offsets": {"AP_B": -8.0}, "partition_db": 8.0}
# Location-specific offsets that no distance model explains (furniture, multipath), std in dB.
SHADOWING_DB = 6.0
# model_hybrid: anchor path-loss prior corrected by fingerprints; agreement: knn and trilateration must agree.
# Ablations of model_hybrid: centroid uses only measured area means, model_only only the fitted prior.
METHODS = ["strongest_ap", "knn", "trilateration", "model_hybrid", "agreement", "centroid", "model_only"]
PLOT_METHODS = METHODS[:5]
COLORS = {"strongest_ap": "#8c8c8c", "knn": "#1f77b4", "trilateration": "#ff7f0e",
          "model_hybrid": "#2ca02c", "agreement": "#9467bd", "centroid": "#17becf", "model_only": "#bcbd22"}


def keep_aps(observations, aps):
    return [replace(o, readings={ap: v for ap, v in o.readings.items() if ap in aps}) for o in observations]


def budget_sample(observations, per_area, seed):
    """A fixed number of labelled samples per area, the cost of one survey round."""
    if per_area is None:
        return observations
    rng = np.random.default_rng(seed)
    chosen = []
    for area in AREAS:
        pool = [o for o in observations if o.area == area]
        picks = rng.choice(len(pool), size=min(per_area, len(pool)), replace=False)
        chosen += [pool[i] for i in sorted(picks)]
    return chosen


def build(method, training, validation, anchors, built=None):
    """Pick the abstention thresholds that maximise accuracy - 2 * false display on validation."""
    if method == "agreement":
        return Agreement(built["knn"], built["trilateration"])
    if method == "strongest_ap":
        return Engine(training, {ap: AP_AREAS[ap] for ap in anchors}, algorithm="strongest_ap")
    candidates = []
    if method == "knn":
        per_area = max(1, len(training) // len(AREAS))
        for k in sorted({min(k, per_area) for k in (1, 3, 5)}):
            for distance in [16.0, 24.0, 32.0]:
                for margin in [0.0, .1, .25]:
                    candidates.append(lambda k=k, d=distance, m=margin: Engine(
                        training, AP_AREAS, algorithm="knn", k=k, max_distance=d, min_margin=m))
    elif method in ("model_hybrid", "centroid", "model_only"):
        shrinks = {"model_hybrid": [1.0, 4.0, 16.0], "centroid": [0.0], "model_only": [1e9]}[method]
        for shrink in shrinks:
            for offset_free in [False, True]:
                for distance in [5.0, 8.0, float("inf")]:
                    for margin in [0.0, .5, 1.0]:
                        candidates.append(lambda s=shrink, o=offset_free, d=distance, m=margin: ModelFingerprint(
                            training, {ap: AP_COORDS[ap] for ap in anchors}, AREA_POSITIONS,
                            shrink=s, offset_free=o, max_distance=d, min_margin=m))
    else:
        for residual in [3.0, 5.0, 8.0, float("inf")]:
            for margin in [0.0, 1.0, 2.0]:
                candidates.append(lambda r=residual, m=margin: Trilaterator(
                    training, {ap: AP_COORDS[ap] for ap in anchors}, AREA_POSITIONS, max_residual=r, min_margin=m))
    best, best_key = None, None
    for make in candidates:
        model = make()
        metrics, _ = evaluate(model, validation)
        key = (metrics["accuracy"] - 2 * metrics["false_display_rate"], -metrics["false_display_rate"])
        if best_key is None or key > best_key:
            best, best_key = model, key
    return best


def scenarios(seed):
    """(name, training, validation, test) per condition; anchors are applied later."""
    data = generate(seed)
    train, validation, test = split_data(data, "session", seed)
    # Same seed, so the noise is identical and only the building differs.
    changed = generate(seed, **CHANGED)
    changed_train, changed_validation, changed_test = split_data(changed, "session", seed)
    device_train, device_validation, device_test = split_data(data, "device", seed)
    shadowed = generate(seed, shadowing_db=SHADOWING_DB)
    shadow_train, shadow_validation, shadow_test = split_data(shadowed, "session", seed)
    missing_test = [replace(o, readings={ap: v for ap, v in o.readings.items() if ap != "AP_B"}) for o in test]
    return [
        ("normal", train, validation, test),
        ("environment_change", train, validation, changed_test),
        ("recalibrated_after_change", changed_train, changed_validation, changed_test),
        ("missing_ap_b", train, validation, missing_test),
        ("new_device", device_train, device_validation, device_test),
        ("location_shadowing", shadow_train, shadow_validation, shadow_test),
    ]


def run(output: Path, seeds=SEEDS):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        for name, train, validation, test in scenarios(seed):
            for anchors in (["AP_A", "AP_B", "AP_C", "AP_D"], ["AP_A", "AP_B", "AP_C"]):
                for per_area in BUDGETS:
                    labelled = budget_sample(train, per_area, seed)
                    # Thresholds always come from the separate validation set, so the budget
                    # limits only the fingerprints or the path-loss fit, not the threshold choice.
                    sets = [keep_aps(x, anchors) for x in (labelled, validation, test)]
                    built = {}
                    for method in METHODS:
                        built[method] = model = build(method, *sets[:2], anchors, built)
                        metrics, _ = evaluate(model, sets[2])
                        rows.append({"seed": seed, "scenario": name, "anchors": len(anchors),
                                     "labelled_per_area": per_area or "all", "labelled_samples": len(labelled),
                                     "method": method, **{k: metrics[k] for k in
                                     ("accuracy", "false_display_rate", "unknown_rate", "count")}})
    frame = pd.DataFrame(rows)
    full = frame[(frame.labelled_per_area == "all") & (frame.scenario == "normal")]
    full_per_area = int(full.labelled_samples.mean() // len(AREAS))
    frame.to_csv(output / "metrics_by_seed.csv", index=False, float_format="%.6f")
    keys = ["scenario", "anchors", "labelled_per_area", "method"]
    summary = (frame.groupby(keys, sort=False)[["accuracy", "false_display_rate", "unknown_rate"]]
               .agg(["mean", "std"]).reset_index())
    summary.columns = ["_".join(c).strip("_") for c in summary.columns]
    summary.to_csv(output / "metrics.csv", index=False, float_format="%.6f")
    summary.attrs["full_per_area"] = full_per_area
    plots(output, summary)
    report(output, summary, seeds, full_per_area)
    (output / "summary.json").write_text(json.dumps(
        {"source": "simulation", "seeds": list(seeds), "budgets_per_area": [b or "all" for b in BUDGETS],
         "full_labelled_per_area": full_per_area, "environment_change": CHANGED,
         "shadowing_db": SHADOWING_DB, "rows": len(frame)}, indent=2) + "\n")
    return summary


def plots(output, summary):
    full = summary[(summary.labelled_per_area == "all") & (summary.anchors == 4)]
    names = ["normal", "environment_change", "missing_ap_b", "new_device", "location_shadowing"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.5))
    width = .8 / len(PLOT_METHODS)
    for i, method in enumerate(PLOT_METHODS):
        part = full[full.method == method].set_index("scenario").loc[names]
        x = np.arange(len(names)) + (i - (len(PLOT_METHODS) - 1) / 2) * width
        axes[0].bar(x, part.accuracy_mean, width, yerr=part.accuracy_std, label=method, color=COLORS[method])
        axes[1].bar(x, part.false_display_rate_mean, width, yerr=part.false_display_rate_std, label=method,
                    color=COLORS[method])
    for ax, title in zip(axes, ["Area accuracy", "False display rate"]):
        ax.set_xticks(np.arange(len(names)), names, rotation=15)
        ax.set_title(f"{title} (simulation, 4 anchors, 5 seeds)")
        ax.set_ylim(0, 1)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=len(PLOT_METHODS), frameon=False)
    fig.tight_layout(rect=(0, .07, 1, 1))
    fig.savefig(output / "scenarios.png", dpi=120)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    full_count = summary.attrs.get("full_per_area", "all")
    labels = [str(b) if b else f"all ({full_count})" for b in BUDGETS]
    titles = {"recalibrated_after_change": "Rebuilt after an environment change",
              "location_shadowing": f"With {SHADOWING_DB:g} dB location shadowing"}
    for ax, (scenario, title) in zip(axes, titles.items()):
        part_all = summary[(summary.scenario == scenario) & (summary.anchors == 4)]
        for method in ("knn", "trilateration", "model_hybrid", "centroid", "model_only"):
            part = part_all[part_all.method == method].set_index("labelled_per_area").loc[[b or "all" for b in BUDGETS]]
            ax.errorbar(labels, part.accuracy_mean, yerr=part.accuracy_std, marker="o", capsize=3, label=method,
                        color=COLORS[method])
        ax.set_xlabel("labelled samples per area")
        ax.set_title(f"{title} (simulation)")
        ax.set_ylim(0, 1)
    axes[0].set_ylabel("area accuracy")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(output / "recalibration_budget.png", dpi=120)
    plt.close(fig)


def table(frame):
    lines = ["|条件|アンカー|正解付きサンプル/エリア|方式|正解率|誤表示率|不明率|", "|---|---:|---:|---|---:|---:|---:|"]
    for row in frame.itertuples():
        lines.append(f"|{row.scenario}|{row.anchors}|{row.labelled_per_area}|{row.method}|"
                     f"{row.accuracy_mean:.3f}±{row.accuracy_std:.3f}|{row.false_display_rate_mean:.3f}±{row.false_display_rate_std:.3f}|"
                     f"{row.unknown_rate_mean:.3f}|")
    return "\n".join(lines)


def report(output, summary, seeds, full_per_area):
    main = summary[summary.labelled_per_area == "all"]
    recal = summary[(summary.scenario == "recalibrated_after_change") & (summary.anchors == 4)]
    shadow = summary[(summary.scenario == "location_shadowing") & (summary.anchors == 4)]
    text = f"""# アンカー三辺測位と指紋方式の比較（シミュレーション）

データは模擬データのみ。学校の実環境での性能を示すものではない。シード {', '.join(map(str, seeds))} の平均±標準偏差。
閾値（k-NN は k も）は検証データで「正解率−2×誤表示率」が最大になるように選び、テストデータで評価した。
正解付きサンプル数の制限（保守の代理指標）は指紋または距離減衰係数の学習に使う数だけを制限し、閾値選択用の検証データは含めない。
all は学習用の全データ（1エリアあたり約 {full_per_area} 件、new_device は 64 件）。strongest_ap は正解付きデータを使わないため、サンプル数によらず同じ値になる。

条件：normal（通常）、environment_change（学習後に AP_B の前に棚を置き −8 dB、間仕切りを 4→8 dB に変更）、
recalibrated_after_change（変更後に測り直したデータで作り直し）、missing_ap_b（AP_B が受信できない）、new_device（学習と別の端末）、
location_shadowing（場所ごとに固定の減衰・増幅を加えた建物。標準偏差 {SHADOWING_DB:g} dB。距離モデルでは説明できない家具・反射の影響を想定）。

注意：模擬データは距離減衰＋階・間仕切りの減衰で作っているため、同じ形のモデルを使う model_hybrid に有利である。
location_shadowing はこの有利さを減らした条件である。

方式：strongest_ap（最も強いAPのエリア）、knn（指紋 k-NN）、trilateration（RSSIから距離を出す三辺測位）、
model_hybrid（距離と階数から各エリアのRSSIを予測し、測定サンプルで補正した指紋と照合）、
agreement（knn と trilateration が同じエリアを答えたときだけ表示）。
切り分け用：centroid（model_hybrid から予測を除き、測定したエリア平均だけで照合）、
model_only（model_hybrid から補正を除き、距離と階数による予測だけで照合）。

## 学習データをすべて使った場合

{table(main)}

## 環境変化の後、少ない測定で作り直した場合（アンカー4台）

{table(recal)}

## 場所ごとの固定の影響（shadowing）がある建物で、少ない測定で作った場合（アンカー4台）

{table(shadow)}

![条件ごとの比較](scenarios.png)
![作り直しに使った測定数](recalibration_budget.png)
"""
    (output / "REPORT.md").write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/trilateration"))
    parser.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = parser.parse_args()
    print(run(args.output, args.seeds).to_string())


if __name__ == "__main__":
    main()
