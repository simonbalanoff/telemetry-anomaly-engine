"""Native development benchmark: capture/receiver mismatch and downlink losses.

The original pilot and seeded streams are verified and reused. New capture arms
never receive evaluation annotations. Results on this previously used validation
archive are development evidence, not independent generalization.
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
from retention.benchmark_metrics import evaluate_bank_stream
from retention.codec import Sample
from retention.coverage import CoverageRecorder
from retention.downlink import LinkConfig, simulate
from retention.native_metrics import build_event_cases
from retention.native_model import CHUNK, causal_capture_scores
from retention.native_source import open_native_source
from retention.receiver_bank import CAPTURE_MODELS, NAMES, ReceiverBank, fit_bank
from retention.recorder import Recorder, RecorderConfig
from run_retention_randomized import load_frozen_model, validate_reference

POLICIES = ("threshold", "adaptive", "coverage")
SCENARIOS = {
    "ample": LinkConfig(wire_bytes_per_contact=32768),
    "congested": LinkConfig(wire_bytes_per_contact=2048, buffer_bytes=4096),
    "lossy": LinkConfig(wire_bytes_per_contact=32768, loss_probability=0.1, seed=0),
}


def capture_budget(task):
    """No labels, event cases, or receiver outcomes enter this replay worker."""
    times = np.load(task["times"], mmap_mode="r", allow_pickle=False)
    values = np.load(task["values"], mmap_mode="r", allow_pickle=False)
    scores = np.load(task["capture_scores"], mmap_mode="r", allow_pickle=False)
    config = RecorderConfig(**task["config"])
    recorders = {}
    for column, mode in enumerate(CAPTURE_MODELS):
        for policy in POLICIES:
            if mode == "difference" and policy != "coverage":
                continue  # Reuse these exact original pilot streams.
            name = f"{config.budget_bytes}-{mode}-{policy}"
            recorder = (
                CoverageRecorder(config, task["mean"], task["sigma"])
                if policy == "coverage"
                else Recorder(policy, config)
            )
            recorders[name] = (recorder, column)
    output = Path(task["output"])
    streams = {name: (output / f"{name}.taers").open("wb") for name in recorders}
    try:
        for timestamp, row, captured in zip(times, values, scores):
            sample = Sample(int(timestamp), tuple(row))
            for name, (recorder, column) in recorders.items():
                packet = recorder.observe(sample, float(captured[column]))
                if packet is not None:
                    streams[name].write(packet.encode())
        for name, (recorder, _) in recorders.items():
            packet = recorder.finish()
            if packet is not None:
                streams[name].write(packet.encode())
    finally:
        for stream in streams.values():
            stream.close()
    print(f"Cap {config.budget_bytes}: mismatch capture complete", flush=True)


def evaluate_budget(payload):
    task, annotations, streams = payload
    times = np.load(task["times"], mmap_mode="r", allow_pickle=False)
    values = np.load(task["values"], mmap_mode="r", allow_pickle=False)
    captures = np.load(task["capture_scores"], mmap_mode="r", allow_pickle=False)
    positive = np.load(task["positive"], mmap_mode="r", allow_pickle=False)
    config = RecorderConfig(**task["config"])
    cases, eligible, normal = build_event_cases(
        times, annotations, task["start_us"], task["end_us"], task["context_us"]
    )
    output = Path(task["output"])
    result = {}
    for name, path_string in streams.items():
        path = Path(path_string)
        mode = name.split("-")[1]
        capture_scores = (
            captures[:, CAPTURE_MODELS.index(mode)] if mode in CAPTURE_MODELS else None
        )
        metrics = evaluate_bank_stream(
            path,
            times,
            values,
            positive,
            cases,
            eligible,
            normal,
            config,
            task["start_us"],
            task["end_us"],
            capture_scores,
            context_us=task["context_us"],
        )
        metrics.update(packet_stream_sha256=sha256(path), config=asdict(config))
        if metrics["packets"] != task["active_epochs"]:
            raise ValueError("Capture omitted an active epoch")
        result[name] = metrics
        if (
            name.endswith("difference-adaptive")
            or name.endswith("difference-coverage")
            or name.endswith("uniform")
        ):
            metrics["delivery"] = {}
            for scenario, link in SCENARIOS.items():
                delivered = output / f"{name}-{scenario}.delivered.taers"
                transport = simulate(
                    path, delivered, link, task["start_us"], task["end_us"]
                )
                evidence = evaluate_bank_stream(
                    delivered,
                    times,
                    values,
                    positive,
                    cases,
                    eligible,
                    normal,
                    config,
                    task["start_us"],
                    task["end_us"],
                    capture_scores,
                    transport["delivered_at_us"],
                    task["context_us"],
                )
                transport.pop("delivered_at_us")
                metrics["delivery"][scenario] = dict(
                    transport=transport,
                    evidence=evidence,
                    packet_stream_sha256=sha256(delivered),
                )
    print(
        f"Cap {config.budget_bytes}: mismatch/delivery evaluation complete", flush=True
    )
    return result


def run_study(
    source,
    dataset,
    cache,
    baseline,
    randomized,
    output,
    budgets=None,
    seeds=tuple(range(10)),
    workers=4,
):
    if type(workers) is not int or workers < 1:
        raise ValueError("Worker count must be positive")
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**64 for seed in seeds)
    ):
        raise ValueError("Specify distinct unsigned 64-bit seeds")
    header, annotations = verify_dataset(dataset)
    reference = json.loads((baseline / "report.json").read_text())
    timestamps, values, _ = open_native_source(source, dataset, cache, header)
    validate_reference(reference, baseline, dataset, cache, header)
    controls = json.loads((randomized / "report.json").read_text())
    if controls["model"] != reference["model"] or controls["provenance"][
        "reference_report_sha256"
    ] != sha256(baseline / "report.json"):
        raise ValueError("Randomized controls belong to a different reference")
    prior = reference["provenance"]
    budgets = list(prior["budgets"] if budgets is None else budgets)
    if (
        not budgets
        or len(set(budgets)) != len(budgets)
        or not set(budgets) <= set(prior["budgets"])
    ):
        raise ValueError("Choose distinct caps from the frozen pilot")
    streams_by_budget = {}
    for budget in budgets:
        streams = {
            f"{budget}-difference-{p}": str(
                (baseline / f"{budget}-{p}.taers").resolve()
            )
            for p in ("threshold", "adaptive")
        }
        streams[f"{budget}-uniform"] = str(
            (baseline / f"{budget}-uniform.taers").resolve()
        )
        for policy in ("reservoir", "randomized_uniform"):
            for seed in seeds:
                name = f"{budget}-{policy}-seed{seed}"
                path = randomized / f"{name}.taers"
                if (
                    name not in controls["runs"]
                    or sha256(path) != controls["runs"][name]["packet_stream_sha256"]
                ):
                    raise ValueError(f"Missing or changed randomized arm: {name}")
                streams[name] = str(path.resolve())
        streams_by_budget[budget] = streams
    if output.resolve() in {
        p.resolve() for p in (source, dataset, cache, baseline, randomized)
    }:
        raise ValueError("Output must be separate from benchmark inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    provenance = dict(
        protocol="receiver-mismatch-v1",
        phase="Mission1 validation development, not held-out",
        reference_sha256=sha256(baseline / "report.json"),
        randomized_sha256=sha256(randomized / "report.json"),
        scripts={
            p.name: sha256(p)
            for p in [
                Path(__file__),
                *sorted((Path(__file__).parent / "retention").glob("*.py")),
            ]
        },
        budgets=budgets,
        seeds=list(seeds),
        capture_models=list(CAPTURE_MODELS),
        receiver_names=list(NAMES),
        link_scenarios={name: asdict(link) for name, link in SCENARIOS.items()},
        python=platform.python_version(),
        numpy=np.__version__,
    )
    atomic_text(output / "protocol.json", json.dumps(provenance, indent=2) + "\n")
    started = time.perf_counter()
    original = load_frozen_model(reference["model"])
    # Pass only training annotations to additional receiver calibration.
    training_events = [
        row for row in annotations if row["start_us"] < original.training_end_us
    ]
    bank = fit_bank(timestamps, values, training_events, original, output)
    atomic_text(output / "receivers.json", json.dumps(bank.to_dict(), indent=2) + "\n")
    left, right = np.searchsorted(timestamps, [prior["start_us"], prior["end_us"]])
    times, observations = timestamps[left:right], values[left:right]
    np.save(output / "validation_times.npy", times)
    np.save(output / "validation_values.npy", observations)
    positive = np.lib.format.open_memmap(
        output / "positive.npy", mode="w+", dtype=bool, shape=(len(times), len(NAMES))
    )
    captures = np.lib.format.open_memmap(
        output / "capture_scores.npy",
        mode="w+",
        dtype="<f8",
        shape=(len(times), len(CAPTURE_MODELS)),
    )
    captures[:, 0] = causal_capture_scores(times, observations, original.sigma)
    for first in range(0, len(times), CHUNK):
        stop = min(first + CHUNK, len(times))
        scores = bank.scores(observations[first:stop])
        positive[first:stop] = scores > bank.thresholds
        captures[first:stop, 1] = scores[:, 0]
        captures[first:stop, 2] = (
            scores[:, 3] / bank.thresholds[3] * prior["capture_threshold"]
            if bank.thresholds[3] > 0
            else (scores[:, 3] > 0) * prior["capture_threshold"]
        )
        captures[first:stop, 3] = 0
    positive.flush()
    captures.flush()
    tasks = []
    for budget in budgets:
        config = RecorderConfig(**reference["arms"][f"{budget}-adaptive"]["config"])
        task = dict(
            times=str((output / "validation_times.npy").resolve()),
            values=str((output / "validation_values.npy").resolve()),
            capture_scores=str((output / "capture_scores.npy").resolve()),
            positive=str((output / "positive.npy").resolve()),
            output=str(output.resolve()),
            config=asdict(config),
            mean=original.mean.tolist(),
            sigma=original.sigma.tolist(),
            start_us=prior["start_us"],
            end_us=prior["end_us"],
            context_us=prior["context_us"],
            active_epochs=reference["active_epochs"],
        )
        tasks.append(task)
        for mode in CAPTURE_MODELS:
            for policy in POLICIES:
                name = f"{budget}-{mode}-{policy}"
                streams_by_budget[budget].setdefault(
                    name, str((output / f"{name}.taers").resolve())
                )
    if workers == 1:
        for task in tasks:
            capture_budget(task)
        evaluated = [
            evaluate_budget(
                (task, annotations, streams_by_budget[task["config"]["budget_bytes"]])
            )
            for task in tasks
        ]
    else:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            list(pool.map(capture_budget, tasks))
            evaluated = list(
                pool.map(
                    evaluate_budget,
                    [
                        (
                            task,
                            annotations,
                            streams_by_budget[task["config"]["budget_bytes"]],
                        )
                        for task in tasks
                    ],
                )
            )
    report = dict(
        provenance=provenance,
        receivers=bank.to_dict(),
        source_observations=len(times),
        arms={
            name: metrics for result in evaluated for name, metrics in result.items()
        },
        total_seconds=time.perf_counter() - started,
        interpretation="Correlated PCA ranks are sensitivity analyses, not independent faults. Within-event trigger blindness excludes no eligible events. Disabled trigger and contact schedules are explicit stress controls.",
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
        ("baseline", "data/results/retention-native"),
        ("randomized", "data/results/retention-randomized"),
        ("output", "data/results/retention-benchmark"),
    ):
        parser.add_argument(f"--{name}", type=Path, default=Path(default))
    parser.add_argument("--budgets", type=int, nargs="+")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    report = run_study(
        args.source,
        args.dataset,
        args.cache,
        args.baseline,
        args.randomized,
        args.output,
        args.budgets,
        tuple(args.seeds),
        args.workers,
    )
    print(f"Completed {len(report['arms'])} arms")


if __name__ == "__main__":
    main()
