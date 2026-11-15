"""Verified dataset -> C++ statistical scores -> validation-selected event metrics.

Test metrics require --test. See docs/statistical-baseline.md for frozen policies.
"""

import argparse
import json
from pathlib import Path
import subprocess

import numpy as np

from dataset import atomic_text, cell_interval, sha256, verify_dataset
from write_binary import PERIOD_US


def label_masks(events, header):
    """Channel flags preserve attribution; categories remain independent of availability."""
    masks = {
        category: np.zeros(header.frame_count, dtype=np.uint8)
        for category in ["Anomaly", "Rare Event", "Communication Gap"]
    }
    for event in events:
        first, stop = cell_interval(event, header)
        masks[event["category"]][first:stop] |= 1 << (event["channel"] - 41)
    return masks


def alarm_intervals(scores, eligible, threshold):
    active = eligible & np.isfinite(scores) & (scores >= threshold)
    edges = np.diff(np.r_[False, active, False].astype(np.int8))
    return list(
        zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist())
    )


def recall_interval(hits, count):
    if count == 0:
        return None
    z = 1.959963984540054
    p = hits / count
    center = (p + z * z / (2 * count)) / (1 + z * z / count)
    half = (
        z
        * np.sqrt(p * (1 - p) / count + z * z / (4 * count * count))
        / (1 + z * z / count)
    )
    return [float(center - half), float(center + half)]


def event_metrics(
    scores,
    eligible,
    events,
    header,
    threshold,
    anomaly_mask,
    tolerance_cells=0,
    *,
    episodes=None,
):
    # Optional episode policy changes alarm grouping, never scored-cell eligibility.
    alarms = (
        alarm_intervals(scores, eligible, threshold) if episodes is None else episodes
    )
    groups = {}
    for event in events:
        if event["category"] != "Anomaly":
            continue
        first, stop = cell_interval(event, header)
        first, stop = max(0, first - tolerance_cells), min(
            len(scores), stop + tolerance_cells
        )
        indices = (
            np.flatnonzero(eligible[first:stop] & np.isfinite(scores[first:stop]))
            + first
        )
        if event["event_id"] not in groups:
            groups[event["event_id"]] = dict(
                indices=[], start=event["start_us"], end=event["end_us"]
            )
        group = groups[event["event_id"]]
        group["indices"].extend(indices.tolist())
        group["start"] = min(group["start"], event["start_us"])
        group["end"] = max(group["end"], event["end_us"])
    groups = {
        key: dict(value, indices=np.unique(value["indices"]))
        for key, value in groups.items()
    }
    detectable = {key: group for key, group in groups.items() if len(group["indices"])}
    matched, delays = set(), []
    # Chronological alarm episodes; earliest-ending unmatched intersecting event wins.
    for first, stop in alarms:
        candidates = []
        for key, group in detectable.items():
            if key in matched:
                continue
            indices = group["indices"]
            pos = np.searchsorted(indices, first)
            if pos < len(indices) and indices[pos] < stop:
                candidates.append((group["end"], key, int(indices[pos])))
        if candidates:
            _, key, cell = min(candidates)
            matched.add(key)
            delays.append(
                max(
                    0,
                    (
                        header.start_us
                        + (cell + 1) * PERIOD_US
                        - detectable[key]["start"]
                    )
                    / 1e6,
                )
            )
    hits, total = len(matched), len(detectable)
    false_alarms = len(alarms) - hits
    precision = hits / len(alarms) if alarms else 0.0
    recall = hits / total if total else 0.0
    normal_cells = np.count_nonzero(
        eligible & np.isfinite(scores) & (anomaly_mask == 0)
    )
    days = normal_cells / 2880
    return dict(
        event_precision=precision,
        event_recall=recall,
        event_f1=(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ),
        detected_events=hits,
        eligible_events=total,
        unscorable_events=len(groups) - total,
        alarm_episodes=len(alarms),
        alarm_cells=sum(stop - first for first, stop in alarms),
        longest_alarm_seconds=max((stop - first for first, stop in alarms), default=0)
        * 30,
        total_alarm_seconds=sum(stop - first for first, stop in alarms) * 30,
        false_alarms=false_alarms,
        false_alarms_per_eligible_day=false_alarms / days if days else None,
        eligible_normal_days=days,
        recall_wilson_95=recall_interval(hits, total),
        detection_delay_seconds=(
            {str(q): float(np.percentile(delays, q)) for q in [50, 95, 99]}
            if delays
            else {}
        ),
        matched_event_ids=sorted(matched),
    )


