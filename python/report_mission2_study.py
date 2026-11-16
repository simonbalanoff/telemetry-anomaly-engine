"""Generate the Mission2 qualification report and cross-phase paper artifacts.

This is post-evaluation descriptive reporting, not a new scoring method or a
replacement for the precommitted primary analysis. Empty denominators are N/A.
"""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dataset import atomic_text, sha256
from retention.mission import open_bundle
from run_retention_bundle_benchmark import verify_completed_study
from summarize_independent_retention import compare


def support_audit(source, bundle, benchmark, temporal):
    times, _, manifest = open_bundle(bundle)
    verify_completed_study(benchmark, manifest)
    for name, digest in manifest["source_annotation_sha256"].items():
        if sha256(source / name) != digest:
            raise ValueError("Source annotations differ from the frozen bundle")
    with (source / "anomaly_types.csv").open(newline="") as stream:
        categories = {row["ID"]: row["Category"] for row in csv.DictReader(stream)}
    start = pd.Timestamp(manifest["evaluation_start_us"], unit="us", tz="UTC")
    end = pd.Timestamp(manifest["evaluation_end_us"], unit="us", tz="UTC")
    all_counts, evaluation_counts = Counter(), Counter()
    with (source / "labels.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row["Channel"] not in manifest["channels"]:
                continue
            category = categories[row["ID"]]
            all_counts[category] += 1
            left, right = pd.Timestamp(row["StartTime"]), pd.Timestamp(row["EndTime"])
            intersects = (
                start <= left < end if left == right else left < end and right > start
            )
            if intersects:
                evaluation_counts[category] += 1
    rows = json.loads((bundle / "evaluation_events.json").read_text())
    if evaluation_counts != Counter(row["category"] for row in rows):
        raise ValueError("Independent raw-CSV check differs from prepared annotations")
    lo, hi = np.searchsorted(
        times, [manifest["evaluation_start_us"], manifest["evaluation_end_us"]]
    )
    full_pairs = int(np.count_nonzero(np.diff(times[lo:hi]) <= 150000000))
    eligible = benchmark["arms"]["1024-disabled-adaptive"]["source_eligible_events"]
    return dict(
        phase="Post-evaluation annotation-support verification; no channel/split changes",
        selected_channels=manifest["channels"],
        all_source_annotation_rows_by_category=dict(all_counts),
        evaluation_annotation_rows_by_category=dict(evaluation_counts),
        evaluation_annotated_event_ids=len({row["event_id"] for row in rows}),
        eligible_anomaly_events=eligible,
        full_archive_scorable_pairs=full_pairs,
        bundle_manifest_sha256=sha256(bundle / "manifest.json"),
        evaluation_annotations_sha256=manifest["files"]["evaluation_events.json"],
        protocol_commit=benchmark["protocol_commit"],
        interpretation="Metadata target flags do not establish anomaly-label support. Rare events remain nominal exclusions. Empty anomaly support permits no fault-retention recall estimate.",
    )


def event_cell(arm, receiver="pca_3"):
    denominator = arm["source_eligible_events"]
    return (
        "N/A"
        if denominator == 0
        else f"{arm['receivers'][receiver]['retained_events']}/{denominator}"
    )


def write_tables(benchmark, temporal, primary, support, output):
    rows = [
        "% Generated from the completed frozen Mission2 reports; N/A is not zero recall.",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Capture / policy & MiB & PCA events & AR(1) events & Scorable pairs \\",
        r"\midrule",
    ]
    chosen = (
        ("uniform", "Uniform"),
        ("difference-adaptive", "Difference / adaptive"),
        ("difference-coverage", "Difference / coverage"),
        ("difference-burst", "Difference / pairs"),
        ("disabled-adaptive", "Disabled / singleton"),
        ("disabled-burst", "Disabled / pairs"),
    )
    for policy, label in chosen:
        name = f"1024-{policy}"
        arm, sequence = benchmark["arms"][name], temporal["arms"][name]
        events = (
            "N/A"
            if sequence["source_eligible_events"] == 0
            else f"{sequence['retained_events']}/{sequence['source_eligible_events']}"
        )
        rows.append(
            f"{label} & {arm['serialized_bytes']/2**20:.2f} & {event_cell(arm)} & {events} & {sequence['scorable_retained_pairs']:,} "
            + r"\\"
        )
    atomic_text(output, "\n".join([*rows, r"\bottomrule", r"\end{tabular}"]) + "\n")


def write_markdown(benchmark, temporal, primary, support, path):
    rows = [
        "# Mission2 frozen follow-up: input availability without anomaly support",
        "",
        "**The predeclared primary contrast is uninformative:** the fixed six-channel",
        "evaluation subset has no eligible anomaly events. N/A is not perfect recall,",
        "zero detection performance, or evidence that the method generalizes.",
        "",
        "## Protocol and execution",
        "",
        "Channels 86–91 were selected using metadata before annotation conversion.",
        "Training ends October 1, 2001; evaluation includes all remaining source through",
        "July 1, 2003, on the anonymized dataset timeline. Retention settings transfer",
        "unchanged from Mission1; receivers calibrate only on eligible Mission2 training",
        "data. The channel/split/implementation commit is `3c1ed90`; the input-lock commit",
        f"is `{benchmark['protocol_commit']}`. All 148 capture arms and 36 selected temporal",
        "evaluations completed. No alternate group was selected after observing the result.",
        "",
        "The [protocol](../../protocols/mission2-study-v1.md) and",
        "[lock](../../protocols/mission2-study-v1.lock.json) bind inputs, code, environment,",
        "and the primary comparison. This is a local Git record, not third-party preregistration.",
        "",
        "## Annotation-support verification",
        "",
        f"The fixed channels have {sum(support['all_source_annotation_rows_by_category'].values())} source annotation rows, all classified as Rare Event.",
        f"The evaluation split has {sum(support['evaluation_annotation_rows_by_category'].values())} Rare Event rows across {support['evaluation_annotated_event_ids']} event IDs.",
        "An independent raw-CSV category/interval check agrees with the prepared bundle.",
        "Rare nominal events remain exclusions under the frozen protocol; they are not",
        "relabeled as faults to create a favorable denominator. Metadata `Target=YES`",
        "did not establish anomaly-only task support under our scoring rules. This is a",
        "limitation of our source qualification, not an annotation error.",
        "",
        "## Predeclared primary contrast",
        "",
        "At the 1,024-byte cap, compare disabled-trigger paired versus singleton background",
        "using AR(1) event evidence. The common eligible and full-archive-recoverable",
        "anomaly counts are both zero. Paired outcome counts are therefore empty; no",
        "effect estimate or significance claim is supported.",
        "",
        "## Secondary input-availability measurement",
        "",
        "| Capture / policy | Encoded MiB | Scorable retained native pairs | Anomaly recall |",
        "| --- | ---: | ---: | --- |",
    ]
    for policy in (
        "uniform",
        "difference-adaptive",
        "difference-coverage",
        "difference-burst",
        "disabled-adaptive",
        "disabled-burst",
    ):
        name = f"1024-{policy}"
        rows.append(
            f"| {policy} | {benchmark['arms'][name]['serialized_bytes']/2**20:.2f} | {temporal['arms'][name]['scorable_retained_pairs']:,} | N/A |"
        )
    singleton = temporal["arms"]["1024-disabled-adaptive"]["scorable_retained_pairs"]
    paired = temporal["arms"]["1024-disabled-burst"]["scorable_retained_pairs"]
    rows.extend(
        [
            "",
            f"The pair policy preserves {paired:,} of {support['full_archive_scorable_pairs']:,} full-source scorable transitions",
            f"({100 * paired / support['full_archive_scorable_pairs']:.2f}%), compared with {singleton:,} for singleton background.",
            "The two primary streams differ by 36 encoded bytes, despite rounding to the same",
            "3.62 MiB. This is a structural input-availability result, not measured fault recovery.",
            "",
            "The paper keeps Mission1 development findings separate from this frozen follow-up.",
            "A subsequent study needs an annotation-only coverage qualification rule declared",
            "before selection, or a representation covering the complete intended target set.",
            "This completed attempt remains in the record; it is not replaced by another group.",
            "",
            "Full artifacts: [capture benchmark](mission2-benchmark.json),",
            "[temporal evaluations](mission2-temporal.json), [primary analysis](mission2-primary.json),",
            "and [annotation-support check](../datasets/mission2-annotation-support.json).",
            "",
        ]
    )
    atomic_text(path, "\n".join(rows))


def plot(mission1, sequence1, bursts1, mission2, sequence2, svg, pdf):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter

    choices = ("uniform", "difference-adaptive", "disabled-adaptive", "disabled-burst")
    pointwise, temporal = [], []
    for policy in choices:
        name = f"1024-{policy}"
        if policy == "disabled-burst":
            arm = bursts1["arms"][name]
            pointwise.append(arm["receivers"]["pca_3"]["retained_events"])
            temporal.append(arm["forecast"]["retained_events"])
        else:
            pointwise.append(
                mission1["arms"][name]["receivers"]["pca_3"]["retained_events"]
            )
            temporal.append(sequence1["arms"][name]["retained_events"])
    with plt.rc_context(
        {"font.size": 9, "axes.spines.top": False, "axes.spines.right": False}
    ):
        fig, (left, right) = plt.subplots(
            1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [1.4, 1]}
        )
        x = np.arange(4)
        a = left.bar(
            x - 0.19, pointwise, width=0.36, color="#0f766e", label="Pointwise PCA"
        )
        b = left.bar(
            x + 0.19, temporal, width=0.36, color="#7c3aed", label="Temporal AR(1)"
        )
        left.bar_label(a, padding=3)
        left.bar_label(b, padding=3)
        left.set_xticks(
            x,
            [
                "Uniform",
                "Adaptive\ntriggered",
                "Singleton\ndisabled",
                "Pairs\ndisabled",
            ],
        )
        left.set_ylim(0, 12.7)
        left.set_ylabel("Events with retained evidence (11 eligible)")
        left.set_title("Mission1 development: receiver requirements")
        left.legend(frameon=False, loc="upper left")
        counts = [
            sequence2["arms"][f"1024-disabled-{p}"]["scorable_retained_pairs"]
            for p in ("adaptive", "burst")
        ]
        bars = right.bar([0, 1], counts, color=["#64748b", "#c2410c"], width=0.55)
        right.bar_label(bars, labels=[f"{value:,}" for value in counts], padding=4)
        right.set_xticks([0, 1], ["Singleton\ndisabled", "Pairs\ndisabled"])
        right.set_ylim(0, max(counts) * 1.24)
        right.set_ylabel("Scorable retained consecutive native pairs")
        right.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        right.set_title("Mission2 frozen subset: input availability")
        right.text(
            0.5,
            0.94,
            "0 eligible anomaly events\nFault recall is unavailable",
            transform=right.transAxes,
            ha="center",
            va="top",
            color="#9a3412",
            fontsize=9,
        )
        fig.suptitle(
            "Receiver input requirements under a 1,024-byte hourly cap", fontsize=12
        )
        fig.text(
            0.5,
            0.015,
            "Shared caps do not imply equal expenditure. Mission2 input-pair counts do not establish fault-recovery benefit.",
            ha="center",
            fontsize=8,
        )
        fig.tight_layout(rect=(0, 0.05, 1, 0.94))
        for path in (svg, pdf):
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, bbox_inches="tight")
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("data/mission2-bundle-v1"))
    parser.add_argument("--source", type=Path, default=Path("data/ESA-Mission2"))
    args = parser.parse_args()
    folder = Path("docs/results")
    benchmark_path, temporal_path = (
        folder / "mission2-benchmark.json",
        folder / "mission2-temporal.json",
    )
    benchmark, temporal = json.loads(benchmark_path.read_text()), json.loads(
        temporal_path.read_text()
    )
    primary = json.loads((folder / "mission2-primary.json").read_text())
    if (
        temporal["benchmark_sha256"] != sha256(benchmark_path)
        or primary["benchmark_sha256"] != sha256(benchmark_path)
        or primary["temporal_sha256"] != sha256(temporal_path)
    ):
        raise ValueError("Completed report hashes differ")
    expected = compare(benchmark, temporal)
    if any(primary[key] != value for key, value in expected.items()):
        raise ValueError("Stored primary result differs from the frozen analysis")
    if primary["source_eligible_events"] != 0 or primary["informative"]:
        raise ValueError(
            "This report template describes the recorded uninformative Mission2 v1 study"
        )
    if len(benchmark["arms"]) != 148 or len(temporal["arms"]) != 36:
        raise ValueError("Declared experiment arms are incomplete")
    support = support_audit(args.source, args.bundle, benchmark, temporal)
    support.update(
        benchmark_sha256=sha256(benchmark_path),
        temporal_sha256=sha256(temporal_path),
        reporting_sha256=sha256(Path(__file__)),
    )
    atomic_text(
        Path("docs/datasets/mission2-annotation-support.json"),
        json.dumps(support, indent=2) + "\n",
    )
    write_tables(
        benchmark,
        temporal,
        primary,
        support,
        Path("paper/generated/mission2_results.tex"),
    )
    write_markdown(benchmark, temporal, primary, support, folder / "mission2-study.md")
    plot(
        json.loads((folder / "receiver-mismatch.json").read_text()),
        json.loads((folder / "temporal-retention.json").read_text()),
        json.loads((folder / "burst-retention.json").read_text()),
        benchmark,
        temporal,
        folder / "receiver-requirements.svg",
        Path("paper/generated/receiver_requirements.pdf"),
    )
    print(
        "Generated Mission2 support report, table, and receiver-requirement figure; primary contrast remains uninformative"
    )


if __name__ == "__main__":
    main()
