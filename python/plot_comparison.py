"""Plot event detection and alarm burden from a completed comparison report.

Optional dependency: matplotlib, included in python/requirements.txt.
"""

import argparse
import json
from pathlib import Path


def plot_report(report: dict, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [
        "zscore",
        "ewma",
        report["best_pca"],
        "retained_excursion",
        "raw_excursion",
        "within_cell_range",
    ]
    labels = [
        "Rolling z-score",
        "EWMA",
        f"PCA (k={report['best_pca'].split('_')[1]})",
        "Retained-value excursion",
        "Raw-sample excursion",
        "Within-cell range",
    ]
    metrics = [report["detectors"][name] for name in names]
    labels = [
        f"{label} ({item['false_alarms']} FP)" for label, item in zip(labels, metrics)
    ]
    colors = ["#2563eb", "#2563eb", "#0f766e", "#64748b", "#d97706", "#d97706"]
    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none"})
    figure, (detection, burden) = plt.subplots(
        1, 2, figsize=(11, 4.6), sharey=True, gridspec_kw={"width_ratios": [1, 1.1]}
    )
    positions = list(range(len(names)))
    hits = [item["detected_events"] for item in metrics]
    bars = detection.barh(positions, hits, color=colors, height=0.6)
    detection.set_yticks(positions, labels)
    detection.invert_yaxis()
    detection.set_xlim(0, max(item["eligible_events"] for item in metrics) + 2)
    detection.bar_label(
        bars,
        labels=[
            f"{item['detected_events']}/{item['eligible_events']}" for item in metrics
        ],
        padding=5,
    )
    detection.set_xlabel("Detected validation events")
    minutes = [item["total_alarm_seconds"] / 60 for item in metrics]
    bars = burden.barh(positions, minutes, color=colors, height=0.6)
    burden.set_xscale("symlog", linthresh=1)
    burden.bar_label(bars, labels=[f"{value:,.1f}" for value in minutes], padding=5)
    burden.set_xlim(0, max(1, max(minutes)) * 5)
    burden.set_xlabel("Minutes above threshold (symmetric log scale)")
    for axes in (detection, burden):
        axes.spines[["top", "right", "left"]].set_visible(False)
        axes.grid(axis="x", alpha=0.15)
        axes.set_axisbelow(True)
        axes.tick_params(axis="y", length=0)
    budget = report["provenance"]["false_alarms_per_day"]
    figure.suptitle(
        "Detection and alarm burden on shared observed cells", fontweight="bold"
    )
    figure.text(
        0.5,
        0.01,
        f"Validation only · thresholds satisfy ≤ {budget:g} false alarm episodes per eligible day",
        ha="center",
        color="#475569",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.94))
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, metadata={"Date": None})
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plot_report(json.loads(args.report.read_text()), args.output)


if __name__ == "__main__":
    main()
