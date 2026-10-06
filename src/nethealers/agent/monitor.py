"""Monitoring: notice phones whose service just got worse, and group them into incidents.

Uses only what phones report. Each phone has a "healthy baseline" (a slow
average of its clarity and data rate) that is updated only while it's fine
and not part of an incident, so a long outage doesn't become the new normal.
A phone is flagged when it stays degraded for two ticks in a row; phones with
out-of-date reports are never flagged, because acting on stale evidence is
how automated systems make things worse.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..sim.world import StepResult, World

DROP_DB = 4.0  # clarity this much below the phone's own normal
POOR_DB = 0.0  # or below this outright...
MIN_BASE_FOR_POOR = 3.0  # ...when it used to be at least this good
LOW_SATISFACTION = 0.8  # or getting less than 80% of the data it wants...
GOOD_SATISFACTION = 0.95  # ...when it used to get almost all of it
GOOD_DB = 13.0  # a drop only matters once a phone falls below "good"
PERSIST_TICKS = 2
WARMUP_TICKS = 5  # learn each phone's normal before judging it
EMA = 0.3
EMA_UP = 0.02  # "normal" rises slowly: a temporary improvement (a neighbour briefly louder) mustn't become the
               # reference that later makes the phone's ordinary level look like a drop


@dataclass
class Flagged:
    phones: list[int]
    first_tick: int
    stale_ignored: list[int] = field(default_factory=list)


class Monitor:
    def __init__(self, history: int = 12):
        self.frames: deque[pd.DataFrame] = deque(maxlen=history)
        self.results: deque[StepResult] = deque(maxlen=history)
        self.base_sinr: dict[int, float] = {}
        self.base_sat: dict[int, float] = {}
        self.streak: dict[int, int] = {}
        self.first_bad: dict[int, int] = {}
        self.seen: dict[int, int] = {}

    def observe(self, world: World, busy_phones: set[int]) -> Flagged:
        """Record this tick. Return phones newly and persistently degraded (not already in an incident)."""
        df = world.snapshot()
        self.frames.append(df)
        self.results.append(world.last)
        sat = (df.throughput_mbps / df.demand_mbps).clip(upper=1.0)
        new, stale = [], []
        for uid, sinr, s, age in zip(df.ue, df.sinr_db, sat, df.report_age):
            uid = int(uid)
            self.seen[uid] = self.seen.get(uid, 0) + 1
            if age > 0:
                stale.append(uid)
                self.streak[uid] = 0
                continue
            b_sinr, b_sat = self.base_sinr.get(uid), self.base_sat.get(uid)
            bad = False
            if b_sinr is not None and self.seen[uid] > WARMUP_TICKS:
                bad |= sinr <= b_sinr - DROP_DB and sinr < GOOD_DB
                bad |= sinr < POOR_DB and b_sinr >= MIN_BASE_FOR_POOR
            if b_sat is not None and self.seen[uid] > WARMUP_TICKS:
                bad |= s < LOW_SATISFACTION and b_sat >= GOOD_SATISFACTION
            if b_sinr is None and s < LOW_SATISFACTION and self.seen[uid] > PERSIST_TICKS:
                bad = True  # a newcomer that can't get service
            if bad:
                self.streak[uid] = self.streak.get(uid, 0) + 1
                self.first_bad.setdefault(uid, world.tick)
                if self.streak[uid] >= PERSIST_TICKS and uid not in busy_phones:
                    new.append(uid)
            else:
                self.streak[uid] = 0
                self.first_bad.pop(uid, None)
                if uid not in busy_phones:
                    k = EMA_UP if (b_sinr is not None and sinr > b_sinr and self.seen[uid] > WARMUP_TICKS) else EMA
                    self.base_sinr[uid] = sinr if b_sinr is None else (1 - k) * b_sinr + k * sinr
                    self.base_sat[uid] = s if b_sat is None else (1 - EMA) * b_sat + EMA * s
        first = min((self.first_bad[u] for u in new), default=world.tick)
        return Flagged(new, first, stale)

    def baseline_window(self, before_tick: int, n: int = 3) -> tuple[list[pd.DataFrame], StepResult] | None:
        """The last `n` snapshots (and the matching StepResult) strictly before `before_tick`."""
        frames = [f for f in self.frames if len(f) and int(f.tick.iloc[0]) < before_tick]
        results = [r for r in self.results if r.tick < before_tick]
        if not frames or not results:
            return None
        return frames[-n:], results[-1]

    def latest(self) -> pd.DataFrame:
        return self.frames[-1]

    def healthy(self, uid: int, sinr: float, sat: float, margin_db: float = 3.0) -> bool:
        b_sinr, b_sat = self.base_sinr.get(uid), self.base_sat.get(uid)
        ok_sinr = b_sinr is None or sinr >= b_sinr - margin_db or sinr >= 13
        ok_sat = sat >= GOOD_SATISFACTION or (b_sat is not None and b_sat < GOOD_SATISFACTION)
        return bool(ok_sinr and ok_sat)


def group_phones(df: pd.DataFrame, phones: list[int], radius: float = 40.0) -> list[list[int]]:
    """Split flagged phones into incidents: phones close together or on the same tower and nearby."""
    if not phones:
        return []
    sub = df.set_index("ue").loc[phones]
    xy = sub[["x", "y"]].to_numpy()
    tower = sub.serving.to_numpy()
    d = np.linalg.norm(xy[:, None] - xy[None], axis=2)
    linked = (d < radius) | ((tower[:, None] == tower[None]) & (d < 2.5 * radius))
    groups, seen = [], set()
    for i in range(len(phones)):
        if i in seen:
            continue
        stack, comp = [i], []
        seen.add(i)
        while stack:
            j = stack.pop()
            comp.append(phones[j])
            for k in np.nonzero(linked[j])[0]:
                if k not in seen:
                    seen.add(int(k))
                    stack.append(int(k))
        groups.append(sorted(comp))
    return groups
