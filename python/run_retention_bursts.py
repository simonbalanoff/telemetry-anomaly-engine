"""Exploratory adjacent-pair background test after observing receiver mismatch."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from dataset import atomic_text, sha256, verify_dataset
from retention.benchmark_metrics import evaluate_bank_stream
from retention.burst import BurstRecorder
from retention.codec import Sample
from retention.forecast import ForecastReceiver
from retention.native_metrics import build_event_cases
from retention.native_source import open_native_source
from retention.native_model import CHUNK, causal_capture_scores
from retention.receiver_bank import ReceiverBank
from run_retention_randomized import load_frozen_model
from retention.recorder import RecorderConfig
from run_retention_randomized import validate_reference
from run_retention_sequence import evaluate as evaluate_forecast


def run_study(source, dataset, cache, baseline, benchmark, sequence, output):
    header, events = verify_dataset(dataset)
    reference = json.loads((baseline / "report.json").read_text())
    native_times, native_values, _ = open_native_source(source, dataset, cache, header)
    validate_reference(reference, baseline, dataset, cache, header)
    mismatch = json.loads((benchmark / "report.json").read_text())
    temporal = json.loads((sequence / "report.json").read_text())
    if temporal["benchmark_sha256"] != sha256(benchmark / "report.json"):
        raise ValueError("Temporal model belongs to a different benchmark")
    if mismatch["provenance"]["reference_sha256"] != sha256(baseline / "report.json"):
        raise ValueError("Mismatch reference differs")
    if output.resolve() in {
        p.resolve() for p in (source, dataset, cache, baseline, benchmark, sequence)
    }:
        raise ValueError("Output must be separate from inputs")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    prior = reference["provenance"]
    left, right = np.searchsorted(native_times, [prior["start_us"], prior["end_us"]])
    times, values = native_times[left:right], native_values[left:right]
    original = load_frozen_model(reference["model"])
    captures = np.zeros((len(times), 4))
    captures[:, 0] = causal_capture_scores(times, values, original.sigma)
    bank = ReceiverBank.from_dict(mismatch["receivers"])
    positive = np.lib.format.open_memmap(
        output / "positive.npy", mode="w+", dtype=bool, shape=(len(times), 6)
    )
    for first in range(0, len(times), CHUNK):
        stop = min(first + CHUNK, len(times))
        positive[first:stop] = bank.scores(values[first:stop]) > bank.thresholds
    positive.flush()
    configs = {
        f"{budget}-{mode}-burst": RecorderConfig(
            **reference["arms"][f"{budget}-adaptive"]["config"]
        )
        for budget in mismatch["provenance"]["budgets"]
        for mode in ("difference", "disabled")
    }
    provenance = dict(
        protocol="adjacent-pair-background-v1",
        phase="exploratory Mission1 validation; motivated by observed temporal receiver failure",
        benchmark_sha256=sha256(benchmark / "report.json"),
        sequence_sha256=sha256(sequence / "report.json"),
        scripts={
            p.name: sha256(p)
            for p in (Path(__file__), Path(__file__).parent / "retention/burst.py")
        },
        configs={name: asdict(config) for name, config in configs.items()},
    )
    atomic_text(output / "protocol.json", json.dumps(provenance, indent=2) + "\n")
    recorders = {name: BurstRecorder(config) for name, config in configs.items()}
    streams = {name: (output / f"{name}.taers").open("xb") for name in recorders}
    try:
        for timestamp, row, scores in zip(times, values, captures):
            sample = Sample(int(timestamp), tuple(row))
            for name, recorder in recorders.items():
                packet = recorder.observe(
                    sample, float(scores[0]) if "-difference-" in name else 0.0
                )
                if packet is not None:
                    streams[name].write(packet.encode())
        for name, recorder in recorders.items():
            packet = recorder.finish()
            if packet is not None:
                streams[name].write(packet.encode())
    finally:
        for stream in streams.values():
            stream.close()
    model_data = temporal["model"]
    model = ForecastReceiver(
        **{
            name: np.asarray(value) if isinstance(value, list) else value
            for name, value in model_data.items()
        }
    )
    scores = model.scores(times, values)
    forecast_positive = np.isfinite(scores) & (scores > model.threshold)
    cases, eligible, normal = build_event_cases(
        times, events, prior["start_us"], prior["end_us"], prior["context_us"]
    )
    arms = {}
    for name, config in configs.items():
        path = output / f"{name}.taers"
        capture = captures[:, 0] if "-difference-" in name else captures[:, 3]
        metrics = evaluate_bank_stream(
            path,
            times,
            values,
            positive,
            cases,
            eligible,
            normal,
            config,
            prior["start_us"],
            prior["end_us"],
            capture,
            context_us=prior["context_us"],
        )
        if metrics["packets"] != reference["active_epochs"]:
            raise ValueError("Burst arm omitted an active epoch")
        metrics.update(
            forecast=evaluate_forecast(
                path, times, values, forecast_positive, cases, normal
            ),
            config=asdict(config),
            packet_stream_sha256=sha256(path),
        )
        arms[name] = metrics
    report = dict(
        provenance=provenance,
        arms=arms,
        interpretation="Paired background trades spread for transitions. Same cap, not necessarily equal expenditure. Developed after inspecting validation; independent confirmation required.",
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
        ("benchmark", "data/results/retention-benchmark"),
        ("sequence", "data/results/retention-sequence"),
        ("output", "data/results/retention-bursts"),
    ):
        parser.add_argument(f"--{name}", type=Path, default=Path(default))
    args = parser.parse_args()
    run_study(
        args.source,
        args.dataset,
        args.cache,
        args.baseline,
        args.benchmark,
        args.sequence,
        args.output,
    )


if __name__ == "__main__":
    main()
