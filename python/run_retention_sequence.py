"""Assess a distinct temporal receiver on selected completed benchmark streams."""

import argparse
import json
from pathlib import Path

import numpy as np

from dataset import atomic_text, sha256, verify_dataset
from retention.codec import RawRecord
from retention.forecast import fit_forecast, pair_evidence
from retention.native_metrics import build_event_cases
from retention.native_source import open_native_source
from retention.stream import read_packets
from run_retention_randomized import load_frozen_model, validate_reference
from retention.mission import open_bundle, read_events
from retention.partitioned_events import event_reader, build_partition_cases

POLICIES = (
    "uniform",
    "difference-threshold",
    "difference-adaptive",
    "difference-coverage",
    "level-adaptive",
    "pca_3-adaptive",
    "disabled-adaptive",
)


def evaluate(path, times, values, positive, cases, normal):
    retained = np.zeros(len(times), dtype=bool)
    with path.open("rb") as stream:
        for packet in read_packets(stream):
            if any(not isinstance(record, RawRecord) for record in packet.records):
                raise ValueError("Forecast receiver requires raw observations")
            stamps = np.array(
                [r.sample.timestamp_us for r in packet.records], dtype=np.int64
            )
            positions = np.searchsorted(times, stamps)
            if np.any(positions >= len(times)) or not np.array_equal(
                times[positions], stamps
            ):
                raise ValueError("Retained timestamps are not native observations")
            measured = np.asarray(
                [r.sample.values for r in packet.records], dtype="<f4"
            ).reshape(-1, 6)
            if not np.array_equal(
                measured.view("<u4"),
                np.ascontiguousarray(values[positions]).view("<u4"),
            ):
                raise ValueError("Retained measurements changed")
            retained[positions] = True
    evidence = pair_evidence(retained, positive)
    rows = [
        dict(
            event_id=c.event_id,
            source_eligible=bool(len(c.indices)) and not c.censored,
            boundary_censored=bool(c.censored),
            full_archive_evidence=bool(positive[c.indices].any()),
            retained_evidence=bool(evidence[c.indices].any()),
        )
        for c in cases
    ]
    eligible = [r for r in rows if r["source_eligible"]]
    scored_pairs = np.zeros(len(times), dtype=bool)
    scored_pairs[1:] = retained[1:] & retained[:-1] & (np.diff(times) <= 150000000)
    return dict(
        source_eligible_events=len(eligible),
        full_archive_events=sum(r["full_archive_evidence"] for r in eligible),
        retained_events=sum(r["retained_evidence"] for r in eligible),
        positive_normal_observations=int(np.count_nonzero(normal & evidence)),
        scorable_retained_pairs=int(scored_pairs.sum()),
        events=rows,
    )