def average_precision(scores, truth):
    """Exact cell-wise AP, grouping tied scores; distinct from event recall."""
    if not len(scores) or not np.any(truth):
        return None
    order = np.argsort(-scores, kind="stable")
    sorted_scores, truth = scores[order], truth[order].astype(np.int64)
    ends = np.r_[np.flatnonzero(np.diff(sorted_scores) != 0), len(scores) - 1]
    tp = np.cumsum(truth)[ends]
    precision = tp / (ends + 1)
    return float(np.sum(np.diff(np.r_[0, tp]) * precision) / np.sum(truth))


def partition_events(events, header, first, stop):
    # Events crossing a split are clipped for matching, preserving event identity.
    start_us, end_us = (
        header.start_us + first * PERIOD_US,
        header.start_us + stop * PERIOD_US,
    )
    result = []
    for event in events:
        if event["start_us"] == event["end_us"]:
            if start_us <= event["start_us"] < end_us:
                result.append(event)
        elif event["start_us"] < end_us and event["end_us"] > start_us:
            result.append(
                dict(
                    event,
                    start_us=max(start_us, event["start_us"]),
                    end_us=min(end_us, event["end_us"]),
                )
            )
    return result


def report_partition(scores, masks, events, header, first, stop, thresholds):
    interval = np.zeros(header.frame_count, dtype=bool)
    interval[first:stop] = True
    excluded = (masks["Rare Event"] | masks["Communication Gap"]) != 0
    report = dict(
        cells=stop - first,
        excluded_label_cells=int(np.count_nonzero(excluded[first:stop])),
        detectors={},
    )
    partition = partition_events(events, header, first, stop)
    for column, name in enumerate(["zscore", "ewma"]):
        eligible = interval & ~excluded & np.isfinite(scores[:, column])
        metrics = event_metrics(
            scores[:, column],
            eligible,
            partition,
            header,
            thresholds[name],
            masks["Anomaly"],
        )
        metrics.update(
            threshold=thresholds[name],
            scored_cells=int(np.count_nonzero(eligible)),
            excluded_or_warmup_fraction=1 - np.count_nonzero(eligible) / (stop - first),
            cell_average_precision=average_precision(
                scores[eligible, column], masks["Anomaly"][eligible] != 0
            ),
            tolerance_sensitivity={
                str(t * 30): event_metrics(
                    scores[:, column],
                    eligible,
                    partition,
                    header,
                    thresholds[name],
                    masks["Anomaly"],
                    t,
                )
                for t in [1, 2]
            },
        )
        report["detectors"][name] = metrics
    return report


def prepare_training_mask(masks, header, validation_start, path):
    """Only unlabelled training cells may contribute to normalization."""
    train = np.zeros(header.frame_count, dtype=np.uint8)
    labelled = masks["Anomaly"] | masks["Rare Event"] | masks["Communication Gap"]
    train[:validation_start] = labelled[:validation_start] == 0
    train.tofile(path)


def generate_scores(executable, dataset, output, header, window, alpha):
    """The C++ command validates frames on both fitting and scoring passes."""
    subprocess.run(
        [
            str(executable.resolve()),
            "score",
            str(dataset / "telemetry.bin"),
            str(output / "train_mask.bin"),
            str(output / "scores.bin"),
            str(output / "runtime.json"),
            str(window),
            str(alpha),
        ],
        check=True,
    )
    if (output / "scores.bin").stat().st_size != header.frame_count * 16:
        raise ValueError("Score file size mismatch")
    return np.memmap(
        output / "scores.bin", mode="r", dtype="<f8", shape=(header.frame_count, 2)
    )


