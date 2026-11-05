import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from esa import load_channel, read_labels


def compare(s):
    groups = s.groupby(s.index.floor("30s"), sort=True)
    first = groups.first()
    last = groups.last()

    previous = last.shift(1)
    selected = []

    for timestamp, group in groups:
        values = group.to_numpy()
        reference = previous.loc[timestamp]

        if pd.isna(reference):
            selected.append(values[-1])
        else:
            idx = np.argmax(np.abs(values - reference))
            selected.append(values[idx])

    extreme = pd.Series(selected, index=last.index)
    collisions = groups.size() > 1
    difference = (extreme - last).abs()
    changed = collisions & (difference > 0)

    print(f"Total grid cells: {len(last)}")
    print(f"Cells with collisions: {int(collisions.sum())}")
    print(f"Selected values changed: {int(changed.sum())}")

    for name, values in [
        ("first", first),
        ("last", last),
        ("max_deviation", extreme)
    ]:
        print(f"\n{name}")
        print(f"  min: {values.min():.6f}")
        print(f"  max: {values.max():.6f}")
        print(f"  max consecutive change: {values.diff().abs().max():.6f}")

    print("\nLargest difference from keep-last:")
    print(difference.nlargest(10).to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("event_id")
    parser.add_argument("--channel", default="channel_41")
    parser.add_argument("--pad-min", type=float, default=60)
    args = parser.parse_args()

    labels = read_labels(args.root)
    event = labels[
        (labels.ID == args.event_id)
        & (labels.Channel == args.channel)
    ]

    if event.empty:
        raise SystemExit("Event is not labelled on this channel")

    pad = pd.Timedelta(minutes=args.pad_min)
    start = event.StartTime.min() - pad
    end = event.EndTime.max() + pad

    s = load_channel(args.root, args.channel).loc[start:end]

    compare(s)


if __name__ == "__main__":
    main()
