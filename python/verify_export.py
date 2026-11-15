"""Independently compare every exported frame with the original six channels.

Uses vectorized indexing rather than the converter's frame iterator, checking
every value bit, quality mask, and staleness field without a compiled runtime.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from convert_esa import grid_statistics, load_aligned_channels
from dataset import atomic_text, sha256, verify_dataset
from write_binary import PERIOD_US

FRAME_DTYPE = np.dtype(
    [
        ("values", "<f4", (6,)),
        ("observed", "u1"),
        ("usable", "u1"),
        ("staleness", "<u2"),
    ]
)
REFERENCE = dict(
    raw_samples=15381169,
    frame_count=14728320,
    occupied=14642408,
    empty=85912,
    collisions=733166,
    start_us=946684800000000,
)


def verify_export(source, dataset):
    header, events = verify_dataset(dataset)
    timestamps, values = load_aligned_channels(source)
    stats = grid_statistics(timestamps)
    if stats != REFERENCE:
        raise ValueError(f"Mission1 reference mismatch: {stats}")
    frames = np.memmap(
        dataset / "telemetry.bin",
        dtype=FRAME_DTYPE,
        offset=64,
        mode="r",
        shape=(header.frame_count,),
    )
    raw_cells = timestamps // PERIOD_US
    start_cell = header.start_us // PERIOD_US
    counts = dict(observed=0, filled=0, unavailable=0)
    for first in range(0, header.frame_count, 262144):
        stop = min(header.frame_count, first + 262144)
        cells = np.arange(first, stop, dtype=np.int64) + start_cell
        source_rows = np.searchsorted(raw_cells, cells, side="right") - 1
        age = cells - raw_cells[source_rows]
        observed, usable = age == 0, age <= 5
        expected = values[source_rows].copy()
        expected[~usable] = 0
        actual = frames[first:stop]
        if not (
            np.array_equal(actual["values"].view("<u4"), expected.view("<u4"))
            and np.array_equal(actual["observed"], observed.astype(np.uint8) * 63)
            and np.array_equal(actual["usable"], usable.astype(np.uint8) * 63)
            and np.array_equal(actual["staleness"], np.minimum(age, 65535))
        ):
            raise ValueError(f"Frame parity failure in [{first}, {stop})")
        counts["observed"] += int(observed.sum())
        counts["filled"] += int((usable & ~observed).sum())
        counts["unavailable"] += int((~usable).sum())
    return dict(
        dataset="ESA-ADB/Mission1",
        channels=list(range(41, 47)),
        reference_statistics=stats,
        binary_bytes=(dataset / "telemetry.bin").stat().st_size,
        frame_states=counts,
        event_channel_intervals=len(events),
        distinct_events=len({e["event_id"] for e in events}),
        telemetry_sha256=sha256(dataset / "telemetry.bin"),
        events_sha256=sha256(dataset / "events.csv"),
        full_source_parity=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify_export(args.source, args.dataset)
    text = json.dumps(result, indent=2) + "\n"
    if args.report:
        atomic_text(args.report, text)
    print(text)


if __name__ == "__main__":
    main()
