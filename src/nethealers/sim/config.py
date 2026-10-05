"""Radio settings and physical constants for the simplified signal model.

Numbers follow 3GPP TR 38.901 (urban micro, "UMi street canyon") and common
28 GHz (FR2) evaluation assumptions. Every value is a modelling choice kept
in one place, so changing it here changes the whole simulator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SPEED_OF_LIGHT = 299_792_458.0


@dataclass(frozen=True)
class RadioConfig:
    carrier_ghz: float = 28.0
    bandwidth_mhz: float = 100.0
    subcarrier_khz: float = 120.0
    n_rb: int = 66  # TS 38.101-2: 100 MHz channel at 120 kHz subcarrier spacing
    noise_figure_db: float = 10.0  # typical FR2 phone receiver
    thermal_dbm_per_hz: float = -174.0
    ue_gain_dbi: float = 0.0
    overhead: float = 0.8  # share of resources that carry user data
    shannon_efficiency: float = 0.75  # real links reach ~75% of the Shannon bound
    max_spectral_efficiency: float = 7.4  # bits/s/Hz, about 256-QAM
    min_sinr_db: float = -10.0  # below this the link carries no data
    idle_activity: float = 0.05  # a tower with no data still sends sync and control
    scatter_extra_db: float = 10.0  # diffuse "everything else" path sits this far below 3GPP NLOS

    @property
    def n_subcarriers(self) -> int:
        return 12 * self.n_rb

    @property
    def noise_dbm_per_re(self) -> float:
        return self.thermal_dbm_per_hz + 10 * math.log10(self.subcarrier_khz * 1e3) + self.noise_figure_db

    @property
    def data_bandwidth_hz(self) -> float:
        return self.bandwidth_mhz * 1e6 * self.overhead

    def per_re_dbm(self, total_dbm: float) -> float:
        """Spread a tower's total transmit power evenly over all subcarriers."""
        return total_dbm - 10 * math.log10(self.n_subcarriers)


@dataclass(frozen=True)
class PanelConfig:
    """Tower antenna panel: 3GPP TR 38.901 element pattern in an 8 x 8 array."""

    element_gain_dbi: float = 8.0
    element_hpbw_deg: float = 65.0
    element_max_atten_db: float = 30.0
    n_horizontal: int = 8
    n_vertical: int = 8
    n_beams: int = 16
    beam_span_deg: float = 112.0  # beams cover -56 to +56 degrees around boresight


@dataclass(frozen=True)
class MobilityConfig:
    a3_offset_db: float = 3.0  # neighbour must beat the serving cell by this much
    time_to_trigger: int = 2  # ...for this many consecutive ticks
    beam_switch_margin_db: float = 1.0  # built-in beam management switches only if better by this


@dataclass(frozen=True)
class RealismConfig:
    """Effects that exist only in the "real" world, never in the agent's twin."""

    # TR 38.901 uses 4 dB for UMi LOS, but that also covers geometry a statistical model leaves out.
    # Our street geometry is explicit, so only the leftover unevenness remains.
    shadowing_std_db: float = 2.5
    shadowing_grid_m: float = 15.0
    rsrp_noise_db: float = 1.0  # measurement error on reported strength
    sinr_noise_db: float = 1.0  # measurement error on reported clarity


# Reflection loss at 28 GHz, rough values from mmWave measurement literature.
MATERIAL_REFLECTION_LOSS_DB = {
    "metal": 1.0,
    "glass": 4.0,
    "concrete": 7.0,
    "brick": 9.0,
}

# Size (length, width, height in metres) and loss through the object at 28 GHz.
BLOCKER_TYPES = {
    "bus": {"size": (14.0, 2.6, 3.4), "loss_db": 25.0},
    "truck": {"size": (9.0, 2.5, 4.0), "loss_db": 30.0},
    "car": {"size": (4.5, 1.8, 1.5), "loss_db": 15.0},
    "crowd": {"size": (10.0, 6.0, 1.8), "loss_db": 20.0},
    "kiosk": {"size": (3.0, 2.0, 2.6), "loss_db": 20.0},
    "hoarding": {"size": (8.0, 0.5, 6.0), "loss_db": 30.0},
}

LABELS = ("none", "blockage", "wrong_beam", "interference", "congestion")