def select_thresholds(scores, masks, events, header, validation_start, test_start):
    """Choose thresholds using validation alone; tie-break toward fewer alarms."""
    thresholds, trials = {}, {}
    excluded = (masks["Rare Event"] | masks["Communication Gap"]) != 0
    interval = np.zeros(header.frame_count, dtype=bool)
    interval[validation_start:test_start] = True
    partition = partition_events(events, header, validation_start, test_start)

    for column, name in enumerate(["zscore", "ewma"]):
        eligible = interval & ~excluded & np.isfinite(scores[:, column])
        normal_scores = scores[eligible & (masks["Anomaly"] == 0), column]
        if not len(normal_scores):
            raise ValueError("No eligible validation normal cells")
        quantiles = np.quantile(
            normal_scores, [0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999, 1]
        )
        no_alarm_threshold = np.nextafter(
            float(np.max(scores[eligible, column])), np.inf
        )
        candidates = np.unique(np.r_[quantiles, no_alarm_threshold])
        trials[name] = []
        for threshold in candidates:
            metrics = event_metrics(
                scores[:, column],
                eligible,
                partition,
                header,
                float(threshold),
                masks["Anomaly"],
            )
            trials[name].append(dict(threshold=float(threshold), **metrics))
        best = max(
            trials[name],
            key=lambda metrics: (
                metrics["event_f1"],
                -metrics["false_alarms"],
                metrics["threshold"],
            ),
        )
        thresholds[name] = best["threshold"]
    return thresholds, trials


def record_run(output, report):
    """Preserve an audit trail so repeated held-out evaluations remain visible."""
    from datetime import datetime, timezone

    filename = (
        "test_report.json"
        if report["partition"] == "test"
        else "validation_report.json"
    )
    atomic_text(output / filename, json.dumps(report, indent=2, allow_nan=False) + "\n")
    with open(output / "runs.jsonl", "a", encoding="utf-8") as audit:
        audit.write(
            json.dumps(
                dict(
                    time=datetime.now(timezone.utc).isoformat(),
                    partition=report["partition"],
                    provenance=report["provenance"],
                )
            )
            + "\n"
        )


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--tae", type=Path, default=Path("build/release/apps/cli/tae"))
    parser.add_argument("--output", type=Path, default=Path("data/results/statistical"))
    parser.add_argument("--window", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--test",
        action="store_true",
        help="Explicitly evaluate the held-out test partition",
    )
    args = parser.parse_args()
    if not 2 <= args.window <= 1_000_000 or not 0 < args.alpha <= 1:
        parser.error("Require window in [2, 1000000] and alpha in (0, 1]")
    if args.output.resolve() == args.dataset.resolve():
        parser.error("Results need a separate directory from the dataset")
    return args


def main():
    args = parse_arguments()
    header, events = verify_dataset(args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)
    verification = json.loads(
        subprocess.check_output(
            [str(args.tae.resolve()), "verify", str(args.dataset / "telemetry.bin")],
            text=True,
        )
    )
    masks = label_masks(events, header)
    validation_start = (header.validation_start_us - header.start_us) // PERIOD_US
    test_start = (header.test_start_us - header.start_us) // PERIOD_US
    prepare_training_mask(
        masks, header, validation_start, args.output / "train_mask.bin"
    )
    provenance = dict(
        manifest_sha256=sha256(args.dataset / "manifest.json"),
        engine_sha256=sha256(args.tae),
        evaluation_sha256=sha256(Path(__file__)),
        window=args.window,
        alpha=args.alpha,
        policy="statistical-v1",
        train_mask_sha256=sha256(args.output / "train_mask.bin"),
    )
    selection_path = args.output / "selection.json"
    selection = (
        json.loads(selection_path.read_text()) if selection_path.exists() else None
    )
    if selection and selection["provenance"] != provenance:
        raise ValueError(
            "Frozen selection differs from this run; use a new output directory"
        )
    if args.test and selection is None:
        raise ValueError("Run validation to freeze selection before --test")

    scores = generate_scores(
        args.tae, args.dataset, args.output, header, args.window, args.alpha
    )
    if selection is None:
        thresholds, trials = select_thresholds(
            scores, masks, events, header, validation_start, test_start
        )
        selection = dict(
            provenance=provenance, thresholds=thresholds, validation_trials=trials
        )
        atomic_text(
            selection_path, json.dumps(selection, indent=2, allow_nan=False) + "\n"
        )

    first, stop = (
        (test_start, header.frame_count)
        if args.test
        else (validation_start, test_start)
    )
    report = dict(
        provenance=provenance,
        partition="test" if args.test else "validation",
        verification=verification,
        runtime=json.loads((args.output / "runtime.json").read_text()),
        metrics=report_partition(
            scores, masks, events, header, first, stop, selection["thresholds"]
        ),
    )
    record_run(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
