"""How are the raw sampling gaps distributed? (one channel is enough: all share timestamps)

Prints the most common exact gap sizes, and how many 30 s grid cells each long gap
leaves empty. This decides the maximum run length that forward-fill may cover.

Usage:  python python/check_gaps.py data/ESA-Mission1 [--channel channel_41]
"""
import argparse
from pathlib import Path

import pandas as pd

from esa import load_channel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--channel", default="channel_41")
    ap.add_argument("--grid-s", type=float, default=30.0)
    args = ap.parse_args()

    s = load_channel(args.root, args.channel)
    gaps = s.index.to_series().diff().dropna().dt.total_seconds()

    print("most common exact gap sizes (seconds -> count):")
    print(gaps.round(3).value_counts().head(8).to_string())

    # A gap of g seconds spans roughly g/grid - 1 empty cells.
    long_gaps = gaps[gaps > 1.5 * args.grid_s]
    missing_cells = (long_gaps / args.grid_s).round().astype(int) - 1
    print(f"\ngaps longer than 1.5 grid steps: {len(long_gaps)}")
    print("empty cells per such gap (quantiles):")
    print(missing_cells.quantile([0.5, 0.9, 0.99, 1.0]).to_string())
    for k in (1, 2, 5, 10, 60):
        print(f"  gaps leaving more than {k:>2} empty cells: {int((missing_cells > k).sum())}")


if __name__ == "__main__":
    main()
