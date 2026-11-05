"""Count events per chronological split and list events that cross a boundary.

Needs data/focus_events.csv, which explore_channels.py writes.

Usage:  python python/check_split.py data/focus_events.csv
        python python/check_split.py data/focus_events.csv --val-start 2008-01-01 --test-start 2011-01-01
"""
import argparse

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--val-start", default="2008-01-01")
    ap.add_argument("--test-start", default="2011-01-01")
    args = ap.parse_args()

    ev = pd.read_csv(args.events)
    for col in ("start", "end"):  # accept tz-aware or naive CSVs; work in naive UTC
        ev[col] = pd.to_datetime(ev[col], utc=True, format="ISO8601").dt.tz_localize(None)
    val_start, test_start = pd.Timestamp(args.val_start), pd.Timestamp(args.test_start)

    def split_of(t: pd.Timestamp) -> str:
        return "train" if t < val_start else "val" if t < test_start else "test"

    ev["split"] = ev.start.map(split_of)
    ev["end_split"] = ev.end.map(split_of)

    table = pd.crosstab(ev.split, ev.Category, margins=True, margins_name="total")
    print(f"boundaries: val starts {val_start.date()}, test starts {test_start.date()}")
    print(table.reindex(["train", "val", "test", "total"]).fillna(0).astype(int).to_string())

    cross = ev[ev.split != ev.end_split]
    print(f"\nevents that start in one split and end in another: {len(cross)}")
    if len(cross):
        cols = ["ID", "Category", "start", "end", "duration_min", "split", "end_split"]
        print(cross[cols].to_string(index=False))


if __name__ == "__main__":
    main()
