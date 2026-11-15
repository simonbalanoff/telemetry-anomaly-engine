"""Native Mission1 validation replay with a common byte-budget sweep.

No test-partition mode is provided. Native archives are trusted local inputs;
large observations and packet streams remain gitignored.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import time

import numpy as np
import pandas as pd

from dataset import atomic_text, sha256, verify_dataset
from retention.codec import HEADER, RAW_BYTES, Sample
from retention.native_metrics import NativeEvaluator, build_event_cases, evaluate_stream
from retention.native_model import CHUNK, causal_capture_scores, fit_native_model
from retention.native_source import open_native_source
from retention.recorder import Recorder, RecorderConfig


def replay(timestamps, values, capture_scores, configs, output):
    """Capture inputs deliberately exclude annotations and receiver outcomes."""
    recorders = {
        name: Recorder(policy, config) for name, (policy, config) in configs.items()
    }
    streams = {name: (output / f"{name}.taers").open("wb") for name in recorders}
    started = time.perf_counter()
    try:
        for index, (timestamp, row, score) in enumerate(
            zip(timestamps, values, capture_scores)
        ):
            sample = Sample(int(timestamp), tuple(row))
            for name, recorder in recorders.items():
                packet = recorder.observe(sample, float(score))
                if packet is not None:
                    streams[name].write(packet.encode())
            if index and index % 250000 == 0:
                print(
                    f"Replayed {index:,}/{len(timestamps):,} native observations",
                    flush=True,
                )
        for name, recorder in recorders.items():
            packet = recorder.finish()
            if packet is not None:
                streams[name].write(packet.encode())
    finally:
        for stream in streams.values():
            stream.close()
    return time.perf_counter() - started


def full_archive_reference(
    timestamps, values, model, cases, normal, config, start, end
):
    evaluator = NativeEvaluator(
        timestamps, values, model, cases, normal, config.epoch_us, start, end
    )
    evaluator.retained[:] = True
    for first in range(0, len(timestamps), CHUNK):
        stop = min(first + CHUNK, len(timestamps))
        evaluator.positive[first:stop] = (
            model.scores(values[first:stop]) > model.thresholds
        )
    evaluator.packet_count = len(np.unique(timestamps // config.epoch_us))
    evaluator.bytes = evaluator.packet_count * HEADER.size + len(timestamps) * RAW_BYTES
    report = evaluator.report(config.budget_bytes)
    report.update(
        kind="unconstrained_full_archive_reference",
        allocated_bytes=None,
        maximum_packet_bytes=None,
        byte_measurement="Calculated from exact raw-record schema; not serialized",
    )
    return report


def write_latex(report, path):
    rows = [
        "% Generated native validation pilot; development results only.",
        r"\begin{tabular}{rlrrrr}",
        r"\toprule",
        r"Cap & Policy & MiB & Raw events & Level & PCA \\",
        r"\midrule",
    ]
    for name, metrics in report["arms"].items():
        budget, policy = name.split("-", 1)
        total = metrics["source_eligible_events"]
        receivers = metrics["receivers"]
        level = (
            f"{receivers['level']['detected_events']}/{total}"
            if receivers["level"]["supported"]
            else "--"
        )
        pca = (
            f"{receivers['pca']['detected_events']}/{total}"
            if receivers["pca"]["supported"]
            else "--"
        )
        rows.append(
            f"{budget} & {policy.capitalize()} & {metrics['serialized_bytes']/2**20:.2f} & "
            f"{metrics['events_with_raw_evidence']}/{total} & {level} & {pca} " + r"\\"
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    atomic_text(path, "\n".join(rows) + "\n")


def run_pilot(
    source,
    dataset,
    cache,
    output,
    start_us,
    end_us,
    budgets=(256, 512, 1024, 2048),
    epoch_us=3600000000,
    threshold=6.0,
    context_us=300000000,
):
    header, events = verify_dataset(dataset)
    if not header.validation_start_us <= start_us < end_us <= header.test_start_us:
        raise ValueError("Pilot must remain entirely inside validation")
    if start_us % epoch_us or end_us % epoch_us:
        raise ValueError("Pilot boundaries must align to complete reporting epochs")
    configs = {
        f"{budget}-{policy}": (
            policy,
            RecorderConfig(epoch_us=epoch_us, budget_bytes=budget, threshold=threshold),
        )
        for budget in sorted(set(budgets))
        for policy in Recorder.POLICIES
    }
    if not configs:
        raise ValueError("Specify at least one budget")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError(
            "Use an empty output directory; pilot artifacts must not be overwritten"
        )
    timestamps, values, source_manifest = open_native_source(
        source, dataset, cache, header
    )
    print(f"Native source verified: {len(timestamps):,} observations", flush=True)
    started = time.perf_counter()
    model = fit_native_model(
        timestamps,
        values,
        events,
        header.validation_start_us,
        output / "training_scores.npy",
    )
    atomic_text(output / "model.json", json.dumps(model.to_dict(), indent=2) + "\n")
    print(
        f"Trained frozen receivers on {model.training_count:,} eligible native observations",
        flush=True,
    )
    left, right = np.searchsorted(timestamps, [start_us, end_us])
    native_times, native_values = timestamps[left:right], values[left:right]
    if not len(native_times):
        raise ValueError("No native observations in pilot interval")
    capture = causal_capture_scores(native_times, native_values, model.sigma)
    provenance = dict(
        protocol="native-retention-pilot-v1",
        dataset_manifest_sha256=sha256(dataset / "manifest.json"),
        native_manifest_sha256=sha256(cache / "manifest.json"),
        source_files=source_manifest["files"],
        scripts={
            path.name: sha256(path)
            for path in [
                Path(__file__),
                Path(__file__).parent / "convert_esa.py",
                Path(__file__).parent / "dataset.py",
                *sorted((Path(__file__).parent / "retention").glob("*.py")),
            ]
        },
        python=platform.python_version(),
        numpy=np.__version__,
        start_us=start_us,
        end_us=end_us,
        budgets=sorted(set(budgets)),
        epoch_us=epoch_us,
        context_us=context_us,
        capture_threshold=threshold,
        capture_reset_gap_us=150000000,
        receiver_quantile=0.999,
        pca_components=3,
        receiver_comparison="strictly greater than frozen threshold",
        phase="validation development, not held-out",
    )
    atomic_text(output / "protocol.json", json.dumps(provenance, indent=2) + "\n")
    replay_seconds = replay(native_times, native_values, capture, configs, output)
    # Capture is complete. Only now are validation labels made available to evaluation.
    cases, eligible, normal = build_event_cases(
        native_times, events, start_us, end_us, context_us
    )
    expected_packets = len(np.unique(native_times // epoch_us))
    report = dict(
        provenance=provenance,
        model=model.to_dict(),
        source_observations=len(native_times),
        active_epochs=expected_packets,
        excluded_source_observations=int(np.count_nonzero(~eligible)),
        full_archive=full_archive_reference(
            native_times,
            native_values,
            model,
            cases,
            normal,
            next(iter(configs.values()))[1],
            start_us,
            end_us,
        ),
        arms={},
        replay_seconds=replay_seconds,
        timing_scope="Combined Python replay for all arms; not individual embedded latency",
    )
    for name, (_, config) in configs.items():
        print(f"Evaluating decoded stream: {name}", flush=True)
        path = output / f"{name}.taers"
        metrics = evaluate_stream(
            path,
            native_times,
            native_values,
            model,
            cases,
            normal,
            config,
            start_us,
            end_us,
        )
        if metrics["packets"] != expected_packets:
            raise ValueError("Policy omitted an active epoch")
        metrics["packet_stream_sha256"] = sha256(path)
        metrics["config"] = asdict(config)
        report["arms"][name] = metrics
    report["total_seconds"] = time.perf_counter() - started
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/ESA-Mission1"))
    parser.add_argument("--dataset", type=Path, default=Path("data/processed"))
    parser.add_argument("--cache", type=Path, default=Path("data/native"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/results/retention-native")
    )
    parser.add_argument("--start", default="2008-01-01T00:00:00Z")
    parser.add_argument("--end", default="2011-01-01T00:00:00Z")
    parser.add_argument(
        "--budgets", type=int, nargs="+", default=[256, 512, 1024, 2048]
    )
    parser.add_argument("--latex", type=Path)
    return parser.parse_args()


def main():
    args = parse_arguments()
    for path in [args.source, args.dataset, args.cache]:
        if args.output.resolve() == path.resolve():
            raise ValueError(
                "Pilot output must be separate from source, dataset, and cache"
            )
    report = run_pilot(
        args.source,
        args.dataset,
        args.cache,
        args.output,
        int(pd.Timestamp(args.start).value // 1000),
        int(pd.Timestamp(args.end).value // 1000),
        args.budgets,
    )
    if args.latex:
        write_latex(report, args.latex)
    print(
        json.dumps(
            {
                name: dict(
                    bytes=metrics["serialized_bytes"],
                    raw_events=metrics["events_with_raw_evidence"],
                )
                for name, metrics in report["arms"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
