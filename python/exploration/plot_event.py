"""Plot a window around one labelled event across channels 41-46.

Usage:  python python/plot_event.py data/ESA-Mission1 id_187 [--pad-min 60]
Writes data/plots/<event_id>.png. Loads six large pickles each run (slow).
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write to a file; no window needed
import matplotlib.pyplot as plt
import pandas as pd

from python.exploration.esa import FOCUS, load_channel, read_labels, read_types


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("event_id")
    ap.add_argument("--pad-min", type=float, default=60.0, help="minutes of context each side")
    args = ap.parse_args()
    root = args.root

    labels = read_labels(root)
    types = read_types(root)

    ev = labels[(labels.ID == args.event_id) & labels.Channel.isin(FOCUS)]
    if ev.empty:
        raise SystemExit(f"{args.event_id} not found, or it does not touch channels 41-46")
    category = types.loc[types.ID == args.event_id, "Category"].iloc[0]

    pad = pd.Timedelta(minutes=args.pad_min)
    lo, hi = ev.StartTime.min() - pad, ev.EndTime.max() + pad
    if hi - lo > pd.Timedelta(days=3):
        print(f"Warning: window is {(hi - lo).days} days long; the plot will be dense.")

    fig, axes = plt.subplots(len(FOCUS), 1, sharex=True, figsize=(12, 10))
    for ax, ch in zip(axes, FOCUS):
        w = load_channel(root, ch).loc[lo:hi]
        ax.plot(w.index, w.values, lw=0.8, marker=".", ms=2)
        for _, r in ev[ev.Channel == ch].iterrows():
            if r.StartTime == r.EndTime:
                ax.axvline(r.StartTime, color="red", alpha=0.6)
            else:
                ax.axvspan(r.StartTime, r.EndTime, color="red", alpha=0.25)
        ax.set_ylabel(ch.replace("channel_", "ch "))
    axes[0].set_title(f"{args.event_id} ({category}), {ev.Channel.nunique()} focus channels labelled")
    fig.autofmt_xdate()

    out = root.parent / "plots" / f"{args.event_id}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
