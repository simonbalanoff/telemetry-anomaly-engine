"""Shared helpers for reading ESA-ADB Mission1 data. Imported by the other scripts."""
import pickle
import warnings
import zipfile
from pathlib import Path

import pandas as pd

# The lightweight channel subset recommended by the ESA-ADB authors (subsystem 5).
FOCUS = [f"channel_{i}" for i in range(41, 47)]


def load_channel(root: Path, name: str) -> pd.Series:
    """Load one channel as a time-sorted float32 Series with a DatetimeIndex.

    NOTE: unpickling executes code from the file. Only use on trusted data
    (here: the official Zenodo download).
    """
    with zipfile.ZipFile(root / "channels" / f"{name}.zip") as z:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            s = pickle.loads(z.read(name))[name]
    return s if s.index.is_monotonic_increasing else s.sort_index()


def _to_naive_utc(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col, utc=True, format="ISO8601").dt.tz_localize(None)


def read_labels(root: Path) -> pd.DataFrame:
    """labels.csv with StartTime/EndTime as timezone-naive UTC timestamps."""
    labels = pd.read_csv(root / "labels.csv")
    labels["StartTime"] = _to_naive_utc(labels.StartTime)
    labels["EndTime"] = _to_naive_utc(labels.EndTime)
    return labels


def read_types(root: Path) -> pd.DataFrame:
    return pd.read_csv(root / "anomaly_types.csv")
