"""Signal paths and received power.

For every tower and phone we find up to three kinds of path:

- direct: the straight line, if no building is in the way. Blockers on the
  line (bus, crowd) subtract their loss.
- reflected: one mirror bounce off a building wall, if both legs are clear
  of buildings. Loses a little extra depending on the wall material.
- scatter: a weak "everything else" floor (diffraction, rough-surface
  scattering), using the 3GPP NLOS formula plus a margin. It keeps values
  finite where no clean path exists.

Path loss follows 3GPP TR 38.901 UMi street canyon. Antenna gain uses the
TR 38.901 element pattern in an 8 x 8 panel steered to one of 16 beams.
Paths add up as power (no phase), which gives stable average values.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np

from .config import SPEED_OF_LIGHT, PanelConfig
from .geometry import Wall, angles_deg, segments_hit_boxes, wrap_deg

DIRECT, REFLECT, SCATTER = 0, 1, 2
PATH_KIND_NAMES = {DIRECT: "direct", REFLECT: "reflected", SCATTER: "scatter"}


def path_loss_los_db(d3d, fc_ghz: float):
    """TR 38.901 Table 7.4.1-1, UMi street canyon, line of sight (PL1)."""
    d = np.maximum(np.asarray(d3d, dtype=float), 1.0)
    return 32.4 + 21.0 * np.log10(d) + 20.0 * np.log10(fc_ghz)


def path_loss_nlos_db(d3d, fc_ghz: float, h_ut: float = 1.5):
    """TR 38.901 Table 7.4.1-1, UMi street canyon, non line of sight."""
    d = np.maximum(np.asarray(d3d, dtype=float), 1.0)
    pl = 35.3 * np.log10(d) + 22.4 + 21.3 * np.log10(fc_ghz) - 0.3 * (h_ut - 1.5)
    return np.maximum(path_loss_los_db(d, fc_ghz), pl)


def element_gain_db(az_local_deg, el_deg, panel: PanelConfig):
    """TR 38.901 Table 7.3-1 antenna element pattern (no mechanical tilt)."""
    theta = 90.0 - np.asarray(el_deg)
    a_v = -np.minimum(12.0 * ((theta - 90.0) / panel.element_hpbw_deg) ** 2, panel.element_max_atten_db)
    a_h = -np.minimum(12.0 * (np.asarray(az_local_deg) / panel.element_hpbw_deg) ** 2, panel.element_max_atten_db)
    return panel.element_gain_dbi - np.minimum(-(a_v + a_h), panel.element_max_atten_db)


def ula_gain(n: int, du):
    """Array gain of n half-wavelength-spaced elements, steered with direction-sine offset du. Peak = n."""
    x = np.pi * np.asarray(du) / 2.0
    num = np.sin(n * x)
    den = np.sin(x)
    small = np.abs(den) < 1e-9
    g = np.where(small, float(n * n), (num / np.where(small, 1.0, den)) ** 2) / n
    return np.maximum(g, 1e-3)


def panel_gain_db(az_local_deg, el_deg, tilt_deg, beam_az_deg, panel: PanelConfig) -> np.ndarray:
    """Gain (dBi) toward P directions for each of B beams. Returns (P, B).

    az_local_deg, el_deg, tilt_deg: (P,). beam_az_deg: (B,). Electrical downtilt
    steers every beam `tilt_deg` below the horizon.
    """
    az = np.radians(az_local_deg)
    el = np.radians(el_deg)
    tilt = np.radians(tilt_deg)
    baz = np.radians(beam_az_deg)
    u_h = np.sin(az) * np.cos(el)
    u_hb = np.sin(baz)[None, :] * np.cos(tilt)[:, None]
    g_h = ula_gain(panel.n_horizontal, u_h[:, None] - u_hb)
    g_v = ula_gain(panel.n_vertical, np.sin(el) - np.sin(-tilt))
    elem = element_gain_db(az_local_deg, el_deg, panel)
    return elem[:, None] + 10 * np.log10(g_h) + 10 * np.log10(g_v)[:, None]


@dataclass
class Paths:
    """All propagation paths in the street, one entry per path (flat arrays)."""

    tower: np.ndarray
    ue: np.ndarray
    kind: np.ndarray
    wall: np.ndarray  # index into the wall list, -1 if none
    length_m: np.ndarray
    loss_db: np.ndarray  # path loss + reflection loss + blockage (+ shadowing in the real world)
    blockage_db: np.ndarray  # the part of loss_db caused by blockers
    aod_az: np.ndarray  # leaving the tower (degrees, global frame)
    aod_el: np.ndarray
    aoa_az: np.ndarray  # arriving at the phone: direction the signal comes from
    aoa_el: np.ndarray
    via: np.ndarray  # (P, 3) bounce point for reflected paths, NaN otherwise

    @property
    def delay_s(self) -> np.ndarray:
        return self.length_m / SPEED_OF_LIGHT

    def __len__(self) -> int:
        return len(self.tower)

    @staticmethod
    def concat(parts: list["Paths"]) -> "Paths":
        return Paths(**{f.name: np.concatenate([getattr(p, f.name) for p in parts]) for f in fields(Paths)})

    def subset(self, mask) -> "Paths":
        return Paths(**{f.name: getattr(self, f.name)[mask] for f in fields(Paths)})

    @staticmethod
    def empty() -> "Paths":
        z = np.zeros(0)
        zi = np.zeros(0, dtype=int)
        return Paths(zi, zi, zi, zi, z, z, z, z, z, z, z, np.zeros((0, 3)))


def trace_paths(
    tower_pos: np.ndarray,
    ue_pos: np.ndarray,
    opaque: np.ndarray,
    blockers: np.ndarray,
    blocker_loss_db: np.ndarray,
    walls: list[Wall],
    wall_loss_db: np.ndarray,
    fc_ghz: float,
    scatter_extra_db: float,
) -> Paths:
    """Find direct, reflected and scatter paths for every tower-phone pair."""
    n_t, n_u = len(tower_pos), len(ue_pos)
    parts: list[Paths] = []

    def blockage(p0, p1):
        if len(blockers) == 0:
            return np.zeros(len(p0))
        return segments_hit_boxes(p0, p1, blockers).astype(float) @ blocker_loss_db

    # Direct and scatter paths share the same tower-phone pairs.
    ti, ui = np.meshgrid(np.arange(n_t), np.arange(n_u), indexing="ij")
    ti, ui = ti.ravel(), ui.ravel()
    p0, p1 = tower_pos[ti], ue_pos[ui]
    v = p1 - p0
    d = np.linalg.norm(v, axis=1)
    aod_az, aod_el = angles_deg(v)
    aoa_az, aoa_el = angles_deg(-v)
    clear = ~segments_hit_boxes(p0, p1, opaque).any(axis=1) if len(opaque) else np.ones(len(ti), bool)
    blk = blockage(p0, p1)
    nan3 = np.full((len(ti), 3), np.nan)
    parts.append(
        Paths(ti, ui, np.full(len(ti), DIRECT), np.full(len(ti), -1), d,
              path_loss_los_db(d, fc_ghz) + blk, blk, aod_az, aod_el, aoa_az, aoa_el, nan3).subset(clear)
    )
    h_ut = ue_pos[ui, 2]
    parts.append(
        Paths(ti, ui, np.full(len(ti), SCATTER), np.full(len(ti), -1), d,
              path_loss_nlos_db(d, fc_ghz, h_ut) + scatter_extra_db, np.zeros(len(ti)),
              aod_az, aod_el, aoa_az, aoa_el, nan3)
    )

    # One-bounce mirror reflections off building walls.
    if walls:
        axis = np.array([w.axis for w in walls])
        coord = np.array([w.coord for w in walls])
        lo = np.array([w.lo for w in walls])
        hi = np.array([w.hi for w in walls])
        zmin = np.array([w.zmin for w in walls])
        zmax = np.array([w.zmax for w in walls])
        normal = np.array([w.normal for w in walls])
        n_w = len(walls)
        wi_all = np.arange(n_w)
        u_ax = ue_pos[:, axis].T  # (W, U)
        u_front = (u_ax - coord[:, None]) * normal[:, None] > 1e-6
        for t in range(n_t):
            tp = tower_pos[t]
            t_ax = tp[axis]
            t_front = (t_ax - coord) * normal > 1e-6
            img = np.tile(tp, (n_w, 1))
            img[wi_all, axis] = 2 * coord - t_ax
            img_ax = img[wi_all, axis]
            denom = u_ax - img_ax[:, None]
            ok = t_front[:, None] & u_front & (np.abs(denom) > 1e-9)
            s = np.where(ok, (coord[:, None] - img_ax[:, None]) / np.where(ok, denom, 1.0), -1.0)
            pts = img[:, None, :] + s[..., None] * (ue_pos[None, :, :] - img[:, None, :])
            p_other = np.where((1 - axis)[:, None] == 0, pts[..., 0], pts[..., 1])
            ok &= (s > 0) & (s < 1)
            ok &= (p_other >= lo[:, None]) & (p_other <= hi[:, None])
            ok &= (pts[..., 2] >= zmin[:, None]) & (pts[..., 2] <= zmax[:, None])
            wi, uj = np.nonzero(ok)
            if len(wi) == 0:
                continue
            pv = pts[wi, uj].copy()
            pv[np.arange(len(wi)), axis[wi]] = coord[wi]  # sit exactly on the wall plane
            a0 = np.tile(tp, (len(wi), 1))
            a1 = ue_pos[uj]
            if len(opaque):
                hit = segments_hit_boxes(a0, pv, opaque).any(axis=1) | segments_hit_boxes(pv, a1, opaque).any(axis=1)
            else:
                hit = np.zeros(len(wi), bool)
            keep = ~hit
            wi, uj, pv, a0, a1 = wi[keep], uj[keep], pv[keep], a0[keep], a1[keep]
            if len(wi) == 0:
                continue
            blk = blockage(a0, pv) + blockage(pv, a1)
            leg1, leg2 = pv - a0, pv - a1
            length = np.linalg.norm(leg1, axis=1) + np.linalg.norm(leg2, axis=1)
            d_az, d_el = angles_deg(leg1)
            r_az, r_el = angles_deg(leg2)
            loss = path_loss_los_db(length, fc_ghz) + wall_loss_db[wi] + blk
            parts.append(Paths(np.full(len(wi), t), uj, np.full(len(wi), REFLECT), wi, length, loss, blk,
                               d_az, d_el, r_az, r_el, pv))

    return Paths.concat(parts)


def received_power_mw(
    paths: Paths,
    n_towers: int,
    n_ues: int,
    tower_power_re_dbm: np.ndarray,
    tower_boresight_deg: np.ndarray,
    tower_tilt_deg: np.ndarray,
    beam_az_deg: np.ndarray,
    panel: PanelConfig,
    ue_gain_dbi: float,
) -> np.ndarray:
    """Power per resource element (mW) each phone gets from each tower beam. Returns (T, B, U)."""
    n_b = len(beam_az_deg)
    if len(paths) == 0:
        return np.zeros((n_towers, n_b, n_ues))
    t = paths.tower
    az_local = wrap_deg(paths.aod_az - tower_boresight_deg[t])
    gain = panel_gain_db(az_local, paths.aod_el, tower_tilt_deg[t], beam_az_deg, panel)
    rx_db = tower_power_re_dbm[t][:, None] + gain + ue_gain_dbi - paths.loss_db[:, None]
    acc = np.zeros((n_towers * n_ues, n_b))
    np.add.at(acc, t * n_ues + paths.ue, 10 ** (rx_db / 10))
    return acc.reshape(n_towers, n_ues, n_b).transpose(0, 2, 1)
