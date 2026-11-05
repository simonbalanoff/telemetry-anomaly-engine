import argparse
import numpy as np
import pandas as pd
from pathlib import Path

from esa import FOCUS, load_channel, read_labels, read_types


def inspect_interval(s, start, end):
    w = s.loc[start:end]
    expected = pd.date_range(
        start.floor("30s"),
        end.floor("30s"),
        freq="30s"
    )
    occupied = pd.DatetimeIndex(w.index.floor("30s").unique())
    missing = expected.difference(occupied)

    if len(w) == 0:
        return len(expected), 0, len(missing), None, None

    values = w.to_numpy()
    changes = np.diff(values)
    constant_fraction = (
        float(np.mean(changes == 0)) if len(changes) else None
    )

    return (
        len(expected),
        len(w),
        len(missing),
        constant_fraction,
        float(np.max(values) - np.min(values))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()

    labels = read_labels(args.root)
    types = read_types(args.root)
    gaps = types.loc[
        types["Category"] == "Communication Gap", "ID"
    ]

    events = labels[
        labels.ID.isin(gaps) & labels.Channel.isin(FOCUS)
    ]

    for channel in FOCUS:
        s = load_channel(args.root, channel)
        channel_events = events[events.Channel == channel]

        for event in channel_events.itertuples():
            result = inspect_interval(
                s, event.StartTime, event.EndTime
            )

            cells, samples, missing, constant, value_range = result

            print(f"\n{event.ID} | {channel}")
            print(f"Start: {event.StartTime}")
            print(f"End: {event.EndTime}")
            print(f"Expected cells: {cells}")
            print(f"Raw samples in interval: {samples}")
            print(f"Missing grid cells: {missing}")
            print(f"Constant consecutive fraction: {constant}")
            print(f"Value range: {value_range}")


if __name__ == "__main__":
    main()
