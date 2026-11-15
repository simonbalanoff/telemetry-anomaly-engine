"""Seeded sampling comparisons on the native pilot's frozen receivers and data.

Capture and evaluation are separate process-pool stages. The replay worker never
receives annotations. Seed ranges describe sampling variation on the same events,
not confidence intervals for new spacecraft faults.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import platform
import time

import numpy as np

from dataset import atomic_text, sha256, verify_dataset
from retention.codec import Sample
from retention.native_metrics import build_event_cases, evaluate_stream
from retention.native_model import NativeModel, RECEIVERS
from retention.native_source import open_native_source
from retention.randomized import RANDOMIZED_POLICIES, RandomizedRecorder
from retention.recorder import RecorderConfig


def load_frozen_model(data):
    model = NativeModel(
        np.array(data["mean"]),
        np.array(data["sigma"]),
        np.array(data["basis"]),
        np.array([data["thresholds"][name] for name in RECEIVERS]),
        data["training_count"],
        data["training_end_us"],
        data["quantile"],
    )
    if model.to_dict() != data:
        raise ValueError("Frozen receiver metadata did not round-trip exactly")
    return model


def validate_reference(reference, baseline_dir, dataset, cache, header):
    provenance = reference["provenance"]
    if json.loads((baseline_dir / "model.json").read_text()) != reference["model"]:
        raise ValueError("Frozen model file differs from the reference report")
    if provenance["dataset_manifest_sha256"] != sha256(dataset / "manifest.json"):
        raise ValueError("Reference dataset differs from current verified bundle")
    if provenance["native_manifest_sha256"] != sha256(cache / "manifest.json"):
        raise ValueError("Reference native source cache differs")
    if (
        not header.validation_start_us
        <= provenance["start_us"]
        < provenance["end_us"]
        <= header.test_start_us
    ):
        raise ValueError("Reference interval must be validation only")
    if reference["model"]["training_end_us"] != header.validation_start_us:
        raise ValueError("Frozen model has an unexpected training cutoff")
    for name in [
        "codec.py",
        "recorder.py",
        "native_metrics.py",
        "native_model.py",
        "stream.py",
    ]:
        if provenance["scripts"][name] != sha256(
            Path(__file__).parent / "retention" / name
        ):
            raise ValueError(
                f"Reference semantics changed: {name}; regenerate the pilot"
            )
    for name, metrics in reference["arms"].items():
        if sha256(baseline_dir / f"{name}.taers") != metrics["packet_stream_sha256"]:
            raise ValueError(f"Reference packet hash mismatch: {name}")


def open_validation(cache, start_us, end_us):
    timestamps = np.load(cache / "timestamps.npy", mmap_mode="r", allow_pickle=False)
    values = np.load(cache / "values.npy", mmap_mode="r", allow_pickle=False)
    left, right = np.searchsorted(timestamps, [start_us, end_us])
    return timestamps[left:right], values[left:right]


def capture_budget(task):
    """Only native observations, a byte cap, and random seeds enter this worker."""
    cache, output = Path(task["cache"]), Path(task["output"])
    timestamps, values = open_validation(cache, task["start_us"], task["end_us"])
    config = RecorderConfig(epoch_us=task["epoch_us"], budget_bytes=task["budget"])
    recorders = {
        f"{task['budget']}-{policy}-seed{seed}": RandomizedRecorder(
            policy, config, seed
        )
        for policy in RANDOMIZED_POLICIES
        for seed in task["seeds"]
    }
    streams = {name: (output / f"{name}.taers").open("wb") for name in recorders}
    started = time.perf_counter()
    try:
        for index, (timestamp, row) in enumerate(zip(timestamps, values)):
            sample = Sample(int(timestamp), tuple(row))
            for name, recorder in recorders.items():
                packet = recorder.observe(sample)
                if packet is not None:
                    streams[name].write(packet.encode())
            if index and index % 1000000 == 0:
                print(
                    f"Cap {task['budget']}: replayed {index:,}/{len(timestamps):,}",
                    flush=True,
                )
        for name, recorder in recorders.items():
            packet = recorder.finish()
            if packet is not None:
                streams[name].write(packet.encode())
    finally:
        for stream in streams.values():
            stream.close()
    print(f"Cap {task['budget']}: capture complete", flush=True)
    return dict(budget=task["budget"], seconds=time.perf_counter() - started)


def compact_metrics(metrics):
    return dict(
        serialized_bytes=metrics["serialized_bytes"],
        maximum_packet_bytes=metrics["maximum_packet_bytes"],
        packets=metrics["packets"],
        allocated_bytes=metrics["allocated_bytes"],
        source_eligible_events=metrics["source_eligible_events"],
        events_with_raw_evidence=metrics["events_with_raw_evidence"],
        macro_pre_context_coverage=metrics["macro_pre_context_coverage"],
        macro_event_sample_coverage=metrics["macro_event_sample_coverage"],
        receivers=metrics["receivers"],
        packet_stream_sha256=metrics.get("packet_stream_sha256"),
        events={
            row["event_id"]: dict(
                retained_samples=row["retained_samples"],
                context_coverage=row["context_coverage"],
                receivers=row["receivers"],
            )
            for row in metrics["events"]
            if row["source_eligible"]
        },
    )


def evaluate_budget(payload):
    task, model_data, annotations, expected_packets = payload
    output = Path(task["output"])
    timestamps, values = open_validation(
        Path(task["cache"]), task["start_us"], task["end_us"]
    )
    model = load_frozen_model(model_data)
    cases, _, normal = build_event_cases(
        timestamps, annotations, task["start_us"], task["end_us"], task["context_us"]
    )
    config = RecorderConfig(epoch_us=task["epoch_us"], budget_bytes=task["budget"])
    runs = {}
    for policy in RANDOMIZED_POLICIES:
        for seed in task["seeds"]:
            name = f"{task['budget']}-{policy}-seed{seed}"
            path = output / f"{name}.taers"
            metrics = evaluate_stream(
                path,
                timestamps,
                values,
                model,
                cases,
                normal,
                config,
                task["start_us"],
                task["end_us"],
            )
            if metrics["packets"] != expected_packets:
                raise ValueError("Randomized arm omitted an active epoch")
            metrics["packet_stream_sha256"] = sha256(path)
            metrics["config"] = asdict(config)
            metrics["seed"] = seed
            metrics["policy"] = policy
            atomic_text(
                output / "arms" / f"{name}.json",
                json.dumps(metrics, indent=2, allow_nan=False) + "\n",
            )
            runs[name] = compact_metrics(metrics)
    print(f"Cap {task['budget']}: decoded evaluation complete", flush=True)
    return runs


def describe(values):
    values = np.asarray(values, dtype=float)
    return dict(
        mean=float(values.mean()),
        minimum=float(values.min()),
        maximum=float(values.max()),
        standard_deviation=float(values.std(ddof=1)) if len(values) > 1 else 0.0,
    )


def summarize_runs(runs, reference, budgets, seeds):
    groups = {}
    for budget in budgets:
        for policy in RANDOMIZED_POLICIES:
            selected = [runs[f"{budget}-{policy}-seed{seed}"] for seed in seeds]
            groups[f"{budget}-{policy}"] = dict(
                seeds=len(seeds),
                actual_bytes=describe([run["serialized_bytes"] for run in selected]),
                raw_events=describe(
                    [run["events_with_raw_evidence"] for run in selected]
                ),
                pca_events=describe(
                    [run["receivers"]["pca"]["detected_events"] for run in selected]
                ),
                level_events=describe(
                    [run["receivers"]["level"]["detected_events"] for run in selected]
                ),
                context_coverage=describe(
                    [run["macro_pre_context_coverage"] for run in selected]
                ),
                event_pca_retention_frequency={
                    event_id: sum(
                        run["events"][event_id]["receivers"]["pca"]["evidence"]
                        for run in selected
                    )
                    / len(selected)
                    for event_id in selected[0]["events"]
                },
            )
    controls = {
        name: compact_metrics(metrics)
        for name, metrics in reference["arms"].items()
        if int(name.split("-")[0]) in budgets and not name.endswith("-summaries")
    }
    return dict(groups=groups, deterministic_controls=controls)


def write_latex(report, path):
    rows = [
        "% Generated randomized validation comparison; seed ranges are not event confidence intervals.",
        r"\begin{tabular}{rlrrr}",
        r"\toprule",
        r"Cap & Policy & Mean MiB & PCA events: mean [range] & Context (\%) \\",
        r"\midrule",
    ]
    for name, group in report["summary"]["groups"].items():
        budget, policy = name.split("-", 1)
        label = {"reservoir": "Reservoir", "randomized_uniform": "Random phase"}[policy]
        hits = group["pca_events"]
        rows.append(
            f"{budget} & {label} & {group['actual_bytes']['mean']/2**20:.2f} & "
            f"{hits['mean']:.1f} [{hits['minimum']:.0f}, {hits['maximum']:.0f}] & "
            f"{100*group['context_coverage']['mean']:.1f} " + r"\\"
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    atomic_text(path, "\n".join(rows) + "\n")


def run_study(
    source, dataset, cache, baseline_dir, output, seeds=tuple(range(10)), workers=4
):
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**64 for seed in seeds)
    ):
        raise ValueError("Specify distinct unsigned 64-bit seeds")
    if type(workers) is not int or workers < 1:
        raise ValueError("Worker count must be positive")
    header, annotations = verify_dataset(dataset)
    reference = json.loads((baseline_dir / "report.json").read_text())
    _, _, native_manifest = open_native_source(source, dataset, cache, header)
    validate_reference(reference, baseline_dir, dataset, cache, header)
    model = load_frozen_model(reference["model"])
    if output.resolve() in [
        path.resolve() for path in [source, dataset, cache, baseline_dir]
    ]:
        raise ValueError("Study output must be separate from all inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory to preserve completed runs")
    prior = reference["provenance"]
    budgets = prior["budgets"]
    tasks = [
        dict(
            cache=str(cache.resolve()),
            output=str(output.resolve()),
            start_us=prior["start_us"],
            end_us=prior["end_us"],
            epoch_us=prior["epoch_us"],
            context_us=prior["context_us"],
            budget=budget,
            seeds=list(seeds),
        )
        for budget in budgets
    ]
    provenance = dict(
        protocol="native-randomized-comparison-v1",
        reference_report_sha256=sha256(baseline_dir / "report.json"),
        native_manifest_sha256=sha256(cache / "manifest.json"),
        source_files=native_manifest["files"],
        dataset_manifest_sha256=sha256(dataset / "manifest.json"),
        frozen_model_sha256=sha256(baseline_dir / "model.json"),
        scripts={
            path.name: sha256(path)
            for path in [
                Path(__file__),
                *sorted((Path(__file__).parent / "retention").glob("*.py")),
            ]
        },
        seeds=list(seeds),
        budgets=budgets,
        workers=workers,
        python=platform.python_version(),
        numpy=np.__version__,
        start_us=prior["start_us"],
        end_us=prior["end_us"],
        phase="validation development, not held-out",
        randomization="SHA-256(policy:seed:epoch) -> Python Random; budget omitted for common random numbers",
    )
    atomic_text(output / "protocol.json", json.dumps(provenance, indent=2) + "\n")
    started = time.perf_counter()
    if workers == 1:
        timings = [capture_budget(task) for task in tasks]
        evaluated = [
            evaluate_budget(
                (task, model.to_dict(), annotations, reference["active_epochs"])
            )
            for task in tasks
        ]
    else:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            timings = list(pool.map(capture_budget, tasks))
            # Do not provide evaluation labels to a replay task or evaluate an unfinished capture stage.
            evaluated = list(
                pool.map(
                    evaluate_budget,
                    [
                        (task, model.to_dict(), annotations, reference["active_epochs"])
                        for task in tasks
                    ],
                )
            )
    runs = {name: metrics for result in evaluated for name, metrics in result.items()}
    report = dict(
        provenance=provenance,
        model=model.to_dict(),
        source_observations=reference["source_observations"],
        source_eligible_events=reference["full_archive"]["source_eligible_events"],
        summary=summarize_runs(runs, reference, budgets, seeds),
        runs=runs,
        capture_timings=timings,
        total_seconds=time.perf_counter() - started,
        interpretation="Seed ranges measure sampling variation on fixed events, not generalization confidence",
    )
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/ESA-Mission1"))
    parser.add_argument("--dataset", type=Path, default=Path("data/processed"))
    parser.add_argument("--cache", type=Path, default=Path("data/native"))
    parser.add_argument(
        "--baseline", type=Path, default=Path("data/results/retention-native")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/results/retention-randomized")
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--latex", type=Path)
    args = parser.parse_args()
    report = run_study(
        args.source,
        args.dataset,
        args.cache,
        args.baseline,
        args.output,
        tuple(args.seeds),
        args.workers,
    )
    if args.latex:
        write_latex(report, args.latex)
    print(json.dumps(report["summary"]["groups"], indent=2))


if __name__ == "__main__":
    main()
