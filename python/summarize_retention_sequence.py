"""Generate the temporal receiver comparison, including exploratory pair capture."""

import argparse
import json
from pathlib import Path

from dataset import atomic_text
from run_retention_sequence import POLICIES


def summarize(benchmark, sequence, bursts, markdown, latex, budget=1024):
    selected = []
    for policy in POLICIES:
        name = f"{budget}-{policy}"
        captured, temporal = benchmark["arms"][name], sequence["arms"][name]
        selected.append((policy, captured, temporal))
    for mode in ("difference", "disabled"):
        name = f"{budget}-{mode}-burst"
        captured = bursts["arms"][name]
        selected.append((f"{mode}-burst", captured, captured["forecast"]))
    rows = [
        "# Temporal evidence and adjacent-pair background",
        "",
        "A ridge AR(1) receiver provides a temporal comparison to the pointwise PCA",
        "receivers. It is fit on eligible consecutive training observations only,",
        "using fixed regularization 0.001, a 150-second gap reset, and a training",
        "score quantile of 0.999. Both original endpoints must survive retention.",
        "No forward filling or stitching across missing observations earns credit.",
        "",
        f"## {budget}-byte cap per active hour",
        "",
        "| Capture / recorder | Actual MiB | PCA-3 events | AR(1) events | Scorable retained pairs |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    table = [
        "% Generated temporal receiver and adjacent-pair comparison.",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Capture / policy & MiB & PCA events & AR(1) events & Retained pairs \\",
        r"\midrule",
    ]
    for policy, captured, temporal in selected:
        total = temporal["source_eligible_events"]
        pca = f"{captured['receivers']['pca_3']['retained_events']}/{total}"
        forecast = f"{temporal['retained_events']}/{total}"
        label = (
            policy.replace("difference-", "Diff. / ")
            .replace("disabled-", "Disabled / ")
            .replace("level-", "Level / ")
            .replace("pca_3-", "PCA / ")
            .capitalize()
        )
        rows.append(
            f"| {label} | {captured['serialized_bytes']/2**20:.2f} | {pca} | {forecast} | {temporal['scorable_retained_pairs']} |"
        )
        table.append(
            f"{label} & {captured['serialized_bytes']/2**20:.2f} & {pca} & {forecast} & {temporal['scorable_retained_pairs']} "
            + r"\\"
        )
    atomic_text(latex, "\n".join([*table, r"\bottomrule", r"\end{tabular}"]) + "\n")
    rows.extend(
        [
            "",
            "The full archive contains AR(1) evidence for all 11 source-eligible events.",
            "The native temporal study reports seven prespecified policies at four caps",
            "(28 evaluations), rather than claiming exhaustive coverage of every receiver.",
            "",
            "## What the experiment shows",
            "",
            "- At 1,024 bytes, adaptive context capture preserves 10/11 temporal events versus 2/11 for uniform and 1/11 for threshold-only capture.",
            "- Disabling the trigger leaves singleton adaptive background capture with 4/11 PCA-3 events but **0/11 AR(1) events**. Pointwise evidence is not interchangeable with temporal evidence.",
            "- The adjacent-pair background control preserves **2/11 AR(1) events** under the disabled trigger, while retaining 4/11 PCA-3 events at the same rounded encoded cost. It does not solve the blind-spot problem.",
            "- With first-difference triggers enabled, both ordinary adaptive and paired capture retain 10/11 AR(1) events. A pair control does not automatically improve the primary triggered result.",
            "",
            "The pair control was designed **after observing this validation failure**. Its",
            "eight-arm study is exploratory, not a fresh confirmation. The same hourly cap",
            "does not imply equal exact expenditure; pair grouping may leave odd quota slots",
            "unused. Isolated events, gap resets, background phase, and downstream model choice",
            "still matter. Cross-mission evidence and stronger temporal detectors are pending.",
            "",
            "Full reports: [temporal receiver](temporal-retention.json),",
            "[adjacent-pair control](burst-retention.json), and",
            "[capture/receiver benchmark](receiver-mismatch.json).",
            "",
            "## Reproduce",
            "",
            "```bash",
            "python python/run_retention_sequence.py --output data/results/sequence-reproduction",
            "python python/run_retention_bursts.py \\",
            "  --sequence data/results/sequence-reproduction \\",
            "  --output data/results/burst-reproduction",
            "```",
            "",
            "These commands require a completed native mismatch benchmark. See the",
            "[benchmark guide](../benchmark.md) for full inputs and the independent-mission workflow.",
            "",
        ]
    )
    atomic_text(markdown, "\n".join(rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark", type=Path, default=Path("docs/results/receiver-mismatch.json")
    )
    parser.add_argument(
        "--sequence", type=Path, default=Path("docs/results/temporal-retention.json")
    )
    parser.add_argument(
        "--bursts", type=Path, default=Path("docs/results/burst-retention.json")
    )
    parser.add_argument(
        "--markdown", type=Path, default=Path("docs/results/temporal-retention.md")
    )
    parser.add_argument(
        "--latex", type=Path, default=Path("paper/generated/temporal_results.tex")
    )
    parser.add_argument("--budget", type=int, default=1024)
    args = parser.parse_args()
    summarize(
        json.loads(args.benchmark.read_text()),
        json.loads(args.sequence.read_text()),
        json.loads(args.bursts.read_text()),
        args.markdown,
        args.latex,
        args.budget,
    )


if __name__ == "__main__":
    main()
