"""Quick pictures of a World for checking the simulator (top-down map and a 3D view).

The real game UI comes in Step 4; these PNGs are for us while building.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .channel import DIRECT, REFLECT  # noqa: E402
from .world import World  # noqa: E402

QUALITY_COLORS = {"good": "#22925A", "fair": "#D89A12", "poor": "#C7412F"}
MATERIAL_COLORS = {"glass": "#A9D3DA", "concrete": "#C9CDD0", "brick": "#D9B8A6", "metal": "#9AA3AB"}


def quality(sinr_db: float) -> str:
    """Signal clarity bands used across the project: below 0 poor, 0-13 fair, 13+ good."""
    if sinr_db < 0:
        return "poor"
    if sinr_db < 13:
        return "fair"
    return "good"


def plot_map(world: World, path: str, *, title: str | None = None, show_hidden: bool = True,
             highlight_ue: int | None = None, show_links: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(12, 7))
    x0, x1, y0, y1 = world.extent
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_facecolor("#F4F6F7")

    for z in world.zones:
        ax.add_patch(Rectangle((z.xmin, z.ymin), z.xmax - z.xmin, z.ymax - z.ymin, fill=True,
                               facecolor="#C7412F", alpha=0.06, edgecolor="#C7412F", ls="--", lw=1.2))
        ax.text(z.xmax - 2, z.ymax - 4, z.name, ha="right", va="top", fontsize=8, color="#C7412F")

    for b in world.boxes:
        if b.hidden and not show_hidden:
            continue
        w, h = b.xmax - b.xmin, b.ymax - b.ymin
        if b.kind == "building":
            ax.add_patch(Rectangle((b.xmin, b.ymin), w, h, facecolor=MATERIAL_COLORS.get(b.material, "#ccc"),
                                   edgecolor="#4A6470", lw=0.8))
            ax.text(b.xmin + w / 2, b.ymin + h / 2, f"{b.name}\n{b.height:.0f} m", ha="center", va="center",
                    fontsize=7, color="#12303E")
        else:
            ax.add_patch(Rectangle((b.xmin, b.ymin), w, h, facecolor="#4A6470", alpha=0.85,
                                   edgecolor="#C7412F" if b.hidden else "#12303E",
                                   ls="--" if b.hidden else "-", lw=1.2))
            ax.text(b.xmin + w / 2, b.ymax + 1.5, b.kind + (" (hidden)" if b.hidden else ""),
                    ha="center", fontsize=7)

    r = world.last
    sinr = r.sinr_db if r is not None else np.full(len(world.ues), 20.0)
    if show_links and r is not None:
        for i, u in enumerate(world.ues):
            t = world.towers[u.serving]
            ax.plot([t.x, u.x], [t.y, u.y], color="#9AB2BB", lw=0.4, zorder=1)

    if highlight_ue is not None and r is not None:
        idx = world.ue_index()[highlight_ue]
        u = world.ues[idx]
        p = r.paths
        m = (p.ue == idx) & (p.tower == u.serving)
        for k in np.nonzero(m)[0]:
            t = world.towers[p.tower[k]]
            if p.kind[k] == DIRECT:
                ax.plot([t.x, u.x], [t.y, u.y], color="#0F7C86", lw=1.6, zorder=3)
            elif p.kind[k] == REFLECT:
                v = p.via[k]
                ax.plot([t.x, v[0], u.x], [t.y, v[1], u.y], color="#0F7C86", lw=1.0, ls="--", zorder=3)

    for t in world.towers:
        ax.plot(t.x, t.y, marker="^", ms=12, color="#183B4E", zorder=5)
        a = np.radians(t.boresight_deg)
        ax.annotate("", xy=(t.x + 18 * np.cos(a), t.y + 18 * np.sin(a)), xytext=(t.x, t.y),
                    arrowprops=dict(arrowstyle="->", color="#183B4E", lw=1.2), zorder=5)
        ax.text(t.x, t.y - 7, f"{t.name}\n{t.power_dbm:g} dBm, tilt {t.tilt_deg:g}", ha="center", va="top",
                fontsize=7, color="#183B4E")

    for i, u in enumerate(world.ues):
        c = QUALITY_COLORS[quality(sinr[i])]
        ax.plot(u.x, u.y, "o", ms=5 if u.id != highlight_ue else 9, color=c, mec="white", mew=0.6, zorder=6)

    for name, c in QUALITY_COLORS.items():
        ax.plot([], [], "o", color=c, label=f"{name} signal")
    ax.legend(loc="lower right", fontsize=8, frameon=True)
    ax.set_title(title or f"{world.name}, tick {world.tick}")
    ax.set_xlabel("metres east")
    ax.set_ylabel("metres north")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_3d(world: World, path: str, *, show_hidden: bool = True) -> None:
    fig = plt.figure(figsize=(11, 7))
    ax = fig.add_subplot(projection="3d")
    for b in world.boxes:
        if b.hidden and not show_hidden:
            continue
        color = MATERIAL_COLORS.get(b.material, "#ccc") if b.kind == "building" else "#4A6470"
        ax.bar3d(b.xmin, b.ymin, b.zmin, b.xmax - b.xmin, b.ymax - b.ymin, b.zmax - b.zmin,
                 color=color, alpha=0.75 if b.kind == "building" else 0.95, shade=True, edgecolor="#4A6470",
                 linewidth=0.3)
    for t in world.towers:
        ax.plot([t.x, t.x], [t.y, t.y], [0, t.z], color="#183B4E", lw=2)
        ax.scatter([t.x], [t.y], [t.z], marker="^", s=60, color="#183B4E")
    r = world.last
    sinr = r.sinr_db if r is not None else np.full(len(world.ues), 20.0)
    cols = [QUALITY_COLORS[quality(s)] for s in sinr]
    ax.scatter([u.x for u in world.ues], [u.y for u in world.ues], [u.z for u in world.ues], c=cols, s=12,
               depthshade=False)
    x0, x1, y0, y1 = world.extent
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_zlim(0, 60)
    ax.set_box_aspect((x1 - x0, y1 - y0, 60))
    ax.view_init(elev=35, azim=-60)
    ax.set_title(f"{world.name} (3D), tick {world.tick}")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
