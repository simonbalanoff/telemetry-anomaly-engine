"""Mission-neutral, hash-verified input for the six-channel experimental codec.

An adapter must supply synchronized original observations, never a filled grid.
Training and evaluation labels are separate files so capture need not load the latter.
"""

import json
from pathlib import Path

import numpy as np

from dataset import sha256
from retention.native_model import CHUNK

BUNDLE_FILES = (
    "timestamps.npy",
    "values.npy",
    "training_events.json",
    "evaluation_events.json",
)


def read_events(path, start_us, end_us):
    events = json.loads(path.read_text())
    if not isinstance(events, list):
        raise ValueError("Events must be a JSON list")
    for event in events:
        if (
            not isinstance(event.get("event_id"), str)
            or not event["event_id"]
            or event.get("category")
            not in ("Anomaly", "Rare Event", "Communication Gap")
            or type(event.get("channel")) is not int
            or not 41 <= event["channel"] <= 46
            or type(event.get("start_us")) is not int
            or type(event.get("end_us")) is not int
            or not start_us <= event["start_us"] <= event["end_us"] <= end_us
            or event["start_us"] >= end_us
        ):
            raise ValueError("Invalid event or event outside its declared split")
    return events


def open_bundle(root):
    """Validate data and metadata without parsing evaluation annotations."""
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("format") != "TAE-MISSION" or manifest.get("version") != 1:
        raise ValueError("Expected TAE-MISSION version 1")
    if not isinstance(manifest.get("mission"), str) or not manifest["mission"].strip():
        raise ValueError("Specify a mission identity")
    channels = manifest.get("channels")
    if (
        not isinstance(channels, list)
        or len(channels) != 6
        or any(not isinstance(c, str) or not c for c in channels)
        or len(set(channels)) != 6
    ):
        raise ValueError("Declare six distinct ordered channel names")
    if manifest.get("observation_semantics") != "synchronized-native-no-fill":
        raise ValueError("Only synchronized original observations are supported")
    for key in ("training_end_us", "evaluation_start_us", "evaluation_end_us"):
        if type(manifest.get(key)) is not int or not 0 <= manifest[key] < 2**63:
            raise ValueError("Split boundaries must be nonnegative int64 microseconds")
    if (
        not 0
        < manifest["training_end_us"]
        <= manifest["evaluation_start_us"]
        < manifest["evaluation_end_us"]
    ):
        raise ValueError("Training must end before evaluation starts")
    for name in BUNDLE_FILES:
        if sha256(root / name) != manifest["files"].get(name):
            raise ValueError(f"Mission bundle hash mismatch: {name}")
    timestamps = np.load(root / "timestamps.npy", mmap_mode="r", allow_pickle=False)
    values = np.load(root / "values.npy", mmap_mode="r", allow_pickle=False)
    if (
        timestamps.dtype != np.dtype("<i8")
        or timestamps.ndim != 1
        or not len(timestamps)
    ):
        raise ValueError("Expected a nonempty int64 timestamp vector")
    if values.dtype != np.dtype("<f4") or values.shape != (len(timestamps), 6):
        raise ValueError("Expected an N by 6 binary32 measurement array")
    if timestamps[0] < 0 or timestamps[-1] >= 2**63 - 1:
        raise ValueError("Invalid timestamp range")
    for first in range(0, len(timestamps), CHUNK):
        if np.any(np.diff(timestamps[max(0, first - 1) : first + CHUNK]) <= 0):
            raise ValueError("Native timestamps must be strictly increasing")
        if not np.isfinite(values[first : first + CHUNK]).all():
            raise ValueError("Measurements must be finite")
    if np.searchsorted(timestamps, manifest["training_end_us"]) < 2:
        raise ValueError("Insufficient training observations")
    left, right = np.searchsorted(
        timestamps, [manifest["evaluation_start_us"], manifest["evaluation_end_us"]]
    )
    if left == right:
        raise ValueError("No evaluation observations")
    return timestamps, values, manifest


def code_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "run_retention_transfer.py",
        root / "run_retention_ablations.py",
        root / "run_retention_pilot.py",
        root / "run_retention_randomized.py",
        root / "dataset.py",
        *sorted((root / "retention").glob("*.py")),
    ]
    return {str(path.relative_to(root)): sha256(path) for path in paths}
