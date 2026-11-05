import argparse
from pathlib import Path

import pandas as pd

from python.exploration.esa import FOCUS, load_channel, read_labels, read_types


def summarize_channel(root: Path, name: str) -> dict:
    s = load_channel(root, name)
    gaps = s.index.to_series().diff().dropna().dt.total_seconds()
    return {
        "channel": name,
        "rows": len(s),
        "start": s.index.min().date(),
        "end": s.index.max().date(),
        "nan": int(s.isna().sum()),
        "median_gap_s": gaps.median(),
        "gaps_over_60s": int((gaps > 60).sum()),
        "max_gap_h": round(gaps.max() / 3600, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    root = ap.parse_args().root

    types = read_types(root)
    labels = read_labels(root)
    rows = labels[labels.Channel.isin(FOCUS)]
    ev = (
        rows.groupby("ID")
        .agg(start=("StartTime", "min"), end=("EndTime", "max"), n_channels=("Channel", "nunique"))
        .reset_index()
        .merge(types[["ID", "Category"]], on="ID")
        .sort_values("start")
    )
    ev["duration_min"] = (ev.end - ev.start).dt.total_seconds() / 60
    ev["is_point"] = ev.duration_min == 0
    out = root.parent / "focus_events.csv"
    ev.to_csv(out, index=False)

    print(f"Events touching channels 41-46: {len(ev)}  (full table: {out})")
    print(ev.Category.value_counts().to_string())
    print(f"Point events (zero duration): {int(ev.is_point.sum())}")
    print("Duration (min) by category:")
    print(ev.groupby("Category").duration_min.describe()[["min", "50%", "max"]].round(1).to_string())

    print("\nEvents per year (by start time):")
    print(pd.crosstab(ev.start.dt.year, ev.Category).to_string())

    print("\nChannel summary:")
    print(pd.DataFrame([summarize_channel(root, c) for c in FOCUS]).to_string(index=False))


if __name__ == "__main__":
    main()
