"""Lock and run a cross-mission study with training-only receiver calibration.

Freeze the protocol and input identity before running. A lock records intent and
hashes; it cannot prove that a human has never inspected evaluation labels.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform

import numpy as np

from dataset import atomic_text, sha256
from retention.codec import Sample
from retention.diagnostics import event_characteristics, summarize_strata
from retention.mission import code_hashes, open_bundle, read_events
from retention.native_metrics import build_event_cases, evaluate_stream
from retention.native_model import causal_capture_scores, fit_native_model
from retention.randomized import RANDOMIZED_POLICIES, RandomizedRecorder
from retention.recorder import Recorder, RecorderConfig
from run_retention_ablations import ablation_configs
from run_retention_pilot import full_archive_reference


def validate_settings(settings):
    expected = {
        "protocol",
        "development_mission",
        "epoch_us",
        "budgets",
        "threshold",
        "pre_trigger_samples",
        "post_trigger_samples",
        "background_fraction",
        "context_us",
        "receiver_quantile",
        "pca_components",
        "seeds",
    }
    if (
        set(settings) != expected
        or settings["protocol"] != "cross-mission-retention-v1"
    ):
        raise ValueError("Unsupported protocol settings")
    if (
        not isinstance(settings["development_mission"], str)
        or not settings["development_mission"]
    ):
        raise ValueError("Declare the development mission")
    if (
        not settings["budgets"]
        or len(set(settings["budgets"])) != len(settings["budgets"])
        or type(settings["context_us"]) is not int
        or settings["context_us"] < 0
        or not 0 < settings["receiver_quantile"] < 1
        or type(settings["pca_components"]) is not int
        or not 1 <= settings["pca_components"] < 6
    ):
        raise ValueError("Invalid evaluation or receiver settings")
    seeds = settings["seeds"]
    if (
        not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(s) is not int or not 0 <= s < 2**64 for s in seeds)
    ):
        raise ValueError("Specify distinct unsigned 64-bit seeds")
    for budget in settings["budgets"]:
        base_config(settings, budget)


def base_config(settings, budget):
    return RecorderConfig(
        **{
            key: settings[key]
            for key in (
                "epoch_us",
                "threshold",
                "pre_trigger_samples",
                "post_trigger_samples",
                "background_fraction",
            )
        },
        budget_bytes=budget,
    )


def freeze(bundle, settings_path, lock_path):
    if lock_path.exists():
        raise ValueError("Lock already exists; preserve the original protocol")
    settings = json.loads(settings_path.read_text())
    validate_settings(settings)
    _, _, manifest = open_bundle(bundle)
    if (
        manifest["mission"].strip().casefold()
        == settings["development_mission"].strip().casefold()
    ):
        raise ValueError("Cross-mission evaluation requires a different mission")
    for key in ("evaluation_start_us", "evaluation_end_us"):
        if manifest[key] % settings["epoch_us"]:
            raise ValueError("Evaluation boundaries must align to complete epochs")
    lock = dict(
        settings=settings,
        target_mission=manifest["mission"],
        bundle_manifest_sha256=sha256(bundle / "manifest.json"),
        settings_sha256=sha256(settings_path),
        scripts=code_hashes(),
        interpretation="Training-calibrated transfer of fixed retention settings; not zero-shot receiver transfer or proof of label blindness",
    )
    atomic_text(lock_path, json.dumps(lock, indent=2, allow_nan=False) + "\n")
    return lock


def make_recorders(settings, budget):
    config = base_config(settings, budget)
    recorders = {policy: Recorder(policy, config) for policy in Recorder.POLICIES}
    configs = {policy: config for policy in recorders}
    for name, variant in ablation_configs(config).items():
        if name != "full":
            recorders[name] = Recorder("adaptive", variant)
            configs[name] = variant
    for policy in RANDOMIZED_POLICIES:
        for seed in settings["seeds"]:
            name = f"{policy}-seed{seed}"
            recorders[name] = RandomizedRecorder(policy, config, seed)
            configs[name] = config
    return recorders, configs


def capture(timestamps, values, scores, settings, output):
    """No training/evaluation annotations enter this stage."""
    configs = {}
    # One budget at a time bounds recorder state and open file handles.
    for budget in settings["budgets"]:
        recorders, variants = make_recorders(settings, budget)
        streams = {
            name: (output / f"{budget}-{name}.taers").open("wb") for name in recorders
        }
        try:
            for timestamp, row, score in zip(timestamps, values, scores):
                sample = Sample(int(timestamp), tuple(row))
                for name, recorder in recorders.items():
                    packet = recorder.observe(sample, float(score))
                    if packet is not None:
                        streams[name].write(packet.encode())
            for name, recorder in recorders.items():
                packet = recorder.finish()
                if packet is not None:
                    streams[name].write(packet.encode())
        finally:
            for stream in streams.values():
                stream.close()
        configs.update(
            {f"{budget}-{name}": config for name, config in variants.items()}
        )
        print(f"Cap {budget}: capture complete", flush=True)
    return configs


def run_study(bundle, lock_path, output):
    lock = json.loads(lock_path.read_text())
    settings = lock["settings"]
    validate_settings(settings)
    if lock["scripts"] != code_hashes():
        raise ValueError(
            "Code differs from frozen protocol; preserve and explicitly revise the lock"
        )
    if lock["bundle_manifest_sha256"] != sha256(bundle / "manifest.json"):
        raise ValueError("Input manifest differs from frozen protocol")
    timestamps, values, manifest = open_bundle(bundle)
    if manifest["mission"] != lock["target_mission"]:
        raise ValueError("Target mission differs from protocol")
    if output.resolve() == bundle.resolve():
        raise ValueError("Output must be separate from mission bundle")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory; completed runs are immutable")
    atomic_text(output / "protocol.json", json.dumps(lock, indent=2) + "\n")
    train_events = read_events(
        bundle / "training_events.json", 0, manifest["training_end_us"]
    )
    model = fit_native_model(
        timestamps,
        values,
        train_events,
        manifest["training_end_us"],
        output / "training_scores.npy",
        settings["receiver_quantile"],
        settings["pca_components"],
    )
    atomic_text(output / "model.json", json.dumps(model.to_dict(), indent=2) + "\n")
    start, end = manifest["evaluation_start_us"], manifest["evaluation_end_us"]
    left, right = np.searchsorted(timestamps, [start, end])
    times, observations = timestamps[left:right], values[left:right]
    scores = causal_capture_scores(times, observations, model.sigma)
    configs = capture(times, observations, scores, settings, output)
    # Evaluation annotations are parsed for the first time after every capture ends.
    events = read_events(bundle / "evaluation_events.json", start, end)
    cases, _, normal = build_event_cases(
        times, events, start, end, settings["context_us"]
    )
    expected_packets = len(np.unique(times // settings["epoch_us"]))
    characteristics = event_characteristics(times, cases)
    arms = {}
    for name, config in configs.items():
        path = output / f"{name}.taers"
        metrics = evaluate_stream(
            path, times, observations, model, cases, normal, config, start, end
        )
        if metrics["packets"] != expected_packets:
            raise ValueError("Arm omitted an active epoch")
        metrics.update(config=asdict(config), packet_stream_sha256=sha256(path))
        metrics["strata"] = summarize_strata(metrics, characteristics)
        arms[name] = metrics
    report = dict(
        protocol_lock_sha256=sha256(lock_path),
        protocol=lock,
        model=model.to_dict(),
        python=platform.python_version(),
        numpy=np.__version__,
        source_observations=len(times),
        active_epochs=expected_packets,
        arms=arms,
        event_characteristics=characteristics,
        full_archive=full_archive_reference(
            times,
            observations,
            model,
            cases,
            normal,
            next(iter(configs.values())),
            start,
            end,
        ),
        interpretation="All fixed arms reported; caps are not equal expenditure. Seed variation does not imply confidence on new events.",
    )
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--bundle", type=Path, required=True)
    freezing.add_argument(
        "--settings", type=Path, default=Path("protocols/cross-mission-v1.json")
    )
    freezing.add_argument("--lock", type=Path, required=True)
    running = commands.add_parser("run")
    running.add_argument("--bundle", type=Path, required=True)
    running.add_argument("--lock", type=Path, required=True)
    running.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.bundle, args.settings, args.lock)
    else:
        run_study(args.bundle, args.lock, args.output)


if __name__ == "__main__":
    main()
