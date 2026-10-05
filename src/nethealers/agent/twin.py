"""Building the twin the agent rehearses on.

Three layers, each from information a real operator would have:

1. The plain twin: building map and network settings (`world.twin()`).
2. Calibration: phones report how strong every tower is. Comparing the
   twin's prediction with what phones reported *before* the incident gives
   a correction per tower and phone, which soaks up things the map doesn't
   know (uneven loss, an unmapped kiosk).
3. The incident hypothesis: what changed since then. A tower that got
   much weaker for a phone gets that much extra loss on its paths (that is
   what a blocker looks like from outside); clarity that is worse than the
   twin can explain becomes extra interference (e.g. an unknown booster).
   Settings faults (a misconfigured tower) need no guess: the twin already
   has the settings.

`TwinTrust` keeps a running error per tower: how far real results landed
from the twin's predictions. The rule-checker asks for a bigger predicted
gain where the twin has been wrong before.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..sim.world import StepResult, World

MEASURABLE_DBM = -115.0
MAX_CALIBRATION_DB = 8.0
DROP_FOR_HYPOTHESIS_DB = 3.0
UNEXPLAINED_SINR_DB = 3.0


def calibration_offsets(twin: World, base: StepResult) -> dict[tuple[int, int], float]:
    """Extra loss per (tower, phone) that makes the twin match pre-incident reports."""
    ref = twin.copy()
    for t in ref.towers:
        t.power_dbm = float(base.tower_power_dbm[t.id])
        t.tilt_deg = float(base.tower_tilt_deg[t.id])
    ref.loss_offset_db, ref.extra_interference_mw = {}, {}
    pred = 10 * np.log10(np.maximum(ref.received_power(ref.trace()).max(axis=1), 1e-30))  # (T, U)
    obs = base.rsrp_beam_dbm.max(axis=1)  # (T, U_base)
    base_pos = {int(u): j for j, u in enumerate(base.ue_ids)}
    out = {}
    for i, u in enumerate(ref.ues):
        j = base_pos.get(u.id)
        if j is None:
            continue
        for t in range(len(ref.towers)):
            if obs[t, j] > MEASURABLE_DBM:
                out[(t, u.id)] = float(np.clip(pred[t, i] - obs[t, j], -MAX_CALIBRATION_DB, MAX_CALIBRATION_DB))
    return out


def build_twin(real: World, base: StepResult, phones: list[int]) -> tuple[World, dict]:
    """The calibrated twin with the incident hypothesis for `phones`. Returns (twin, notes)."""
    tw = real.twin()
    offsets = calibration_offsets(tw, base)
    notes = {"calibrated_links": len(offsets), "assumed_extra_loss": {}, "assumed_interference": {}}

    obs_base = base.rsrp_beam_dbm.max(axis=1)
    obs_now = real.last.rsrp_beam_dbm.max(axis=1)
    base_pos = {int(u): j for j, u in enumerate(base.ue_ids)}
    idx = real.ue_index()
    for uid in phones:
        j, i = base_pos.get(uid), idx.get(uid)
        if j is None or i is None:
            continue
        for t in range(len(real.towers)):
            drop = obs_base[t, j] - obs_now[t, i]
            if drop > DROP_FOR_HYPOTHESIS_DB and obs_base[t, j] > MEASURABLE_DBM:
                offsets[(t, uid)] = offsets.get((t, uid), 0.0) + float(drop)
                notes["assumed_extra_loss"][(t, uid)] = round(float(drop), 1)
    tw.loss_offset_db = offsets

    # Clarity still worse than the twin can explain: assume extra interference at that phone.
    probe = tw.copy()
    probe.step()
    r = probe.last
    noise = 10 ** (real.radio.noise_dbm_per_re / 10)
    seen = real.snapshot().set_index("ue")
    p_idx = probe.ue_index()
    for uid in phones:
        if uid not in seen.index or uid not in p_idx:
            continue
        i = p_idx[uid]
        twin_sinr = float(r.sinr_db[i])
        obs_sinr = float(seen.loc[uid, "sinr_db"])
        if twin_sinr - obs_sinr > UNEXPLAINED_SINR_DB:
            signal = r.rx_mw[r.serving[i], r.beam[i], i]
            needed = signal / 10 ** (obs_sinr / 10) - noise
            extra = needed - r.interference_mw[i]
            if extra > 0:
                tw.extra_interference_mw[uid] = float(extra)
                notes["assumed_interference"][uid] = round(twin_sinr - obs_sinr, 1)
    return tw, notes


@dataclass
class TwinTrust:
    """Running prediction error per tower (dB). Starts cautious."""

    initial_db: float = 2.0
    weight: float = 0.4
    max_step_db: float = 8.0  # one wild miss (say, a bus that moved) shouldn't freeze the agent
    error: dict[int, float] = field(default_factory=dict)

    def get(self, tower: int) -> float:
        return self.error.get(tower, self.initial_db)

    def update(self, tower: int, predicted_db: float, measured_db: float) -> float:
        err = min(abs(predicted_db - measured_db), self.max_step_db)
        self.error[tower] = (1 - self.weight) * self.get(tower) + self.weight * err
        return self.error[tower]
