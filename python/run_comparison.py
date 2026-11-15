"""Compare PCA and preserved raw extrema under a validation false-alarm budget.

Default: validation only. Test reporting requires an existing frozen selection
and --exploratory-test because this project's historical test split was examined.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import numpy as np

from comparison import (
    alarm_catalog,
    channel_evidence,
    summarize_detector,
    validation_selection,
)
from dataset import atomic_text, sha256, verify_dataset
from evaluate import label_masks, partition_events, prepare_training_mask
from export_features import CHUNK_CELLS, verify_features
from verify_export import FRAME_DTYPE
from write_binary import PERIOD_US

EVIDENCE_NAMES = ["retained_excursion", "raw_excursion", "within_cell_range"]


def score_raw_evidence(path, features, frames, runtime):
    """Matched extrema/keep-last controls share the same frozen normalizer."""
    mean = np.array([entry["mean"] for entry in runtime["normalization"]])
    sigma = np.maximum(
        1e-12, np.sqrt([entry["variance"] for entry in runtime["normalization"]])
    )
    output = np.lib.format.open_memmap(
        path, mode="w+", dtype="<f8", shape=(len(frames), 3)
    )
    for first in range(0, len(frames), CHUNK_CELLS):
        stop = min(first + CHUNK_CELLS, len(frames))
        block = features[first:stop]
        observed = block["sample_count"] > 0
        retained = (frames["values"][first:stop].astype(float) - mean) / sigma
        minimum = (block["minimum"].astype(float) - mean) / sigma
        maximum = (block["maximum"].astype(float) - mean) / sigma
        output[first:stop, 0] = np.max(np.abs(retained), axis=1)
        output[first:stop, 1] = np.max(
            np.maximum(np.abs(minimum), np.abs(maximum)), axis=1
        )
        output[first:stop, 2] = np.max(maximum - minimum, axis=1)
        output[first:stop][~observed] = np.nan
    output.flush()
    return output


def provenance(args, feature_manifest):
    scripts = [
        "run_comparison.py",
        "comparison.py",
        "evaluate.py",
        "dataset.py",
        "export_features.py",
        "verify_export.py",
        "write_binary.py",
    ]
    return dict(
        policy="evidence-comparison-v2",
        manifest_sha256=sha256(args.dataset / "manifest.json"),
        feature_manifest_sha256=sha256(args.features / "manifest.json"),
        features_sha256=feature_manifest["features_sha256"],
        engine_sha256=sha256(args.tae),
        scripts={name: sha256(Path(__file__).parent / name) for name in scripts},
        window=args.window,
        alpha=args.alpha,
        false_alarms_per_day=args.false_alarms_per_day,
        bridge_missing_cells=args.bridge_missing_cells,
        python=platform.python_version(),
        numpy=np.__version__,
    )


def generate_scores(args, header, features):
    subprocess.run(
        [
            str(args.tae.resolve()),
            "score-pca",
            str(args.dataset / "telemetry.bin"),
            str(args.output / "train_mask.bin"),
            str(args.output / "engine_scores.bin"),
            str(args.output / "runtime.json"),
            str(args.window),
            str(args.alpha),
        ],
        check=True,
    )
    runtime = json.loads((args.output / "runtime.json").read_text())
    names = runtime["score_names"]
    if names != ["zscore", "ewma"] + [f"pca_{count}" for count in range(1, 6)]:
        raise ValueError("Unexpected C++ score schema")
    if (args.output / "engine_scores.bin").stat().st_size != header.frame_count * len(
        names
    ) * 8:
        raise ValueError("Incomplete C++ scores")
    engine_scores = np.memmap(
        args.output / "engine_scores.bin",
        mode="r",
        dtype="<f8",
        shape=(header.frame_count, len(names)),
    )
    frames = np.memmap(
        args.dataset / "telemetry.bin",
        mode="r",
        dtype=FRAME_DTYPE,
        offset=64,
        shape=(header.frame_count,),
    )
    evidence = score_raw_evidence(
        args.output / "evidence_scores.npy", features, frames, runtime
    )
    columns = {name: engine_scores[:, index] for index, name in enumerate(names)}
    columns.update(
        {name: evidence[:, index] for index, name in enumerate(EVIDENCE_NAMES)}
    )
    return columns, frames, runtime


def write_reports(
    args,
    header,
    features,
    frames,
    columns,
    runtime,
    masks,
    events,
    selection,
    run_provenance,
):
    first = (
        (header.test_start_us - header.start_us) // PERIOD_US
        if args.exploratory_test
        else (header.validation_start_us - header.start_us) // PERIOD_US
    )
    stop = (
        header.frame_count
        if args.exploratory_test
        else (header.test_start_us - header.start_us) // PERIOD_US
    )
    common = np.isfinite(columns["pca_1"]) & (features["sample_count"] > 0)
    excluded = (masks["Rare Event"] | masks["Communication Gap"]) != 0
    bridgeable = (frames["observed"] == 0) & (frames["usable"] == 63) & ~excluded
    eligible = common & ~excluded
    eligible[:first] = False
    eligible[stop:] = False
    partition = partition_events(events, header, first, stop)
    report = dict(
        partition="exploratory_test" if args.exploratory_test else "validation",
        provenance=run_provenance,
        best_pca=selection["best_pca"],
        comparison_cells=int(np.count_nonzero(eligible)),
        partition_cells=stop - first,
        excluded_or_unscorable_fraction=1
        - float(np.count_nonzero(eligible)) / (stop - first),
        detectors={},
    )
    for name, scores in columns.items():
        threshold = selection["detectors"][name]["threshold"]
        metrics = summarize_detector(
            scores,
            eligible,
            partition,
            header,
            masks["Anomaly"],
            threshold,
            bridgeable,
            args.bridge_missing_cells,
        )
        report["detectors"][name] = metrics
        alarms = alarm_catalog(
            scores,
            eligible,
            partition,
            header,
            threshold,
            bridgeable,
            args.bridge_missing_cells,
        )
        for alarm in alarms:
            peak = alarm["peak_cell"]
            alarm["evidence"] = channel_evidence(
                name, frames[peak], features[peak], runtime
            )
        atomic_text(
            args.output / f"{report['partition']}_{name}_alarms.json",
            json.dumps(alarms, indent=2, allow_nan=False) + "\n",
        )
    atomic_text(
        args.output / f"{report['partition']}_report.json",
        json.dumps(report, indent=2, allow_nan=False) + "\n",
    )
    with (args.output / "runs.jsonl").open("a", encoding="utf-8") as audit:
        audit.write(
            json.dumps(
                dict(
                    time=datetime.now(timezone.utc).isoformat(),
                    partition=report["partition"],
                    provenance=run_provenance,
                )
            )
            + "\n"
        )
    return report


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--features", type=Path, default=Path("data/features"))
    parser.add_argument("--tae", type=Path, default=Path("build/release/apps/cli/tae"))
    parser.add_argument("--output", type=Path, default=Path("data/results/comparison"))
    parser.add_argument("--window", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--false-alarms-per-day", type=float, default=0.01)
    parser.add_argument(
        "--bridge-missing-cells",
        type=int,
        choices=range(0, 6),
        default=5,
        help="Hold alarms across up to this many usable unobserved cells",
    )
    parser.add_argument("--exploratory-test", action="store_true")
    args = parser.parse_args()
    if not 2 <= args.window <= 1000000 or not 0 < args.alpha <= 1:
        parser.error("Invalid window or alpha")
    if not np.isfinite(args.false_alarms_per_day) or args.false_alarms_per_day < 0:
        parser.error("False-alarm budget must be finite and nonnegative")
    if args.output.resolve() in [args.dataset.resolve(), args.features.resolve()]:
        parser.error("Results require a separate output directory")
    return args


def main():
    args = parse_arguments()
    header, events = verify_dataset(args.dataset)
    features, manifest = verify_features(args.features, args.dataset, header)
    args.output.mkdir(parents=True, exist_ok=True)
    current_provenance = provenance(args, manifest)
    path = args.output / "selection.json"
    selection = json.loads(path.read_text()) if path.exists() else None
    if selection is not None and selection["provenance"] != current_provenance:
        raise ValueError("Frozen comparison differs; choose a new output directory")
    if args.exploratory_test and selection is None:
        raise ValueError(
            "Freeze a validation selection before exploratory test reporting"
        )
    masks = label_masks(events, header)
    validation_start = (header.validation_start_us - header.start_us) // PERIOD_US
    test_start = (header.test_start_us - header.start_us) // PERIOD_US
    prepare_training_mask(
        masks, header, validation_start, args.output / "train_mask.bin"
    )
    columns, frames, runtime = generate_scores(args, header, features)
    common = np.isfinite(columns["pca_1"]) & (features["sample_count"] > 0)
    for name, scores in columns.items():
        if not np.all(np.isfinite(scores[common])):
            raise ValueError(f"Inconsistent comparison coverage: {name}")
    if selection is None:
        eligible = common & ((masks["Rare Event"] | masks["Communication Gap"]) == 0)
        eligible[:validation_start] = False
        eligible[test_start:] = False
        partition = partition_events(events, header, validation_start, test_start)
        selection = validation_selection(
            columns,
            eligible,
            partition,
            header,
            masks["Anomaly"],
            args.false_alarms_per_day,
            bridgeable=(frames["observed"] == 0)
            & (frames["usable"] == 63)
            & ((masks["Rare Event"] | masks["Communication Gap"]) == 0),
            max_gap=args.bridge_missing_cells,
        )
        selection["provenance"] = current_provenance
        atomic_text(path, json.dumps(selection, indent=2, allow_nan=False) + "\n")
    report = write_reports(
        args,
        header,
        features,
        frames,
        columns,
        runtime,
        masks,
        events,
        selection,
        current_provenance,
    )
    print(
        json.dumps(
            {
                name: {
                    key: metrics[key]
                    for key in [
                        "event_recall",
                        "false_alarms_per_eligible_day",
                        "alarm_fraction",
                    ]
                }
                for name, metrics in report["detectors"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
