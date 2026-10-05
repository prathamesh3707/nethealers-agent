"""Turn what the network can see into numbers a classifier can use.

Only observable quantities go in: what phones report (strength per beam and
per tower, clarity, quality), what towers know (load, number of phones,
handovers) and rough phone positions for neighbourhood context. Nothing
from the simulator's hidden truth (`true_*` columns, problem records).

Every feature compares "now" with a baseline from just before, because a
cause shows up as a *change*: a bus makes the serving signal fall while
interference stays put; a noisy neighbour makes interference rise while the
serving signal stays put; congestion leaves signal alone but halves data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..sim.world import StepResult, World

BASE_COLS = ["sinr_db", "rsrp_dbm", "beam_rsrp_dbm", "nbr_rsrp_dbm", "rsrq_db", "throughput_mbps", "tower_load"]


def _derived(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["sinr"] = df.sinr_db
    out["rsrp"] = df.rsrp_dbm
    out["beam_rsrp"] = df.beam_rsrp_dbm
    out["nbr_rsrp"] = df.nbr_rsrp_dbm
    out["rsrq"] = df.rsrq_db
    out["sat"] = (df.throughput_mbps / df.demand_mbps).clip(upper=1.0)
    out["load"] = df.tower_load
    out["beam_gap"] = df.rsrp_dbm - df.beam_rsrp_dbm  # best beam minus the beam in use
    out["margin"] = df.rsrp_dbm - df.nbr_rsrp_dbm  # serving cell minus best neighbour
    out["interf"] = df.beam_rsrp_dbm - df.sinr_db  # estimated interference + noise (dBm per RE)
    return out


def phone_features(world: World, base_frames: list[pd.DataFrame], base_result: StepResult) -> pd.DataFrame:
    """Features for every phone that existed before the change. Index = phone id.

    base_frames: snapshots from the ticks before the change; base_result: the last of those ticks.
    """
    now_df = world.snapshot().set_index("ue")
    base_all = pd.concat(base_frames)
    base_ids = base_frames[-1].ue.tolist()
    now_df = now_df.loc[[u for u in base_ids if u in now_df.index]]

    base_mean = base_all.groupby("ue")[BASE_COLS + ["demand_mbps"]].mean().loc[now_df.index]
    base_last = base_frames[-1].set_index("ue").loc[now_df.index]

    now = _derived(now_df)
    base = _derived(base_mean)
    feats = now.copy()
    for c in now.columns:
        feats[f"{c}_base"] = base[c]
        feats[f"d_{c}"] = now[c] - base[c]

    feats["handover"] = (now_df.serving.values != base_last.serving.values).astype(float)
    feats["beam_switched"] = (now_df.beam.values != base_last.beam.values).astype(float)

    # Per-tower strength reports: did the old serving tower fade? Did some other tower get louder?
    r = world.last
    idx_now = world.ue_index()
    rows_now = np.array([idx_now[u] for u in now_df.index])
    cell_now = r.rsrp_beam_dbm.max(axis=1)[:, rows_now]  # (T, N)
    base_index = {u: i for i, u in enumerate(base_ids)}
    rows_base = np.array([base_index[u] for u in now_df.index])
    cell_base = base_result.rsrp_beam_dbm.max(axis=1)[:, rows_base]
    rise = cell_now - cell_base
    serving_now = now_df.serving.values.astype(int)
    serving_base = base_last.serving.values.astype(int)
    cols = np.arange(len(rows_now))
    feats["old_serving_change"] = rise[serving_base, cols]
    other = rise.copy()
    other[serving_now, cols] = -np.inf
    feats["max_other_rise"] = other.max(axis=0)
    feats["mean_tower_change"] = rise.mean(axis=0)

    # Shape of the beam reports from the serving tower.
    beams = r.rsrp_beam_dbm[serving_now, :, rows_now]  # (N, B)
    top = np.sort(beams, axis=1)[:, ::-1]
    feats["top2_gap"] = top[:, 0] - top[:, 1]
    feats["beams_within_3db"] = (beams >= top[:, :1] - 3).sum(axis=1)

    # Neighbourhood context: is this phone alone, its street corner, its tower, or everyone?
    dropped = (feats.d_sinr <= -3).values
    unmet = (feats.sat < 0.8).values
    xy = now_df[["x", "y"]].values
    dist = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
    near = (dist < 30) & ~np.eye(len(xy), dtype=bool)
    n_near = near.sum(axis=1)
    feats["near_phones"] = n_near
    feats["near_drop_share"] = np.where(n_near > 0, (near & dropped[None, :]).sum(axis=1) / np.maximum(n_near, 1), 0)
    same = serving_now[:, None] == serving_now[None, :]
    n_same = same.sum(axis=1)
    feats["tower_drop_share"] = (same & dropped[None, :]).sum(axis=1) / n_same
    feats["tower_unmet_share"] = (same & unmet[None, :]).sum(axis=1) / n_same
    feats["all_drop_share"] = dropped.mean()

    # Phones attached to each tower, now vs before (a crowd shows up as new attachments).
    all_now = world.snapshot()
    count_now = all_now.serving.value_counts()
    count_base = base_frames[-1].serving.value_counts()
    feats["tower_phones"] = [count_now.get(s, 0) for s in serving_now]
    feats["d_tower_phones"] = [count_now.get(s, 0) - count_base.get(s, 0) for s in serving_now]
    return feats


def feature_columns(df: pd.DataFrame) -> list[str]:
    meta = {"label", "episode", "world", "kind", "ticks_after", "ue", "affected", "split", "fixable"}
    return [c for c in df.columns if c not in meta and not c.startswith("lwm")]


def lwm_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("lwm")]
