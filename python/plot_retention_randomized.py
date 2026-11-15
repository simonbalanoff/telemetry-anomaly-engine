"""Seed-range plots for randomized comparisons; ranges are not confidence intervals."""

import argparse
import json
from pathlib import Path


def plot_study(report, svg, pdf):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none"})
    figure, (evidence, context) = plt.subplots(1, 2, figsize=(10.5, 4.4))
    budgets = report["provenance"]["budgets"]
    colors = {"reservoir": "#2563eb", "randomized_uniform": "#d97706"}
    labels = {
        "reservoir": "Reservoir: seed mean/range",
        "randomized_uniform": "Random phase: seed mean/range",
    }
    for policy, color in colors.items():
        groups = [
            report["summary"]["groups"][f"{budget}-{policy}"] for budget in budgets
        ]
        costs = [group["actual_bytes"]["mean"] / 2**20 for group in groups]
        for axes, key, multiplier in [
            (evidence, "pca_events", 1),
            (context, "context_coverage", 100),
        ]:
            means = [multiplier * group[key]["mean"] for group in groups]
            low = [multiplier * group[key]["minimum"] for group in groups]
            high = [multiplier * group[key]["maximum"] for group in groups]
            axes.plot(costs, means, "o-", color=color, label=labels[policy])
            axes.fill_between(costs, low, high, color=color, alpha=0.13)
    for policy, color, style in [
        ("uniform", "#64748b", "o--"),
        ("adaptive", "#0f766e", "o-"),
    ]:
        controls = [
            report["summary"]["deterministic_controls"][f"{budget}-{policy}"]
            for budget in budgets
        ]
        x = [control["serialized_bytes"] / 2**20 for control in controls]
        evidence.plot(
            x,
            [control["receivers"]["pca"]["detected_events"] for control in controls],
            style,
            color=color,
            label=policy.capitalize(),
        )
        context.plot(
            x,
            [100 * control["macro_pre_context_coverage"] for control in controls],
            style,
            color=color,
        )
    total = report["source_eligible_events"]
    evidence.set_ylabel(f"Events with frozen PCA evidence (of {total})")
    evidence.set_ylim(0, total + 1)
    evidence.set_yticks(range(0, total + 1, 2))
    context.set_ylabel("Mean pre-event raw context retained (%)")
    context.set_ylim(0, 100)
    for axes in (evidence, context):
        axes.set_xscale("log")
        axes.set_xlabel("Actual encoded packet bytes (MiB, log scale)")
        axes.grid(alpha=0.15)
        axes.spines[["top", "right"]].set_visible(False)
    evidence.legend(loc="lower right", frameon=False, fontsize=8)
    figure.suptitle(
        "Randomized sampling controls on the same native validation events",
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.015,
        f"{len(report['provenance']['seeds'])} seeds per policy/cap · shaded ranges show sampling variation, not new-event confidence",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    figure.tight_layout(rect=(0, 0.07, 1, 0.94))
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
        "--svg", type=Path, default=Path("docs/results/randomized-retention.svg")
    )
    parser.add_argument(
        "--pdf", type=Path, default=Path("paper/generated/randomized_tradeoff.pdf")
    )
    args = parser.parse_args()
    plot_study(json.loads(args.report.read_text()), args.svg, args.pdf)


if __name__ == "__main__":
    main()
