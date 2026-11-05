import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from exploration.esa import FOCUS, load_channel
from preprocess import iter_grid_frames
from write_binary import FRAME_SIZE, HEADER_SIZE, PERIOD_US, Header, write_binary


VALIDATION_START_US = 1_199_145_600_000_000
TEST_START_US = 1_293_840_000_000_000


def load_aligned_channels(root: Path):
    timestamps_ns = None
    values = None

    for column, name in enumerate(FOCUS):
        print(f"Loading {name}...", flush=True)
        series = load_channel(root, name)

        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError(f"{name} does not have a DatetimeIndex")

        index = series.index

        if index.tz is not None:
            index = index.tz_convert("UTC").tz_localize(None)

        current_ns = index.asi8

        if len(current_ns) == 0:
            raise ValueError(f"{name} is empty")

        if np.any(current_ns % 1000 != 0):
            raise ValueError(f"{name} has sub-microsecond timestamps")

        if timestamps_ns is None:
            if np.any(np.diff(current_ns) <= 0):
                raise ValueError("Reference timestamps are not increasing")

            timestamps_ns = current_ns.copy()
            values = np.empty(
                (len(timestamps_ns), len(FOCUS)),
                dtype=np.float32,
            )
        elif not np.array_equal(current_ns, timestamps_ns):
            raise ValueError(f"Timestamp alignment failure in {name}")

        samples = series.to_numpy()

        if not np.all(np.isfinite(samples)):
            raise ValueError(f"{name} contains nonfinite measurements")

        converted = np.asarray(samples, dtype=np.float32)

        if not np.all(np.isfinite(converted)):
            raise ValueError(f"{name} contains values outside float32 range")

        values[:, column] = converted

    return timestamps_ns // 1000, values


def grid_statistics(timestamps_us: np.ndarray):
    cells = timestamps_us // PERIOD_US
    first_cell = int(cells[0])
    last_cell = int(cells[-1])

    boundaries = np.flatnonzero(np.diff(cells) != 0) + 1
    group_sizes = np.diff(
        np.concatenate(([0], boundaries, [len(cells)]))
    )

    occupied = len(group_sizes)
    frame_count = last_cell - first_cell + 1

    return {
        "raw_samples": len(timestamps_us),
        "frame_count": frame_count,
        "occupied": occupied,
        "empty": frame_count - occupied,
        "collisions": int(np.count_nonzero(group_sizes > 1)),
        "start_us": first_cell * PERIOD_US,
    }


def convert(root: Path, output: Path):
    timestamps_us, values = load_aligned_channels(root)
    stats = grid_statistics(timestamps_us)

    header = Header(
        start_us=stats["start_us"],
        frame_count=stats["frame_count"],
        validation_start_us=VALIDATION_START_US,
        test_start_us=TEST_START_US,
    )

    print()
    print("Conversion summary")
    print("------------------")

    for key, value in stats.items():
        print(f"{key}: {value}")

    expected_size = HEADER_SIZE + stats["frame_count"] * FRAME_SIZE
    print(f"Expected binary size: {expected_size:,} bytes")

    output.parent.mkdir(parents=True, exist_ok=True)

    write_binary(
        output,
        header,
        iter_grid_frames(timestamps_us, values),
    )

    actual_size = output.stat().st_size

    if actual_size != expected_size:
        raise RuntimeError("Written file size does not match expectation")

    print(f"Created: {output}")
    print(f"Verified size: {actual_size:,} bytes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/telemetry.bin"),
    )

    args = parser.parse_args()
    convert(args.root, args.output)


if __name__ == "__main__":
    main()
