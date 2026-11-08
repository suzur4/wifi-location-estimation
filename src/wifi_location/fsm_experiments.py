"""Seed-separated, simulation-only experiments for display-state management.

Run with python -m wifi_location.fsm_experiments --output results/fsm.
Truth labels are used only for constructing explicit challenges and scoring.
Neither the estimator, the filter nor the state machine receives test truth.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import statistics

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .algorithms import Engine
from .filters import Kalman1D
from .models import Observation
from .simulation import AP_AREAS, AREAS, generate
from .state_machine import FsmConfig, FsmState, expire, observe


TRAIN_SEEDS = (11, 12, 13)
VALIDATION_SEEDS = (21, 22, 23)
TEST_SEEDS = (31, 32, 33)
MAX_AGE = 180
METHODS = {
    "A": ("既存の推定のみ", False, "instant"),
    "B": ("単純な連続判定", False, "consecutive"),
    "C": ("FSM", False, "fsm"),
    "D": ("カルマン＋既存推定", True, "instant"),
    "E": ("カルマン＋FSM", True, "fsm"),
}


@dataclass(frozen=True)
class Event:
    now: datetime
    truth: str
    observation: Observation | None
    challenge: str = "normal"


def scenarios(seed: int):
    """Mostly stationary trials plus isolated, explicitly synthetic safety challenges."""
    samples = generate(seed=seed, sessions=3, samples_per_area=24)
    groups = defaultdict(list)
    for sample in samples:
        groups[sample.session_id].append(sample)
    for name, batch in groups.items():
        yield f"{seed}-{name}", "stationary", [Event(o.timestamp, o.area, o) for o in batch]

    # Six separate trials per challenge. Changing the real area halfway does not
    # reset any processing state and never describes a teacher's movement.
    for area_index, area in enumerate(AREAS):
        batch = groups[f"sim-s00-{area}"]
        other = groups[f"sim-s01-{AREAS[(area_index + 1) % len(AREAS)]}"]
        for kind in ("transient", "missing_ap", "area_change", "stale", "replayed"):
            events = []
            offset = timedelta(0)
            for index, original in enumerate(batch):
                sample = replace(original, timestamp=original.timestamp + offset, area=None)
                truth, challenge = area, "normal"
                if kind == "transient" and index == 12:
                    sample = replace(sample, readings=other[index].readings,
                                     connected_ap=other[index].connected_ap)
                    challenge = "one_wrong_fingerprint"
                if kind == "missing_ap" and 10 <= index <= 15:
                    readings = dict(list(sample.readings.items())[:1]) if index < 13 else {}
                    sample = replace(sample, readings=readings, connected_ap=None)
                    challenge = "one_or_zero_ap"
                if kind == "area_change" and index >= 12:
                    sample = replace(sample, readings=other[index].readings,
                                     connected_ap=other[index].connected_ap)
                    truth = AREAS[(area_index + 1) % len(AREAS)]
                    challenge = "changed_area"
                events.append(Event(sample.timestamp, truth, sample, challenge))
                if kind == "stale" and index == 11:
                    events.append(Event(sample.timestamp + timedelta(seconds=MAX_AGE), truth, None, "expired"))
                    offset += timedelta(seconds=MAX_AGE + 3)
                if kind == "replayed" and index == 11:
                    events.append(Event(sample.timestamp + timedelta(seconds=1), truth, sample, "duplicate"))
                    events.append(Event(sample.timestamp + timedelta(seconds=2), truth,
                                        replace(batch[index - 1], area=None), "out_of_order"))
            yield f"{seed}-{kind}-{area}", kind, events


def inference(engine, events, filtered):
    """Process each new observation once. GET-like ticks never update filters."""
    last = None
    filters = {}
    for event in events:
        incoming = event.observation
        fresh = incoming is not None and (last is None or incoming.timestamp > last.timestamp)
        if fresh:
            if last is None or (incoming.timestamp - last.timestamp).total_seconds() >= MAX_AGE:
                filters.clear()
            if filtered:
                for ap in list(filters):
                    if ap not in incoming.readings:
                        del filters[ap]
                readings = {ap: filters.setdefault(ap, Kalman1D(q=1, r=16)).update(value)
                            for ap, value in incoming.readings.items()}
                last = replace(incoming, readings=readings, area=None)
            else:
                last = replace(incoming, area=None)
        estimate = engine.predict(last, now=event.now)
        count = len(set(last.readings).intersection(engine.aps))
        yield event, last, estimate, count, fresh


def trial(engine, events, config, method):
    _, filtered, policy = METHODS[method]
    state = FsmState()
    candidate, consecutive = None, 0
    rows = []
    for event, latest, estimate, ap_count, fresh in inference(engine, events, filtered):
        if policy == "fsm":
            state = expire(state, now=event.now, config=config)
            if fresh:
                state = observe(state, estimate, observed_at=latest.timestamp,
                                now=event.now, observed_aps=ap_count, config=config)
            displayed, reason = state.display_area, state.reason
            count = state.confirmations
        elif policy == "consecutive":
            if estimate.area == "unknown":
                candidate, consecutive = None, 0
            elif fresh:
                consecutive = consecutive + 1 if candidate == estimate.area else 1
                candidate = estimate.area
            displayed = candidate if consecutive >= config.confirmations else None
            reason = estimate.reason if displayed else "consecutive_pending"
            count = consecutive
        else:
            displayed = None if estimate.area == "unknown" else estimate.area
            reason, count = estimate.reason, int(displayed is not None)
        age = (event.now - latest.timestamp).total_seconds()
        rows.append({"timestamp": event.now.isoformat(), "truth": event.truth,
                     "display": displayed or "unknown", "reason": reason,
                     "raw_prediction": estimate.area, "age_seconds": age,
                     "challenge": event.challenge, "new_observation": fresh,
                     "confirmations": count, "observed_aps": ap_count,
                     "method": method})
    return rows


def metrics(rows):
    count = len(rows)
    correct = sum(row["display"] == row["truth"] and row["age_seconds"] < MAX_AGE for row in rows)
    unknown = sum(row["display"] == "unknown" for row in rows)
    displayed = count - unknown
    return {"events": count, "accuracy": correct / count,
            "false_display_rate": (displayed - correct) / count, "unknown_rate": unknown / count,
            "display_precision": correct / displayed if displayed else None,
            "expired_displays": sum(row["display"] != "unknown" and row["age_seconds"] >= MAX_AGE for row in rows),
            "display_changes": sum(a["display"] != b["display"] for a, b in zip(rows, rows[1:])
                                   if (a["trial"], a.get("method")) == (b["trial"], b.get("method"))),
            "transient_wrong_displays": sum(row["challenge"] == "one_wrong_fingerprint" and
                                            row["display"] not in (row["truth"], "unknown") for row in rows)}


def delays(rows):
    """Time/new observations to first correct display per truth segment, including censored segments."""
    result, current = [], []
    after_change = False
    for row in rows:
        if current and (row["trial"] != current[-1]["trial"] or row["truth"] != current[-1]["truth"]):
            result.append({**segment_delay(current), "after_area_change": after_change})
            after_change = row["trial"] == current[-1]["trial"]
            current = []
        current.append(row)
    if current:
        result.append({**segment_delay(current), "after_area_change": after_change})
    return result


def segment_delay(rows):
    observations = 0
    for row in rows:
        observations += int(row["new_observation"])
        if row["display"] == row["truth"] and row["age_seconds"] < MAX_AGE:
            seconds = (datetime.fromisoformat(row["timestamp"]) - datetime.fromisoformat(rows[0]["timestamp"])).total_seconds()
            return {"trial": row["trial"], "truth": row["truth"], "observations": observations, "seconds": seconds}
    return {"trial": rows[0]["trial"], "truth": rows[0]["truth"], "observations": None, "seconds": None}


def evaluate(engine, seeds, config, methods=tuple(METHODS)):
    results = []
    for seed in seeds:
        for identifier, kind, events in scenarios(seed):
            for method in methods:
                results.extend({**row, "trial": identifier, "scenario": kind, "seed": seed}
                               for row in trial(engine, events, config, method))
    return results


def summarize(rows):
    output = []
    for method in sorted({row["method"] for row in rows}):
        selected = [row for row in rows if row["method"] == method]
        for scenario in ("all", *sorted({row["scenario"] for row in selected})):
            group = selected if scenario == "all" else [row for row in selected if row["scenario"] == scenario]
            measured = delays(group)
            confirmed = [row for row in measured if row["seconds"] is not None]
            changed = [row for row in measured if row["after_area_change"]]
            changed_confirmed = [row for row in changed if row["seconds"] is not None]
            output.append({"method": method, "label": METHODS[method][0], "scenario": scenario,
                           **metrics(group), "truth_segments": len(measured),
                           "unconfirmed_segments": len(measured) - len(confirmed),
                           "changed_segments": len(changed),
                           "unconfirmed_changed_segments": len(changed) - len(changed_confirmed),
                           "mean_after_change_seconds": statistics.mean(row["seconds"] for row in changed_confirmed) if changed_confirmed else None,
                           "mean_confirm_observations": statistics.mean(row["observations"] for row in confirmed) if confirmed else None,
                           "mean_confirm_seconds": statistics.mean(row["seconds"] for row in confirmed) if confirmed else None})
    return output


def run(output, test_seeds=TEST_SEEDS):
    test_seeds = tuple(test_seeds)
    if not test_seeds or len(set(test_seeds)) != len(test_seeds) or set(test_seeds).intersection(TRAIN_SEEDS + VALIDATION_SEEDS):
        raise ValueError("test seeds must be distinct and disjoint from training/validation")
    training = [sample for seed in TRAIN_SEEDS for sample in generate(seed, sessions=3, samples_per_area=16)]
    engine = Engine(training, AP_AREAS, max_distance=16, min_margin=.25)
    candidates = []
    # Tune shared C/E parameters on validation ONLY, with equal weight for both.
    for confirmations in (2, 3, 4):
        for margin in (.25, .5):
            config = FsmConfig(confirmations=confirmations, max_age_seconds=MAX_AGE, min_aps=2, min_margin=margin)
            rows = evaluate(engine, VALIDATION_SEEDS, config, methods=("C", "E"))
            result = metrics(rows)
            candidates.append({"confirmations": confirmations, "min_margin": margin,
                               "utility": result["accuracy"] - 2 * result["false_display_rate"], **result})
    chosen = max(candidates, key=lambda row: (row["utility"], -row["false_display_rate"], -row["confirmations"], -row["min_margin"]))
    config = FsmConfig(confirmations=chosen["confirmations"], max_age_seconds=MAX_AGE,
                       min_aps=2, min_margin=chosen["min_margin"])
    rows = evaluate(engine, test_seeds, config)
    aggregate = summarize(rows)
    by_seed = [{"seed": seed, **row} for seed in test_seeds
               for row in summarize([row for row in rows if row["seed"] == seed])]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output / "predictions.csv", index=False)
    pd.DataFrame(aggregate).to_csv(output / "metrics.csv", index=False)
    pd.DataFrame(by_seed).to_csv(output / "by_seed.csv", index=False)
    pd.DataFrame(candidates).to_csv(output / "validation.csv", index=False)
    source_names = ("fsm_experiments.py", "state_machine.py", "algorithms.py", "filters.py", "simulation.py")
    summary = {"source": "simulation", "training_seeds": TRAIN_SEEDS,
               "validation_seeds": VALIDATION_SEEDS, "test_seeds": test_seeds,
               "training_observations": len(training), "fsm_config": asdict(config),
               "engine": {"algorithm": "knn", "k": 5, "min_aps": 2, "max_distance": 16, "min_margin": .25},
               "kalman": {"q": 1, "r": 16, "initial_variance": 25},
               "selection": "validation C/E average accuracy - 2*false_display_rate; then fewer errors, smaller N, smaller margin",
               "code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in source_names},
               "prediction_sha256": hashlib.sha256((output / "predictions.csv").read_bytes()).hexdigest(),
               "metrics": aggregate, "by_seed": by_seed}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plot(output, aggregate, by_seed)
    report(output, summary)
    return summary


def plot(output, aggregate, by_seed):
    overall = [row for row in aggregate if row["scenario"] == "all"]
    labels = ["A\nk-NN", "B\nConsecutive", "C\nFSM", "D\nKalman", "E\nKalman + FSM"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bottom = [0.0] * len(overall)
    for field, label, color in (("accuracy", "Correct display", "#286947"),
                                 ("false_display_rate", "Wrong display", "#c45b3b"),
                                 ("unknown_rate", "Unknown", "#c9d0d8")):
        values = [100 * row[field] for row in overall]
        ax.bar(labels, values, bottom=bottom, label=label, color=color)
        bottom = [a + b for a, b in zip(bottom, values)]
    ax.set(title="SIMULATION | held-out seeds | all scenarios", ylabel="Percent of evaluation events", ylim=(0, 100))
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.12), ncol=3)
    fig.tight_layout()
    fig.savefig(output / "display_rates.png", dpi=140)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for seed in sorted({row["seed"] for row in by_seed}):
        selected = [row for row in by_seed if row["seed"] == seed and row["scenario"] == "all"]
        axes[0].plot(labels, [100 * row["false_display_rate"] for row in selected], "o-", label=f"seed {seed}")
        axes[1].plot(labels, [row["mean_confirm_seconds"] for row in selected], "o-", label=f"seed {seed}")
    axes[0].set(ylabel="Wrong displays (%)", title="SIMULATION | held-out seeds")
    axes[1].set(ylabel="Seconds to first correct display", title="Confirmed segments only; see censored counts")
    axes[0].legend()
    fig.tight_layout()
    fig.savefig(output / "errors_and_delay.png", dpi=140)
    plt.close(fig)


def report(output, summary):
    config = summary["fsm_config"]
    lines = ["# 表示状態の比較実験結果", "", "全て模擬データ。実在の教員・学校AP・学校ネットワークは使用していない。", "",
             f"学習シード {list(TRAIN_SEEDS)}、調整用 {list(VALIDATION_SEEDS)}、最終評価用 {list(summary['test_seeds'])}。",
             f"調整用で選んだFSM条件は確認 {config['confirmations']} 回、スコア差 {config['min_margin']} 以上、既知AP {config['min_aps']} 台、鮮度 {config['max_age_seconds']} 秒未満。", "",
             "|方式|正解表示率|誤表示率|位置不明率|平均観測数|平均待ち秒|未確定区間|表示変動回数|期限切れ表示|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary["metrics"]:
        if row["scenario"] != "all":
            continue
        lines.append(f"|{row['method']} {row['label']}|{row['accuracy']:.1%}|{row['false_display_rate']:.1%}|{row['unknown_rate']:.1%}|{row['mean_confirm_observations']:.2f}|{row['mean_confirm_seconds']:.2f}|{row['unconfirmed_segments']}/{row['truth_segments']}|{row['display_changes']}|{row['expired_displays']}|")
    lines += ["", "正解表示率・誤表示率・位置不明率の分母は評価イベント全件。期限切れを表示した場合は誤表示に数える。表示変動は不明との切替も含み、独立試行の境界は数えない。平均待ち時間・観測数は初めて正解表示に到達した区間のみで算出し、到達しなかった区間数を別記する。", "",
              "静止試行を中心に、一時的な誤指紋、AP欠損、エリア変更、期限切れ、重複・逆順受信を追加した。異なる設定で使った入力は同じ。FSMを使わない方式も既存Engineの鮮度判定を使うため、期限切れゼロだけではFSMの優位性を示さない。", "",
              "## グラフと再確認", "", "![表示の内訳](display_rates.png)", "", "![シード別の誤表示と待ち時間](errors_and_delay.png)", "",
              "[方式・条件別CSV](metrics.csv)、[各シードCSV](by_seed.csv)、[調整用CSV](validation.csv)、[全評価イベントCSV](predictions.csv)、[設定とコードハッシュ](summary.json)。", "",
              "本実験で使うスコア差はモデルの相対支持の差であり、正解確率ではない。少数のシードと共有の模擬電波モデルによる結果であり、実機性能や統計的優越を示すものではない。カルマンのQ/Rは既存研究値を固定し、この評価では最適化していない。Web本体へのカルマン導入は本実験の対象外。", ""]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/fsm"))
    parser.add_argument("--seeds", type=int, nargs="+", default=TEST_SEEDS)
    args = parser.parse_args()
    summary = run(args.output, args.seeds)
    print(json.dumps({"output": str(args.output), "fsm_config": summary["fsm_config"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
