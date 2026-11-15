"""Verified, memory-mapped native Mission1 observations, before any grid/fill."""

import json
import os
from pathlib import Path
import tempfile

import numpy as np

from convert_esa import load_aligned_channels
from dataset import atomic_text, sha256
from verify_export import FRAME_DTYPE
from write_binary import PERIOD_US


def verify_native_against_grid(timestamps, values, header, telemetry):
    """Check all occupied-cell keep-last bits and occupancy against verified v1."""
    cells = timestamps // PERIOD_US
    first_cell = header.start_us // PERIOD_US
    if (
        int(cells[0]) != first_cell
        or int(cells[-1]) != first_cell + header.frame_count - 1
    ):
        raise ValueError("Native source coverage differs from telemetry")
    frames = np.memmap(
        telemetry, mode="r", dtype=FRAME_DTYPE, offset=64, shape=(header.frame_count,)
    )
    for first in range(0, header.frame_count, 262144):
        stop = min(first + 262144, header.frame_count)
        left, right = np.searchsorted(cells, [first_cell + first, first_cell + stop])
        occupied = np.zeros(stop - first, dtype=bool)
        if left < right:
            local = cells[left:right]
            ends = np.r_[np.flatnonzero(np.diff(local)) + 1, right - left]
            positions = local[ends - 1] - first_cell
            occupied[positions - first] = True
            actual = np.ascontiguousarray(frames["values"][positions])
            expected = np.ascontiguousarray(values[left + ends - 1])
            if not np.array_equal(actual.view("<u4"), expected.view("<u4")):
                raise ValueError("Native source keep-last values differ from telemetry")
        if not np.array_equal(occupied, frames["observed"][first:stop] == 63):
            raise ValueError("Native source occupancy differs from telemetry")


def open_native_source(root: Path, dataset: Path, cache: Path, header):
    """Source hashes bind the cache to the actual archives, not just filenames."""
    archives = {
        f"channel_{channel}.zip": sha256(root / "channels" / f"channel_{channel}.zip")
        for channel in range(41, 47)
    }
    identity = dict(
        format="TAE-NATIVE",
        version=1,
        channels=list(range(41, 47)),
        archives=archives,
        dataset_manifest_sha256=sha256(dataset / "manifest.json"),
        adapter_sha256=sha256(Path(__file__)),
    )
    manifest_path = cache / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["identity"] != identity:
            raise ValueError(
                "Native cache provenance changed; choose a new --cache directory"
            )
        for name in ["timestamps.npy", "values.npy"]:
            if sha256(cache / name) != manifest["files"][name]:
                raise ValueError(f"Native cache hash mismatch: {name}")
    else:
        cache.mkdir(parents=True, exist_ok=True)
        timestamps, values = load_aligned_channels(root)
        verify_native_against_grid(
            timestamps, values, header, dataset / "telemetry.bin"
        )
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            temporary = Path(directory)
            np.save(temporary / "timestamps.npy", timestamps.astype("<i8", copy=False))
            np.save(temporary / "values.npy", values.astype("<f4", copy=False))
            for name in ["timestamps.npy", "values.npy"]:
                os.replace(temporary / name, cache / name)
        manifest = dict(
            identity=identity,
            count=len(timestamps),
            files={
                name: sha256(cache / name) for name in ["timestamps.npy", "values.npy"]
            },
        )
        atomic_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    timestamps = np.load(cache / "timestamps.npy", mmap_mode="r", allow_pickle=False)
    values = np.load(cache / "values.npy", mmap_mode="r", allow_pickle=False)
    if timestamps.dtype != np.dtype("<i8") or values.dtype != np.dtype("<f4"):
        raise ValueError("Native cache dtype mismatch")
    if timestamps.shape != (manifest["count"],) or values.shape != (
        manifest["count"],
        6,
    ):
        raise ValueError("Native cache shape mismatch")
    return timestamps, values, manifest
