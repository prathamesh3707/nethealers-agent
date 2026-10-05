"""Generate the diagnosis dataset.

    uv run python scripts/make_dataset.py                  # full: 6000 city episodes + 600 Station Road
    uv run python scripts/make_dataset.py --episodes 300   # quick check

Writes data/train.parquet (random cities) and data/station_road.parquet
(the demo street, kept out of training so it's a fair test).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nethealers.diagnosis.dataset import generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=6000, help="random-city episodes")
    ap.add_argument("--station-road", type=int, default=600, help="Station Road episodes (test only)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-lwm", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for name, n, layout, start in [("train", args.episodes, "city", 0),
                                   ("station_road", args.station_road, "station_road", 500_000)]:
        if n <= 0:
            continue
        t0 = time.time()
        df = generate(n, start_seed=start, layout=layout, workers=args.workers, with_lwm=not args.no_lwm)
        df.to_parquet(out / f"{name}.parquet", index=False)
        print(f"{name}: {n} episodes, {len(df)} rows in {time.time() - t0:.0f}s -> {out / f'{name}.parquet'}")
        print("  labels:", df.label.value_counts().to_dict())


if __name__ == "__main__":
    main()
