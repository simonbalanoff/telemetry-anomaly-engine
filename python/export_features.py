"""Preserve within-cell extremes without changing the version-1 telemetry format.

The optional feature bundle is bound to a verified telemetry file by SHA-256.
Empty cells contain count zero and NaN extrema, including forward-filled cells:
imputation is never presented as an additional raw observation.
"""

import argparse
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from convert_esa import grid_statistics, load_aligned_channels
from dataset import atomic_text, sha256, verify_dataset
from verify_export import FRAME_DTYPE
from write_binary import PERIOD_US

FEATURE_DTYPE = np.dtype(
    [("sample_count", "<u4"), ("minimum", "<f4", (6,)), ("maximum", "<f4", (6,))]
)
CHUNK_CELLS = 262144


def write_features(path: Path, timestamps, values, header, frames) -> dict:
    """Reduce raw groups independently; verify every retained value against v1."""
    raw_cells = timestamps // PERIOD_US
    grid_start = header.start_us // PERIOD_US
    stats = grid_statistics(timestamps)
    if (
        stats["start_us"] != header.start_us
        or stats["frame_count"] != header.frame_count
    ):
        raise ValueError("Source coverage differs from the verified telemetry")
    features = np.lib.format.open_memmap(
        path, mode="w+", dtype=FEATURE_DTYPE, shape=(header.frame_count,)
    )
    for first in range(0, header.frame_count, CHUNK_CELLS):
        stop = min(first + CHUNK_CELLS, header.frame_count)
        left, right = np.searchsorted(
            raw_cells, [grid_start + first, grid_start + stop]
        )
        block = features[first:stop]
        block["sample_count"] = 0
        block["minimum"] = np.nan
        block["maximum"] = np.nan
        if left < right:
            cells = raw_cells[left:right]
            starts = np.r_[0, np.flatnonzero(np.diff(cells)) + 1]
            ends = np.r_[starts[1:], right - left]
            positions = cells[starts] - grid_start - first
            block["sample_count"][positions] = ends - starts
            block["minimum"][positions] = np.minimum.reduceat(
                values[left:right], starts
            )
            block["maximum"][positions] = np.maximum.reduceat(
                values[left:right], starts
            )
            retained = values[left + ends - 1]
            actual = np.ascontiguousarray(frames["values"][first + positions])
            if not np.array_equal(actual.view("<u4"), retained.view("<u4")):
                raise ValueError("Source keep-last values differ from telemetry")
        if not np.array_equal(
            block["sample_count"] > 0, frames["observed"][first:stop] == 63
        ):
            raise ValueError("Source occupancy differs from telemetry")
    features.flush()
    del features
    return stats


def export_features(source: Path, dataset: Path, output: Path) -> dict:
    header, _ = verify_dataset(dataset)
    output.mkdir(parents=True, exist_ok=True)
    timestamps, values = load_aligned_channels(source)
    frames = np.memmap(
        dataset / "telemetry.bin",
        mode="r",
        dtype=FRAME_DTYPE,
        offset=64,
        shape=(header.frame_count,),
    )
    descriptor, temporary = tempfile.mkstemp(dir=output, suffix=".npy")
    os.close(descriptor)
    try:
        stats = write_features(Path(temporary), timestamps, values, header, frames)
        os.replace(temporary, output / "cell_features.npy")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    manifest = dict(
        format="TAE-CELL-FEATURES",
        version=1,
        channels=list(range(41, 47)),
        telemetry_sha256=sha256(dataset / "telemetry.bin"),
        features_sha256=sha256(output / "cell_features.npy"),
        exporter_sha256=sha256(Path(__file__)),
        frame_count=header.frame_count,
        grid_period_us=PERIOD_US,
        source_statistics=stats,
    )
    atomic_text(output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_features(output: Path, dataset: Path, header):
    """Check binding, file hash, exact NumPy schema, and per-cell invariants."""
    manifest = json.loads((output / "manifest.json").read_text())
    expected = dict(
        format="TAE-CELL-FEATURES",
        version=1,
        channels=list(range(41, 47)),
        frame_count=header.frame_count,
        grid_period_us=PERIOD_US,
    )
    for key, value in expected.items():
        if type(manifest.get(key)) is not type(value) or manifest[key] != value:
            raise ValueError(f"Feature manifest mismatch: {key}")
    if manifest["telemetry_sha256"] != sha256(dataset / "telemetry.bin"):
        raise ValueError("Feature bundle belongs to different telemetry")
    if manifest["features_sha256"] != sha256(output / "cell_features.npy"):
        raise ValueError("Feature hash mismatch")
    features = np.load(output / "cell_features.npy", mmap_mode="r", allow_pickle=False)
    if features.dtype != FEATURE_DTYPE or features.shape != (header.frame_count,):
        raise ValueError("Incorrect feature array schema")
    frames = np.memmap(
        dataset / "telemetry.bin",
        mode="r",
        dtype=FRAME_DTYPE,
        offset=64,
        shape=(header.frame_count,),
    )
    for first in range(0, header.frame_count, CHUNK_CELLS):
        block = features[first : first + CHUNK_CELLS]
        frame_block = frames[first : first + CHUNK_CELLS]
        observed = block["sample_count"] > 0
        minimum, maximum = block["minimum"], block["maximum"]
        if not np.array_equal(observed, frame_block["observed"] == 63):
            raise ValueError("Feature occupancy mismatch")
        if not (
            np.all(np.isfinite(minimum[observed]))
            and np.all(np.isfinite(maximum[observed]))
            and np.all(minimum[observed] <= frame_block["values"][observed])
            and np.all(frame_block["values"][observed] <= maximum[observed])
            and np.all(np.isnan(minimum[~observed]))
            and np.all(np.isnan(maximum[~observed]))
        ):
            raise ValueError("Invalid feature extrema")
    return features, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/features"))
    args = parser.parse_args()
    if args.output.resolve() == args.dataset.resolve():
        parser.error("Feature bundle needs a separate directory")
    manifest = export_features(args.source, args.dataset, args.output)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
