
"""Check whether channels 41-46 share identical timestamps.

Usage:  python python/check_timestamps.py data/ESA-Mission1
"""
import argparse
from pathlib import Path

from python.exploration.esa import FOCUS, load_channel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    root = ap.parse_args().root

    indexes = {}
    for ch in FOCUS:
        idx = load_channel(root, ch).index  # keep only the index to save memory
        indexes[ch] = idx
        print(f"{ch}: {len(idx)} rows, monotonic={idx.is_monotonic_increasing}, "
              f"duplicate timestamps={int(idx.duplicated().sum())}")

    first = indexes[FOCUS[0]]
    same = all(first.equals(indexes[c]) for c in FOCUS[1:])
    print(f"\nAll six channels share identical timestamps: {same}")
    if not same:
        for c in FOCUS[1:]:
            if not first.equals(indexes[c]):
                print(f"  {c} differs from {FOCUS[0]} "
                      f"(rows {len(indexes[c])} vs {len(first)})")


if __name__ == "__main__":
    main()
