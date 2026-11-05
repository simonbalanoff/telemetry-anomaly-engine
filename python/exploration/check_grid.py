"""How well does a 30 s grid fit the raw timestamps of one channel?

Reports how many raw samples land in each grid cell, how many cells are empty,
and how far apart the values are when two samples share a cell. This decides
how the preprocessing script should aggregate samples that collide.

Usage:  python python/check_grid.py data/ESA-Mission1 [--channel channel_41] [--grid 30s]
"""
import argparse
from pathlib import Path

import pandas as pd

from esa import load_channel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--channel", default="channel_41")
    ap.add_argument("--grid", default="30s")
    args = ap.parse_args()

    s = load_channel(args.root, args.channel)
    cell = s.index.floor(args.grid)
    g = s.groupby(cell).agg(["count", "min", "max"])
    spread = (g["max"] - g["min"]).astype("float64")

    grid_s = pd.Timedelta(args.grid).total_seconds()
    span_cells = int((cell.max() - cell.min()).total_seconds() // grid_s) + 1
    occupied = len(g)
    print(f"{args.channel}, grid {args.grid}")
    print(f"raw samples: {len(s)}")
    print(f"cells in span: {span_cells}, occupied: {occupied}, empty: {span_cells - occupied} "
          f"({100 * (span_cells - occupied) / span_cells:.2f}%)")
    print("\nsamples per occupied cell:")
    print(g["count"].value_counts().sort_index().to_string())

    multi = spread[g["count"] >= 2]
    single_step = s.diff().abs().dropna()
    print(f"\ncells with 2+ samples: {len(multi)}")
    if len(multi):
        q = [0.5, 0.99, 1.0]
        print("value spread inside those cells (max - min):")
        print(multi.quantile(q).round(4).to_string())
        print("for comparison, |change| between consecutive raw samples:")
        print(single_step.quantile(q).round(4).to_string())


if __name__ == "__main__":
    main()
