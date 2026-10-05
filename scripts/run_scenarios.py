"""Run the six scenarios with every method over several seeds and write the evaluation report.

    uv run python scripts/run_scenarios.py              # 8 seeds, half the cores
    uv run python scripts/run_scenarios.py --seeds 3    # quick look

Writes out/scenarios.json (raw), docs/evaluation_report.md and docs/eval_timeline.png.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nethealers.eval.controllers import METHODS  # noqa: E402
from nethealers.eval.runner import run_one  # noqa: E402
from nethealers.eval.scenarios import LENGTH, SCENARIOS, START  # noqa: E402

METHOD_NAMES = {
    "no_action": "No action at all", "standard": "Network alone", "rule_based": "Simple rule fixer",
    "agent_no_twin": "Agent, no twin", "agent": "Agent (full)",
}
COLORS = {"no_action": "#9AB2BB", "standard": "#4A6470", "rule_based": "#D89A12", "agent_no_twin": "#7FB8BF",
          "agent": "#0F7C86"}


def _job(args):
    return run_one(*args)


def collateral(results: list[dict]) -> dict:
    """Phone-seconds a method made worse than the network alone did (same street, same seed)."""
    std = {(r["scenario"], r["seed"]): r["degraded_sets"] for r in results if r["method"] == "standard"}
    out = {}
    for r in results:
        ref = std.get((r["scenario"], r["seed"]))
        if ref is None or r["method"] == "standard":
            continue
        extra = 0
        for t, phones in r["degraded_sets"].items():
            if int(t) >= START:
                extra += len(set(phones) - set(ref.get(t, ref.get(str(t), []))))
        out[(r["scenario"], r["method"], r["seed"])] = extra
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    args = ap.parse_args()
    jobs = [(s.key, m, seed) for s in SCENARIOS for m in METHODS for seed in range(1, args.seeds + 1)]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_job, jobs, chunksize=2))
    print(f"{len(jobs)} runs in {time.time() - t0:.0f}s")

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "scenarios.json").write_text(json.dumps(results, default=lambda o: o.item() if hasattr(o, "item") else str(o)))

    coll = collateral(results)
    rows = []
    for r in results:
        rows.append({k: v for k, v in r.items() if k not in ("per_tick", "degraded_sets", "events")}
                    | {"collateral": coll.get((r["scenario"], r["method"], r["seed"]), 0)})
    df = pd.DataFrame(rows)

    def agg(g):
        rec = g.recovery_s.dropna()
        d = {
            "degraded phone-s": round(g.degraded_phone_seconds.mean(), 1),
            "recovered": f"{g.recovered.mean():.0%}",
            "median recovery s": float(rec.median()) if len(rec) else None,
            "still degraded at end": round(g.still_degraded_at_end.mean(), 1),
            "after it ends (phone-s)": round(g.aftermath_phone_seconds.mean(), 1),
            "made worse (phone-s)": round(g.collateral.mean(), 1),
            "changes made": round(g.actions.mean(), 1),
            "safety breaks": int(g.limit_violations.sum() + g.zone_violations.sum()),
        }
        if "undos" in g and g.undos.notna().any():
            d.update({
                "undone": round(g.undos.mean(), 1), "asked a person": round(g.escalations.mean(), 1),
                "false alarms": round(g.false_alarms.mean(), 1),
                "diagnosis right": f"{g.diagnosis_correct.mean():.0%}",
                "twin error dB": round(float(g.twin_error_db.mean()), 1) if g.twin_error_db.notna().any() else None,
            })
        d["decision ms (max)"] = round(g.max_decision_ms.mean(), 0)
        return pd.Series(d)

    summary = pd.DataFrame([{"scenario": k[0], "method": k[1], **agg(g).to_dict()}
                            for k, g in df.groupby(["scenario", "method"], sort=False)])
    summary["method"] = summary.method.map(METHOD_NAMES)
    print(summary.to_string(index=False))

    # Timeline plot: degraded phones per tick, averaged over seeds.
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex=True)
    for ax, sc in zip(axes.ravel(), SCENARIOS):
        for m in METHODS:
            series = np.array([r["per_tick"] for r in results if r["scenario"] == sc.key and r["method"] == m])
            if len(series):
                ax.plot(range(1, LENGTH + 1), series.mean(axis=0), label=METHOD_NAMES[m], color=COLORS[m],
                        lw=2.4 if m == "agent" else 1.4)
        ax.axvline(START, color="#C7412F", ls=":", lw=1)
        ax.set_title(sc.title, fontsize=10)
        ax.set_ylabel("degraded phones")
        ax.grid(alpha=0.3)
    axes[1, 0].set_xlabel("seconds")
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(f"Phones with degraded service over time (mean of {args.seeds} seeds; problem starts at the red line)")
    fig.tight_layout()
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    fig.savefig(docs / "eval_timeline.png", dpi=120)

    lines = ["# Evaluation: six scenarios, five methods", "",
             f"Station Road, {args.seeds} seeds per scenario (phone positions and details vary by seed). "
             f"Problems start at second {START}; each run lasts {LENGTH} s. Scored against the simulator's hidden "
             "truth: a phone is degraded when its true clarity is 4 dB below its own normal and below 13 dB, or "
             "it gets under 80% of the data it wants.", "",
             "- **degraded phone-s**: phones degraded x seconds while the problem lasts (lower is better)",
             "- **after it ends**: degraded phone-seconds once a temporary cause (the bus) has gone; leftover "
             "changes that are never withdrawn show up here",
             "- **made worse**: phone-seconds degraded under this method but not under the network alone",
             "- **safety breaks**: an independent audit of limits and the protected hospital zone",
             "- **asked a person**: escalations, including approval requests (a simulated operator approves "
             "after 5 s)", "",
             "![timeline](eval_timeline.png)", ""]
    for sc in SCENARIOS:
        part = summary[summary.scenario == sc.key].drop(columns="scenario").dropna(axis=1, how="all")
        lines += [f"## {sc.title}", "", part.to_markdown(index=False), ""]
    (docs / "evaluation_report.md").write_text("\n".join(lines))
    print(f"report: {docs / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
