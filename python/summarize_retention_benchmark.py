"""Generate auditable tables and scientific figures from a completed benchmark."""

import argparse
import json
from pathlib import Path

from dataset import atomic_text
from retention.receiver_bank import CAPTURE_MODELS, NAMES
from run_retention_benchmark import POLICIES

LABELS = {
    "difference": "Difference",
    "level": "Level",
    "pca_3": "PCA",
    "disabled": "Disabled",
}


def summarize(report, markdown, latex, delivery_latex, budget=1024):
    arms = report["arms"]
    rows = [
        "# Capture/receiver mismatch and delivery",
        "",
        "Development results on the same Mission1 validation archive. Receiver normalization",
        "and thresholds use training data only. PCA ranks are correlated sensitivity checks,",
        "not independent faults. No independent-mission result is claimed.",
        "",
        f"## Capture mismatch at {budget} bytes per active hour",
        "",
        "| Capture | Recorder | Actual MiB | PCA-3 events | Trigger-blind PCA-3 retained / recoverable | Pre-context | Post-context |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    table = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Capture & Policy & MiB & PCA events & Blind kept/available & Pre-context (\%) \\",
        r"\midrule",
    ]

    def percent(value):
        return "--" if value is None else f"{100 * value:.1f}"

    for mode in CAPTURE_MODELS:
        for policy in POLICIES:
            arm = arms[f"{budget}-{mode}-{policy}"]
            pca = arm["receivers"]["pca_3"]
            hits = f"{pca['retained_events']}/{arm['source_eligible_events']}"
            blind = f"{pca['trigger_blind_retained_events']}/{pca['trigger_blind_recoverable_events']}"
            rows.append(
                f"| {LABELS[mode]} | {policy} | {arm['serialized_bytes']/2**20:.2f} | {hits} | {blind} | {percent(arm['pre_context_coverage'])}% | {percent(arm['post_context_coverage'])}% |"
            )
            table.append(
                f"{LABELS[mode]} & {policy.capitalize()} & {arm['serialized_bytes']/2**20:.2f} & {hits} & {blind} & {percent(arm['pre_context_coverage'])} "
                + r"\\"
            )
    atomic_text(
        latex,
        "\n".join(
            [
                "% Generated from completed receiver mismatch benchmark.",
                *table,
                r"\bottomrule",
                r"\end{tabular}",
            ]
        )
        + "\n",
    )
    rows.extend(
        [
            "",
            "Trigger-blind means no above-threshold capture score **within the annotated event**.",
            "Context capture may still be triggered outside it. The blind denominator includes",
            "only source-eligible events detectable by that downstream receiver in the full",
            "archive. All source-eligible events remain in the overall denominator. A zero",
            "blind denominator means no such cases, not perfect blind-spot protection.",
            "",
            "Coverage is an experimental control: within each reserved background time stratum,",
            "it replaces candidates to increase distance from previously retained background",
            "observations in training-standardized units. Trigger/context records are protected.",
            "This is not claimed as an original or optimal algorithm. The disabled-trigger arm",
            "is an explicit stress control, not evidence of actual onboard model failure.",
            "",
            "## Delivered evidence",
            "",
            "| Recorder | Scenario | Transmitted wire MiB | Delivered / captured packets | PCA-3 events |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    delivery_table = [
        r"\begin{tabular}{llrrr}",
        r"\toprule",
        r"Policy & Link & Wire MiB & Delivered packets & PCA events \\",
        r"\midrule",
    ]
    for policy in ("uniform", "difference-adaptive", "difference-coverage"):
        arm = arms[f"{budget}-{policy}"]
        for scenario, data in arm["delivery"].items():
            transport, evidence = data["transport"], data["evidence"]
            wire = transport["bytes"]["transmitted_wire_bytes"] / 2**20
            packets = (
                f"{transport['packets']['delivered']}/{transport['packets']['arrived']}"
            )
            hits = f"{evidence['receivers']['pca_3']['retained_events']}/{evidence['source_eligible_events']}"
            label = policy.replace("difference-", "")
            rows.append(f"| {label} | {scenario} | {wire:.2f} | {packets} | {hits} |")
            delivery_table.append(
                f"{label.capitalize()} & {scenario.capitalize()} & {wire:.2f} & {packets} & {hits} "
                + r"\\"
            )
    atomic_text(
        delivery_latex,
        "\n".join(
            [
                "% Generated finite-buffer delivery comparison.",
                *delivery_table,
                r"\bottomrule",
                r"\end{tabular}",
            ]
        )
        + "\n",
    )
    rows.extend(
        [
            "",
            "Contacts are discrete six-hour service opportunities. Arrivals at contact time enter",
            "before service. Ample/lossy cases allow 32,768 wire bytes per contact and a 16,384-byte",
            "payload buffer; congestion allows 2,048 and 4,096 bytes, respectively. Each 128-byte",
            "frame payload charges 16 overhead bytes. Lossy drops completed packets with probability",
            "0.1 (one declared seed). No retransmission is modeled. These illustrative schedules",
            "are not validated mission requirements. Loss variation needs additional seeds before",
            "an uncertainty claim. Pending, evicted, rejected, or lost packets supply no evidence.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "python python/run_retention_benchmark.py --output data/results/benchmark-reproduction",
            "```",
            "",
            "This requires the verified native pilot and seeded-control streams. All caps, arms,",
            "events, receiver recoverability, normal-observation exposure, stream hashes, and",
            "delivery accounting are available in [the JSON report](receiver-mismatch.json).",
            "A frozen independent-mission version is available in `run_retention_bundle_benchmark.py`.",
            "",
        ]
    )
    atomic_text(markdown, "\n".join(rows))


def plot(report, svg, pdf, budget=1024):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    arms = report["arms"]
    keys = [
        f"{budget}-{mode}-{policy}" for mode in CAPTURE_MODELS for policy in POLICIES
    ]
    labels = [
        f"{LABELS[mode]} / {policy}" for mode in CAPTURE_MODELS for policy in POLICIES
    ]
    ratios = np.array(
        [
            [
                (
                    arm["receivers"][name]["retained_events"]
                    / arm["receivers"][name]["full_archive_events"]
                    if arm["receivers"][name]["full_archive_events"]
                    else np.nan
                )
                for name in NAMES
            ]
            for arm in (arms[key] for key in keys)
        ]
    )
    with plt.rc_context(
        {"font.size": 9, "axes.spines.top": False, "axes.spines.right": False}
    ):
        fig, (matrix, delivery) = plt.subplots(
            1, 2, figsize=(12, 5.5), gridspec_kw={"width_ratios": [1.35, 1]}
        )
        matrix.imshow(ratios, cmap="Blues", vmin=0, vmax=1, aspect="auto")
        matrix.set_xticks(
            range(len(NAMES)), [n.replace("_", " ").upper() for n in NAMES]
        )
        matrix.set_yticks(range(len(labels)), labels)
        for row, key in enumerate(keys):
            for col, name in enumerate(NAMES):
                m = arms[key]["receivers"][name]
                matrix.text(
                    col,
                    row,
                    f"{m['retained_events']}/{m['full_archive_events']}",
                    ha="center",
                    va="center",
                    color="white" if ratios[row, col] > 0.6 else "black",
                    fontsize=8,
                )
        matrix.set_title("Retained / full-archive-recoverable events")
        policies = ("uniform", "difference-adaptive", "difference-coverage")
        x = np.arange(3)
        for index, (scenario, color) in enumerate(
            (
                ("captured", "#64748b"),
                ("ample", "#0f766e"),
                ("congested", "#c2410c"),
                ("lossy", "#7c3aed"),
            )
        ):
            hits = [
                (
                    arms[f"{budget}-{policy}"]["receivers"]["pca_3"]["retained_events"]
                    if scenario == "captured"
                    else arms[f"{budget}-{policy}"]["delivery"][scenario]["evidence"][
                        "receivers"
                    ]["pca_3"]["retained_events"]
                )
                for policy in policies
            ]
            delivery.bar(
                x + (index - 1.5) * 0.19,
                hits,
                width=0.18,
                label=scenario.capitalize(),
                color=color,
            )
        delivery.set_xticks(x, ["Uniform", "Adaptive", "Coverage"])
        delivery.set_ylabel("Events with PCA-3 evidence")
        delivery.set_ylim(
            0, max(arm["source_eligible_events"] for arm in arms.values()) + 1
        )
        delivery.set_title("Captured evidence versus delivered evidence")
        delivery.legend(frameon=False)
        fig.suptitle(f"Mission1 development study · {budget}-byte hourly cap")
        fig.text(
            0.5,
            0.02,
            "Correlated receivers; same validation events. Contact/loss scenarios are illustrative, not mission requirements.",
            ha="center",
            fontsize=8,
        )
        fig.tight_layout(rect=(0, 0.05, 1, 0.95))
        for path in (svg, pdf):
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, bbox_inches="tight")
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--budget", type=int, default=1024)
    parser.add_argument(
        "--markdown", type=Path, default=Path("docs/results/receiver-mismatch.md")
    )
    parser.add_argument(
        "--latex", type=Path, default=Path("paper/generated/mismatch_results.tex")
    )
    parser.add_argument(
        "--delivery-latex",
        type=Path,
        default=Path("paper/generated/delivery_results.tex"),
    )
    parser.add_argument(
        "--svg", type=Path, default=Path("docs/results/receiver-mismatch.svg")
    )
    parser.add_argument(
        "--pdf", type=Path, default=Path("paper/generated/receiver_mismatch.pdf")
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    summarize(report, args.markdown, args.latex, args.delivery_latex, args.budget)
    plot(report, args.svg, args.pdf, args.budget)


if __name__ == "__main__":
    main()
