"""Train the diagnosis model three ways and write a report.

    uv run python scripts/train_diagnosis.py

Reads data/train.parquet and data/station_road.parquet (see make_dataset.py).
Writes models/diagnosis.joblib (the plain + LWM version, which the agent uses) and out/diagnosis_report.md.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import joblib  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nethealers.diagnosis.train import VARIANTS, evaluate, fit, split_by_episode  # noqa: E402


def plot_confusion(report, path):
    cm = report.confusion.values.astype(float)
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    labels = [c.replace("true ", "") for c in report.confusion.index]
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("model said")
    ax.set_ylabel("true cause")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{norm[i, j]:.0%}\n({int(cm[i, j])})", ha="center", va="center", fontsize=8,
                    color="white" if norm[i, j] > 0.6 else "#12303E")
    ax.set_title(f"{report.variant} on {report.dataset}")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    data = pd.read_parquet(ROOT / "data" / "train.parquet")
    station = pd.read_parquet(ROOT / "data" / "station_road.parquet")
    train, val, test = split_by_episode(data)
    print(f"train {len(train)} rows / val {len(val)} / held-out cities {len(test)} / Station Road {len(station)}")
    print("train labels:", train.label.value_counts().to_dict())

    models, reports = {}, []
    for v in VARIANTS:
        t0 = time.time()
        m = fit(train, val, v)
        models[v] = m
        for name, df in (("validation", val), ("held-out cities", test), ("Station Road", station)):
            reports.append(evaluate(m, df, name))
        print(f"{v:10s} trained in {time.time() - t0:.0f}s on {len(m.columns)} inputs")

    summary = pd.DataFrame([{
        "version": r.variant, "data": r.dataset, "rows": r.n, "accuracy": round(r.accuracy, 3),
        "macro F1": round(r.macro_f1, 3), "calibration error": round(r.ece, 3),
        ">=90% sure: share": round(r.confident[0.9][0], 2), ">=90% sure: accuracy": round(r.confident[0.9][1], 3),
    } for r in reports])
    print(summary.to_string(index=False))

    # The project uses LWM by design; the other versions are kept as evidence of what it adds.
    best = "plain+lwm"
    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump(models[best], ROOT / "models" / "diagnosis.joblib")
    print(f"saved {best} -> models/diagnosis.joblib")

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    lines = ["# Diagnosis model report", "",
             f"Training rows: {len(train)} (random cities). Validation: {len(val)}. "
             f"Held-out cities: {len(test)}. Station Road (never trained on): {len(station)}.", "",
             "## Summary", "", summary.to_markdown(index=False), "",
             f"Version used by the agent: **{best}** (LWM is part of the design; the others are comparisons).", ""]
    for r in reports:
        if r.dataset == "validation":
            continue
        lines += [f"## {r.variant} on {r.dataset}", "", r.per_class.to_markdown(), "", r.confusion.to_markdown(), ""]
        plot_confusion(r, out / f"confusion_{r.variant.replace('+', '_')}_{r.dataset.replace(' ', '_')}.png")
    (out / "diagnosis_report.md").write_text("\n".join(lines))
    print(f"report: {out / 'diagnosis_report.md'}")


if __name__ == "__main__":
    main()
