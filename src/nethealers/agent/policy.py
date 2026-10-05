"""The operator's policy (config/policy.yaml) as a typed object."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "config" / "policy.yaml"


@dataclass(frozen=True)
class Policy:
    power_step_db: float = 3.0
    power_total_db: float = 6.0
    tilt_step_deg: float = 2.0
    tilt_total_deg: float = 4.0
    rebalance_step_db: float = 6.0
    rebalance_total_db: float = 8.0
    handover_max_phones: int = 30
    cooldown_ticks: dict = field(default_factory=lambda: {"power": 10, "tilt": 10, "rebalance": 10, "beam": 3,
                                                          "handover": 2})
    max_harmed_phones: int = 2
    min_median_change_db: float = -1.0
    min_predicted_gain_db: float = 2.0
    twin_error_margin: float = 0.3
    max_report_age: int = 1
    act_alone: float = 0.8
    act_small: float = 0.6
    beam_override_auto: bool = True
    handover_auto: bool = True
    power_auto_db: float = 1.0
    tilt_auto_deg: float = 1.0
    rebalance_auto_db: float = 3.0
    verify_ticks: int = 3
    keep_if_share_of_prediction: float = 0.4
    max_attempts: int = 3

    @classmethod
    def load(cls, path: Path = DEFAULT_POLICY) -> "Policy":
        d = yaml.safe_load(Path(path).read_text())
        lim, col, gain = d["limits"], d["collateral"], d["gain"]
        conf, auto, ver = d["confidence"], d["autonomy"], d["verify"]
        return cls(
            power_step_db=lim["power_step_db"], power_total_db=lim["power_total_db"],
            tilt_step_deg=lim["tilt_step_deg"], tilt_total_deg=lim["tilt_total_deg"],
            rebalance_step_db=lim["rebalance_step_db"], rebalance_total_db=lim["rebalance_total_db"],
            handover_max_phones=lim["handover_max_phones"], cooldown_ticks=dict(d["cooldown_ticks"]),
            max_harmed_phones=col["max_harmed_phones"], min_median_change_db=col["min_median_change_db"],
            min_predicted_gain_db=gain["min_predicted_db"], twin_error_margin=gain["twin_error_margin"],
            max_report_age=d["evidence"]["max_report_age"], act_alone=conf["act_alone"], act_small=conf["act_small"],
            beam_override_auto=auto["beam_override"] == "auto", handover_auto=auto["handover"] == "auto",
            power_auto_db=auto["power_auto_db"], tilt_auto_deg=auto["tilt_auto_deg"],
            rebalance_auto_db=auto["rebalance_auto_db"], verify_ticks=ver["ticks"],
            keep_if_share_of_prediction=ver["keep_if_share_of_prediction"], max_attempts=ver["max_attempts"],
        )