def run_study(source, dataset, cache, benchmark, baseline, output):
    header, annotations = verify_dataset(dataset)
    times, values, _ = open_native_source(source, dataset, cache, header)
    report = json.loads((benchmark / "report.json").read_text())
    reference = json.loads((baseline / "report.json").read_text())
    validate_reference(reference, baseline, dataset, cache, header)
    if report["provenance"]["reference_sha256"] != sha256(baseline / "report.json"):
        raise ValueError("Sequence evaluation and benchmark references differ")
    if output.resolve() in {
        p.resolve() for p in (source, dataset, cache, benchmark, baseline)
    }:
        raise ValueError("Output must be separate from inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    normalizer = load_frozen_model(reference["model"])
    training_events = [
        event for event in annotations if event["start_us"] < normalizer.training_end_us
    ]
    model = fit_forecast(times, values, training_events, normalizer, output)
    prior = reference["provenance"]
    left, right = np.searchsorted(times, [prior["start_us"], prior["end_us"]])
    times, values = times[left:right], values[left:right]
    scores = model.scores(times, values)
    positive = np.isfinite(scores) & (scores > model.threshold)
    cases, _, normal = build_event_cases(
        times, annotations, prior["start_us"], prior["end_us"], prior["context_us"]
    )
    arms = {}
    for budget in report["provenance"]["budgets"]:
        for policy in POLICIES:
            name = f"{budget}-{policy}"
            original_name = policy.replace("difference-", "")
            path = (
                baseline / f"{budget}-{original_name}.taers"
                if policy in ("uniform", "difference-threshold", "difference-adaptive")
                else benchmark / f"{name}.taers"
            )
            if sha256(path) != report["arms"][name]["packet_stream_sha256"]:
                raise ValueError(f"Benchmark stream changed: {name}")
            arms[name] = evaluate(path, times, values, positive, cases, normal)
            arms[name]["packet_stream_sha256"] = sha256(path)
            print(f"Forecast evaluated: {name}", flush=True)
    result = dict(
        model=model.to_dict(),
        benchmark_sha256=sha256(benchmark / "report.json"),
        scripts={
            p.name: sha256(p)
            for p in (Path(__file__), Path(__file__).parent / "retention/forecast.py")
        },
        arms=arms,
        source_observations=len(times),
        interpretation="AR(1) uses consecutive original observations with gap reset; both endpoints must be retained. This is a distinct linear temporal baseline, not physical diagnosis or a learned future fault model.",
    )
    atomic_text(
        output / "report.json", json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    return result


def run_bundle_study(bundle, benchmark, output):
    times, values, manifest = open_bundle(bundle)
    reference = json.loads((benchmark / "report.json").read_text())
    from run_retention_bundle_benchmark import verify_completed_study

    verify_completed_study(reference, manifest)
    if reference["provenance"]["bundle_manifest_sha256"] != sha256(
        bundle / "manifest.json"
    ):
        raise ValueError("Bundle differs from completed benchmark")
    if output.resolve() in {bundle.resolve(), benchmark.resolve()}:
        raise ValueError("Output must be separate from inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    normalizer = load_frozen_model(reference["receivers"]["original"])
    reader = event_reader(manifest, read_events)
    training = reader(bundle / "training_events.json", 0, manifest["training_end_us"])
    model = fit_forecast(times, values, training, normalizer, output)
    start, end = manifest["evaluation_start_us"], manifest["evaluation_end_us"]
    left, right = np.searchsorted(times, [start, end])
    times, values = times[left:right], values[left:right]
    scores = model.scores(times, values)
    positive = np.isfinite(scores) & (scores > model.threshold)
    events = reader(bundle / "evaluation_events.json", start, end)
    cases, _, normal = build_partition_cases(
        times, events, start, end, reference["provenance"]["settings"]["context_us"]
    )
    arms = {}
    for budget in reference["provenance"]["settings"]["budgets"]:
        for policy in (*POLICIES, "difference-burst", "disabled-burst"):
            name = f"{budget}-{policy}"
            path = benchmark / f"{name}.taers"
            if sha256(path) != reference["arms"][name]["packet_stream_sha256"]:
                raise ValueError(f"Benchmark stream changed: {name}")
            arms[name] = evaluate(path, times, values, positive, cases, normal)
            arms[name]["packet_stream_sha256"] = sha256(path)
    report = dict(
        model=model.to_dict(),
        protocol_commit=reference.get("protocol_commit"),
        protocol_lock_sha256=reference.get("protocol_lock_sha256"),
        benchmark_sha256=sha256(benchmark / "report.json"),
        arms=arms,
        source_observations=len(times),
        interpretation="Training-only AR(1); both original endpoints must survive; all selected policies reported",
    )
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in (
        ("source", "data/ESA-Mission1"),
        ("dataset", "data/processed"),
        ("cache", "data/native"),
        ("benchmark", "data/results/retention-benchmark"),
        ("baseline", "data/results/retention-native"),
        ("output", "data/results/retention-sequence"),
    ):
        parser.add_argument(f"--{name}", type=Path, default=Path(default))
    parser.add_argument(
        "--bundle", type=Path, help="Evaluate a completed independent-mission benchmark"
    )
    args = parser.parse_args()
    if args.bundle is not None:
        run_bundle_study(args.bundle, args.benchmark, args.output)
        return
    run_study(
        args.source,
        args.dataset,
        args.cache,
        args.benchmark,
        args.baseline,
        args.output,
    )


if __name__ == "__main__":
    main()
