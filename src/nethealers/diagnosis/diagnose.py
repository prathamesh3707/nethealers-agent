"""The diagnosis step the agent calls: which phones are in trouble, and why.

    d = Diagnoser.load()
    report = d.diagnose(world, base_frames, base_result)

`report` has one row per phone: the most likely cause, its calibrated
confidence, and the probability of every cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ..sim.world import StepResult, World
from .features import phone_features
from .train import Model

DEFAULT_MODEL = Path(__file__).resolve().parents[3] / "models" / "diagnosis.joblib"


@dataclass
class Diagnoser:
    model: Model
    lwm: object | None = None

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL) -> "Diagnoser":
        model: Model = joblib.load(path)
        lwm = None
        if any(c.startswith("lwm") for c in model.columns):
            from .lwm import load_model

            lwm = load_model()
        return cls(model, lwm)

    def diagnose(self, world: World, base_frames: list[pd.DataFrame], base_result: StepResult,
                 phones: list[int] | None = None) -> pd.DataFrame:
        feats = phone_features(world, base_frames, base_result)
        if phones is not None:
            feats = feats.loc[[p for p in phones if p in feats.index]]
        feats = feats.reset_index().rename(columns={"index": "ue"})
        if self.lwm is not None and len(feats):
            feats = self._add_lwm(feats, world, base_result)
        proba = self.model.predict_proba(feats)
        classes = np.asarray(self.model.classes)
        out = pd.DataFrame({"ue": feats.ue.values, "cause": classes[proba.argmax(1)], "confidence": proba.max(1)})
        for i, c in enumerate(classes):
            out[f"p_{c}"] = proba[:, i]
        return out.set_index("ue")

    def _add_lwm(self, feats: pd.DataFrame, world: World, base_result: StepResult) -> pd.DataFrame:
        from .lwm import lwm_features

        return pd.concat([feats.reset_index(drop=True),
                          lwm_features(self.lwm, world, base_result, list(feats.ue))], axis=1)
