"""Plot native pilot cost/evidence tradeoffs without mixing summary surrogates."""

import argparse
import json
from pathlib import Path


def plot_pilot(report, svg, pdf):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none"})
    figure, (evidence, context) = plt.subplots(1, 2, figsize=(10.5, 4.2))
    colors = {"uniform": "#64748b", "threshold": "#d97706", "adaptive": "#0f766e"}
    full_cost = report["full_archive"]["serialized_bytes"]
    total = report["full_archive"]["source_eligible_events"]
    for policy, color in colors.items():
        points = [
            metrics
            for name, metrics in report["arms"].items()
            if name.endswith("-" + policy)
        ]
        x = [100 * metrics["serialized_bytes"] / full_cost for metrics in points]
        y = [metrics["receivers"]["pca"]["detected_events"] for metrics in points]
        coverage = [100 * metrics["macro_pre_context_coverage"] for metrics in points]
        evidence.plot(x, y, "o-", label=policy.capitalize(), color=color)
        context.plot(x, coverage, "o-", label=policy.capitalize(), color=color)
        if policy != "threshold":
            for cost, hits, metrics in zip(x, y, points):
                evidence.annotate(
                    str(metrics["config"]["budget_bytes"]),
                    (cost, hits),
                    xytext=(3, 5),
                    textcoords="offset points",
                    fontsize=8,
                )
    evidence.plot(
        [100],
        [report["full_archive"]["receivers"]["pca"]["detected_events"]],
        "*",
        color="#2563eb",
        markersize=12,
        label="Full archive",
    )
    context.plot([100], [100], "*", color="#2563eb", markersize=12)
    evidence.set_ylabel(f"Events with frozen PCA evidence (of {total})")
    evidence.set_ylim(-0.4, total + 1.7)
    evidence.set_yticks(range(0, total + 1, 2))
    context.set_ylabel("Mean pre-event raw context retained (%)")
    context.set_ylim(-3, 108)
    for axes in (evidence, context):
        axes.set_xscale("log")
        axes.set_xlabel("Encoded bytes / full-archive format cost (%)")
        axes.grid(alpha=0.15)
        axes.spines[["top", "right"]].set_visible(False)
    evidence.legend(loc="lower right", frameon=False, fontsize=9)
    figure.suptitle(
        "Native Mission1 validation pilot: evidence versus actual byte cost",
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        "Development results, 2008–2010 · labels are absent from capture · annotations show per-hour byte caps",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    figure.tight_layout(rect=(0, 0.06, 1, 0.95))
    for path, metadata in [
        (svg, {"Date": None}),
        (pdf, {"CreationDate": None, "ModDate": None}),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, metadata=metadata)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--svg", type=Path, default=Path("docs/results/native-retention.svg")
    )
    parser.add_argument(
        "--pdf", type=Path, default=Path("paper/generated/native_tradeoff.pdf")
    )
    args = parser.parse_args()
    plot_pilot(json.loads(args.report.read_text()), args.svg, args.pdf)


if __name__ == "__main__":
    main()
