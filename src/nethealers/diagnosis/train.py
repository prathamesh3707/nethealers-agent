"""Train and grade the diagnosis classifier.

Three versions are compared on cities they never saw and on Station Road:

- plain: features built from what the network reports
- plain + LWM: the same plus LWM's 64-number fingerprint (now, and its change)
- LWM only: the fingerprint alone, to see what it carries by itself

The model is a gradient-boosted tree ensemble (scikit-learn). Its
confidence is then calibrated, so "90% sure" means right about 90% of the
time; the agent relies on that to choose between acting and asking a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import GroupShuffleSplit

from ..sim.config import LABELS
from .features import feature_columns, lwm_columns

VARIANTS = ("plain", "plain+lwm", "lwm_only")


def columns_for(df: pd.DataFrame, variant: str) -> list[str]:
    if variant == "plain":
        return feature_columns(df)
    if variant == "plain+lwm":
        return feature_columns(df) + lwm_columns(df)
    if variant == "lwm_only":
        return lwm_columns(df)
    raise ValueError(variant)


def split_by_episode(df: pd.DataFrame, seed: int = 0):
    """70 / 15 / 15 split where every episode (a whole city) lands in one part only."""
    groups = df.episode.values
    outer = GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=seed)
    train_idx, rest_idx = next(outer.split(df, groups=groups))
    rest = df.iloc[rest_idx]
    inner = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=seed + 1)
    val_i, test_i = next(inner.split(rest, groups=rest.episode.values))
    return df.iloc[train_idx], rest.iloc[val_i], rest.iloc[test_i]


@dataclass
class Model:
    variant: str
    columns: list[str]
    classes: list[str]
    estimator: object  # calibrated classifier

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict_proba(df[self.columns])

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Most likely cause and its calibrated confidence."""
        p = self.predict_proba(df)
        return np.asarray(self.classes)[p.argmax(1)], p.max(1)


def fit(train: pd.DataFrame, val: pd.DataFrame, variant: str, seed: int = 0) -> Model:
    cols = columns_for(train, variant)
    base = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
        class_weight="balanced", early_stopping=True, validation_fraction=0.1, random_state=seed,
    )
    base.fit(train[cols], train.label)
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="isotonic")
    calibrated.fit(val[cols], val.label)
    return Model(variant, cols, list(calibrated.classes_), calibrated)


def expected_calibration_error(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(ece)


@dataclass
class Report:
    variant: str
    dataset: str
    n: int
    accuracy: float
    macro_f1: float
    per_class: pd.DataFrame
    confusion: pd.DataFrame
    ece: float
    confident: dict = field(default_factory=dict)  # threshold -> (share of cases, accuracy on them)


def evaluate(model: Model, df: pd.DataFrame, dataset: str) -> Report:
    pred, conf = model.predict(df)
    y = df.label.values
    labels = [c for c in LABELS if c in set(y) | set(pred)]
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=labels, zero_division=0)
    per_class = pd.DataFrame({"precision": p, "recall": r, "f1": f, "count": s}, index=labels).round(3)
    cm = pd.DataFrame(confusion_matrix(y, pred, labels=labels), index=[f"true {c}" for c in labels],
                      columns=[f"said {c}" for c in labels])
    correct = pred == y
    confident = {}
    for t in (0.7, 0.9):
        m = conf >= t
        confident[t] = (float(m.mean()), float(correct[m].mean()) if m.any() else float("nan"))
    return Report(model.variant, dataset, len(df), float(accuracy_score(y, pred)),
                  float(f1_score(y, pred, labels=labels, average="macro", zero_division=0)), per_class, cm,
                  expected_calibration_error(conf, correct), confident)
