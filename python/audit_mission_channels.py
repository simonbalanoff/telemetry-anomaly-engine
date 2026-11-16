"""Audit metadata-selected native channels without reading anomaly annotations.

Selection uses channels.csv only. Numeric quality is assessed on training values;
full-range timestamps are compared only for source-format compatibility. Official
archives contain pickle objects: only run this on a trusted, verified source.
"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import zipfile

import numpy as np
import pandas as pd

from dataset import atomic_text, sha256


def select_channels(metadata):
    required = {"Channel", "Group", "Target", "Categorical"}
    if not required <= set(metadata.columns):
        raise ValueError("Channel metadata is missing required columns")
    if metadata["Channel"].duplicated().any():
        raise ValueError("Channel metadata contains duplicate names")
    ordered = metadata.copy()
    ordered["Group"] = pd.to_numeric(ordered["Group"], errors="raise")
    for group, rows in ordered.groupby("Group", sort=True):
        if (
            len(rows) == 6
            and rows["Target"].eq("YES").all()
            and rows["Categorical"].eq("NO").all()
        ):
            names = sorted(
                rows["Channel"], key=lambda value: int(value.rsplit("_", 1)[1])
            )
            return int(group), names
    raise ValueError("No metadata group contains exactly six numeric target channels")


def load_trusted_channel(path, name):
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != [name]:
            raise ValueError(f"Unexpected archive members for {name}")
        try:
            data = archive.read(name)
        except NotImplementedError:
            # The official Mission2 archives may use Deflate64, unsupported by
            # Python's standard zipfile reader. System unzip verifies its CRC.
            data = subprocess.check_output(["unzip", "-p", str(path), name])
    frame = pickle.loads(data)
    if not isinstance(frame, pd.DataFrame) or list(frame.columns) != [name]:
        raise ValueError(f"Unexpected source object for {name}")
    return frame[name]


def audit(root, training_end_us):
    if type(training_end_us) is not int or training_end_us <= 0:
        raise ValueError("Training cutoff must be positive UTC microseconds")
    metadata = pd.read_csv(root / "channels.csv")
    group, names = select_channels(metadata)
    reports = {}
    reference_training = reference_all = None
    training_aligned = all_aligned = True
    for name in names:
        path = root / "channels" / f"{name}.zip"
        series = load_trusted_channel(path, name)
        if not isinstance(series.index, pd.DatetimeIndex) or not len(series):
            raise ValueError(f"{name} needs nonempty native datetime timestamps")
        times = series.index.as_unit("ns").asi8
        training_mask = times < training_end_us * 1000
        train_times = times[training_mask]
        training = np.asarray(series.iloc[np.flatnonzero(training_mask)], dtype=float)
        with np.errstate(over="ignore", invalid="ignore"):
            finite32 = bool(np.isfinite(training.astype("<f4")).all())
        increasing = bool(len(train_times) > 1 and np.all(np.diff(train_times) > 0))
        valid_time = bool(
            len(train_times)
            and np.all(train_times >= 0)
            and np.all(train_times % 1000 == 0)
        )
        if reference_training is None:
            reference_training, reference_all = train_times.copy(), times.copy()
        same_training = bool(np.array_equal(train_times, reference_training))
        same_all = bool(np.array_equal(times, reference_all))
        training_aligned &= same_training
        all_aligned &= same_all
        reports[name] = dict(
            source_archive_sha256=sha256(path),
            full_observations=len(times),
            training_observations=len(train_times),
            training_timestamps_sha256=hashlib.sha256(
                train_times.astype("<i8").tobytes()
            ).hexdigest(),
            training_timestamps_strictly_increasing=increasing,
            training_timestamps_nonnegative_microsecond_precision=valid_time,
            training_values_finite_binary32=finite32,
            training_timestamps_equal_first_channel=same_training,
            full_timestamps_equal_first_channel=same_all,
        )
        print(
            f"Audited {name}: {len(train_times):,} training observations; training aligned={same_training}",
            flush=True,
        )
    quality = all(
        r["training_values_finite_binary32"]
        and r["training_timestamps_strictly_increasing"]
        and r["training_timestamps_nonnegative_microsecond_precision"]
        for r in reports.values()
    )
    return dict(
        protocol="metadata-first-native-channel-audit-v1",
        source=root.name,
        adapter_sha256=sha256(Path(__file__)),
        metadata_sha256=sha256(root / "channels.csv"),
        selection_rule="Lowest numbered complete metadata group with exactly six Target=YES, Categorical=NO channels",
        group=group,
        channels=names,
        training_end_us=training_end_us,
        training_native_alignment=bool(training_aligned),
        full_native_alignment=bool(all_aligned),
        training_numeric_and_timestamp_quality=quality,
        ready_for_native_adapter=bool(training_aligned and all_aligned and quality),
        full_numeric_validation_performed=False,
        channel_audit=reports,
        exposure="channels.csv, native timestamp identity across full source, training values only; no labels or evaluation-value statistics inspected",
        interpretation="Compatibility audit only; full numeric validation remains required during bundle conversion. Not a frozen split or evaluation result. Do not fill, interpolate, or intersect away asynchronous observations.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--training-end", default="2001-10-01T00:00:00Z")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("Preserve completed audits; choose a new report path")
    cutoff = int(pd.Timestamp(args.training_end).value // 1000)
    result = audit(args.source, cutoff)
    atomic_text(args.report, json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "channel_audit"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
