"""Step 1 demo: the Station Road street, every problem type, the five fixes, and the twin gap.

Run:  uv run python scripts/step1_demo.py
Pictures land in out/.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from nethealers.sim import (  # noqa: E402
    BeamOverride,
    Handover,
    LoadRebalance,
    PowerChange,
    TiltChange,
    add_blocker,
    add_external_interferer,
    apply_action,
    crowd_surge,
    describe,
    misconfigure_tower,
    station_road,
    stick_beams,
)
from nethealers.sim.layouts import BUS_POSITION  # noqa: E402
from nethealers.sim.viz import plot_3d, plot_map  # noqa: E402

OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)


def median_sinr(df, ids):
    return float(df.set_index("ue").loc[ids].true_sinr_db.median())


def section(title):
    print(f"\n=== {title} ===")


def main():
    section("Normal day on Station Road")
    w = station_road()
    base = w.run(4)
    print(w.tower_summary().to_string(index=False))
    bands = np.select([base.true_sinr_db < 0, base.true_sinr_db < 13], ["poor", "fair"], "good")
    names, counts = np.unique(bands, return_counts=True)
    print("Phones by signal clarity:", {str(n): int(c) for n, c in zip(names, counts)})
    plot_map(w, str(OUT / "1_normal_day.png"), show_links=True, title="Station Road: normal day")
    plot_3d(w, str(OUT / "1_normal_day_3d.png"))

    section("A bus stops in front of the bus stop")
    bus_stop = base[base.group == "bus_stop"].ue.tolist()
    a_before = 10 * np.log10(w.last.rx_mw[0].max(axis=0))
    add_blocker(w, "bus", *BUS_POSITION)
    first = w.step()
    a_after = 10 * np.log10(w.last.rx_mw[0].max(axis=0))
    idx = w.ue_index()
    drop = np.median([a_after[idx[u]] - a_before[idx[u]] for u in bus_stop])
    print(f"Tower A's signal at the 12 bus-stop phones drops by {abs(drop):.1f} dB (bus loss 25 dB).")
    print(f"Their clarity: {median_sinr(base, bus_stop):.1f} dB before, {median_sinr(first, bus_stop):.1f} dB "
          f"one second after.")
    later = w.run(3)
    moved = int((later.set_index('ue').loc[bus_stop].serving != 0).sum())
    print(f"Built-in handover moves {moved} of them to other towers: clarity {median_sinr(later, bus_stop):.1f} dB.")
    worst = int(first.set_index("ue").loc[bus_stop].true_sinr_db.idxmin())
    plot_map(w, str(OUT / "2_bus_with_handover.png"), highlight_ue=worst,
             title="Bus stops: built-in handover rescues most phones")

    section("Same bus, but Tower A is missing its neighbour links (a real misconfiguration)")
    w = station_road()
    w.missing_relations = {(0, 1), (0, 2)}
    w.run(4)
    add_blocker(w, "bus", *BUS_POSITION)
    stuck = w.run(3)
    poor = stuck[(stuck.group == "bus_stop") & (stuck.true_sinr_db < 0)].ue.tolist()
    print(f"{len(poor)} bus-stop phones stay poor: clarity {median_sinr(stuck, poor):.1f} dB. "
          "Nothing built-in fixes this.")
    plot_map(w, str(OUT / "3_bus_coverage_hole.png"), highlight_ue=poor[0] if poor else None,
             title="Bus + missing neighbour links: a coverage hole")

    section("Rehearsing fixes: blind twin vs twin that knows the bus vs what really happens")
    blind, aware = w.twin(), w.twin(include_dynamic=True)
    fixes = [Handover(tuple(poor), 2), Handover(tuple(poor), 1), PowerChange(0, 3.0), TiltChange(0, -2.0),
             LoadRebalance(0, 2, 6.0)]
    print(f"{'Fix':48s}{'blind twin':>11s}{'aware twin':>11s}{'real':>8s}   (median clarity, dB)")
    for f in fixes:
        res = []
        for world in (blind, aware, w):
            c = world.copy()
            apply_action(c, f)
            res.append(median_sinr(c.run(3), poor))
        print(f"{describe(w, f):48s}{res[0]:11.1f}{res[1]:11.1f}{res[2]:8.1f}")
    print("A twin that doesn't know about the bus trusts the wrong fix. One that does is closer, but not exact:\n"
          "that gap is why the agent checks every result and undoes what falls short.")

    section("Other problem types")
    w = station_road()
    b = w.run(4)
    ids = b[b.group == "bus_stop"].ue.tolist()[:6]
    stick_beams(w, ids, offset=3)
    bad = w.run(2)
    ids = [i for i in ids if w.ue(i).serving == 0]
    best = int(bad.set_index("ue").loc[ids].best_beam.mode()[0])
    apply_action(w, BeamOverride(0, tuple(ids), best))
    good = w.run(2)
    print(f"Wrong beam on {len(ids)} phones: {median_sinr(b, ids):.1f} -> {median_sinr(bad, ids):.1f} dB; "
          f"beam override fixes it: {median_sinr(good, ids):.1f} dB")

    w = station_road()
    b = w.run(4)
    misconfigure_tower(w, 2, 5.0, -6.0)
    bad = w.run(3)
    apply_action(w, PowerChange(2, -5.0))
    apply_action(w, TiltChange(2, 6.0))
    good = w.run(3)
    print(f"Tower C set too loud and tilted up: street median {b.true_sinr_db.median():.1f} -> "
          f"{bad.true_sinr_db.median():.1f} dB; turning it back down: {good.true_sinr_db.median():.1f} dB")

    w = station_road()
    b = w.run(4)
    add_external_interferer(w, 232, 100)
    bad = w.run(2)
    near = b[(abs(b.x - 232) < 25) & (b.group == "bus_stop")].ue.tolist()
    print(f"Illegal booster near the bus stop: {median_sinr(b, near):.1f} -> {median_sinr(bad, near):.1f} dB "
          "(no network setting removes it: the agent must report it to a human)")
    plot_map(w, str(OUT / "4_booster.png"), title="Illegal booster near the bus stop")

    w = station_road()
    b = w.run(4)
    crowd_surge(w, 200, 114, 12, 60, demand_mbps=20)
    bad = w.run(3)
    unmet = int((bad.throughput_mbps < 0.95 * bad.demand_mbps).sum())
    print(f"Crowd of 60 arrives near Tower A: load {w.last.load[0]:.2f} (over 1 = overloaded), "
          f"{unmet} phones get less data than they need")
    plot_map(w, str(OUT / "5_crowd.png"), title="Crowd surge: Tower A overloaded")

    print(f"\nPictures saved in {OUT}")


if __name__ == "__main__":
    main()
