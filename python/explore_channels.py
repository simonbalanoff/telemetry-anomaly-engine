import argparse
import pickle
import warnings
import zipfile
from pathlib import Path

import pandas as pd

FOCUS = [f"channel_{i}" for i in range(41, 47)]


def load_channel(root: Path, name: str) -> pd.Series:
    # NOTE: unpickling executes code from the file. Only use on trusted data.
    with zipfile.ZipFile(root / "channels" / f"{name}.zip") as z:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return pickle.loads(z.read(name))[name]


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

    # --- events, one row per event ---
    types = pd.read_csv(root / "anomaly_types.csv")
    labels = pd.read_csv(root / "labels.csv", parse_dates=["StartTime", "EndTime"])
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
    ev.to_csv(root.parent / "focus_events.csv", index=False)

    print(f"Events touching channels 41-46: {len(ev)}")
    print(ev.Category.value_counts().to_string())
    print(f"Point events (zero duration): {int(ev.is_point.sum())}")
    print("Duration (min) by category:")
    print(ev.groupby("Category").duration_min.describe()[["min", "50%", "max"]].round(1).to_string())

    print("\nEvents per year (by start time):")
    print(pd.crosstab(ev.start.dt.year, ev.Category).to_string())

    # --- channel health ---
    print("\nChannel summary:")
    print(pd.DataFrame([summarize_channel(root, c) for c in FOCUS]).to_string(index=False))


if __name__ == "__main__":
    main()
