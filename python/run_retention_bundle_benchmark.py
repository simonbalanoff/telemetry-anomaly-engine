"""Freeze and run receiver-mismatch experiments on a verified independent mission.

All policies and receiver calibration rules are declared before capture. Hashes
make protocol changes visible; they do not establish that labels were never seen.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import hashlib
import json
import multiprocessing
from pathlib import Path
import platform
import subprocess

import numpy as np

from dataset import atomic_text, sha256
from retention.codec import Sample
from retention.burst import BurstRecorder
from retention.coverage import CoverageRecorder
from retention.mission import open_bundle, read_events
from retention.partitioned_events import event_reader
from retention.native_model import CHUNK, causal_capture_scores, fit_native_model
from retention.randomized import RandomizedRecorder
from retention.receiver_bank import CAPTURE_MODELS, NAMES, fit_bank
from retention.recorder import Recorder
from run_retention_benchmark import POLICIES, SCENARIOS, evaluate_budget
from run_retention_transfer import base_config, validate_settings

EXTERNAL_POLICIES = (*POLICIES, "burst")


def digest_settings(settings):
    return hashlib.sha256(
        json.dumps(
            settings, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def implementation_hashes():
    root = Path(__file__).parent
    paths = [
        *sorted((root / "retention").glob("*.py")),
        root / "run_retention_bundle_benchmark.py",
        root / "run_retention_sequence.py",
        root / "run_retention_benchmark.py",
        root / "run_retention_transfer.py",
        root / "run_retention_randomized.py",
        root / "run_retention_pilot.py",
        root / "dataset.py",
        root / "requirements-core.txt",
        root / "prepare_mission2_bundle.py",
        root / "summarize_independent_retention.py",
    ]
    return {str(path.relative_to(root)): sha256(path) for path in paths}


def bind_study_protocol(manifest, path):
    expected = manifest.get("study_protocol_sha256")
    if expected is None and path is None:
        return None
    if path is None or sha256(path) != expected:
        raise ValueError(
            "Provide the study protocol matching the bundle's declared digest"
        )
    root = Path(__file__).resolve().parents[1]
    relative = path.resolve().relative_to(root)
    return dict(path=relative.as_posix(), sha256=expected)


def verify_study_protocol(lock, manifest):
    study = lock.get("study_protocol")
    expected = manifest.get("study_protocol_sha256")
    if study is None:
        if expected is not None:
            raise ValueError("Study protocol is missing from lock")
        return
    root = Path(__file__).resolve().parents[1]
    path = (root / study["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or sha256(path) != study["sha256"]
        or study["sha256"] != expected
    ):
        raise ValueError("Study protocol differs from the frozen record")


def verify_committed_protocol(lock, lock_path, root=None):
    """A study-bound lock cannot be evaluated from an uncommitted working copy."""
    if lock.get("study_protocol") is None:
        return None
    root = Path(__file__).resolve().parents[1] if root is None else Path(root).resolve()
    paths = [
        Path(lock_path).resolve(),
        (root / lock["study_protocol"]["path"]).resolve(),
        *((root / "python" / name).resolve() for name in lock["scripts"]),
    ]
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError("Frozen protocol paths must remain inside the repository")
    relative = [path.relative_to(root).as_posix() for path in paths]
    try:
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", *relative],
            cwd=root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *relative],
            cwd=root,
            check=True,
            capture_output=True,
        )
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", relative[0]], cwd=root, text=True
        ).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(
            "Commit the frozen lock, study protocol, and implementation before evaluation"
        ) from error


def verify_completed_study(report, manifest=None):
    """Temporal assessment and primary analysis must use the same committed study."""
    lock = report.get("provenance", {})
    if lock.get("study_protocol") is None:
        return
    if lock["scripts"] != implementation_hashes():
        raise ValueError("Implementation changed after the frozen benchmark")
    if (lock["python"], lock["numpy"]) != (platform.python_version(), np.__version__):
        raise ValueError("Numerical environment changed after the benchmark")
    declared = manifest or {"study_protocol_sha256": lock["study_protocol"]["sha256"]}
    verify_study_protocol(lock, declared)
    root = Path(__file__).resolve().parents[1]
    path = (root / report["protocol_lock_path"]).resolve()
    if not path.is_relative_to(root) or sha256(path) != report["protocol_lock_sha256"]:
        raise ValueError("Protocol lock changed after the benchmark")
    if verify_committed_protocol(lock, path) != report["protocol_commit"]:
        raise ValueError("Protocol commit changed after the benchmark")


def freeze(bundle, settings_path, lock_path, study_protocol=None):
    if lock_path.exists():
        raise ValueError("Preserve existing locks; choose a new protocol path")
    settings = json.loads(settings_path.read_text())
    validate_settings(settings)
    if settings["threshold"] <= 0:
        raise ValueError("Mismatch controls require a positive capture threshold")
    if settings["pca_components"] != 3:
        raise ValueError("Receiver-mismatch protocol requires original PCA rank 3")
    _, _, manifest = open_bundle(bundle)
    event_reader(manifest)
    study = bind_study_protocol(manifest, study_protocol)
    if manifest.get(
        "retention_settings_digest", digest_settings(settings)
    ) != digest_settings(settings):
        raise ValueError("Retention settings differ from the prepared study bundle")
    if (
        manifest["mission"].strip().casefold()
        == settings["development_mission"].strip().casefold()
    ):
        raise ValueError("Independent evaluation requires a different mission")
    if any(
        manifest[key] % settings["epoch_us"]
        for key in ("evaluation_start_us", "evaluation_end_us")
    ):
        raise ValueError("Evaluation must cover complete reporting epochs")
    lock = dict(
        protocol="independent-receiver-mismatch-v1",
        settings=settings,
        study_protocol=study,
        settings_digest=digest_settings(settings),
        target_mission=manifest["mission"],
        bundle_manifest_sha256=sha256(bundle / "manifest.json"),
        scripts=implementation_hashes(),
        python=platform.python_version(),
        numpy=np.__version__,
        capture_models=list(CAPTURE_MODELS),
        receivers=list(NAMES),
        policies=list(EXTERNAL_POLICIES),
        temporal_receiver="training-only ridge AR(1), both original endpoints required",
        link_scenarios={name: asdict(link) for name, link in SCENARIOS.items()},
    )
    atomic_text(lock_path, json.dumps(lock, indent=2) + "\n")
    return lock


def capture_external(task):
    times = np.load(task["times"], mmap_mode="r", allow_pickle=False)
    values = np.load(task["values"], mmap_mode="r", allow_pickle=False)
    scores = np.load(task["capture_scores"], mmap_mode="r", allow_pickle=False)
    config = base_config(task["settings"], task["config"]["budget_bytes"])
    recorders = {}
    for column, mode in enumerate(CAPTURE_MODELS):
        for policy in EXTERNAL_POLICIES:
            if policy == "coverage":
                recorder = CoverageRecorder(config, task["mean"], task["sigma"])
            elif policy == "burst":
                recorder = BurstRecorder(config)
            else:
                recorder = Recorder(policy, config)
            recorders[f"{config.budget_bytes}-{mode}-{policy}"] = (recorder, column)
    recorders[f"{config.budget_bytes}-uniform"] = (Recorder("uniform", config), 0)
    for policy in ("reservoir", "randomized_uniform"):
        for seed in task["settings"]["seeds"]:
            recorders[f"{config.budget_bytes}-{policy}-seed{seed}"] = (
                RandomizedRecorder(policy, config, seed),
                0,
            )
    output = Path(task["output"])
    streams = {name: (output / f"{name}.taers").open("xb") for name in recorders}
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
    return {name: str((output / f"{name}.taers").resolve()) for name in recorders}


def run_study(bundle, lock_path, output, workers=4):
    if type(workers) is not int or workers < 1:
        raise ValueError("Worker count must be positive")
    lock = json.loads(lock_path.read_text())
    settings = lock["settings"]
    validate_settings(settings)
    if settings["threshold"] <= 0:
        raise ValueError("Mismatch controls require a positive capture threshold")
    if settings["pca_components"] != 3:
        raise ValueError("Receiver-mismatch protocol requires original PCA rank 3")
    if lock["protocol"] != "independent-receiver-mismatch-v1" or lock[
        "settings_digest"
    ] != digest_settings(settings):
        raise ValueError("Protocol settings differ from frozen digest")
    if lock["scripts"] != implementation_hashes():
        raise ValueError("Implementation differs from frozen protocol")
    if (lock["python"], lock["numpy"]) != (platform.python_version(), np.__version__):
        raise ValueError("Numerical environment differs from frozen protocol")
    if lock["bundle_manifest_sha256"] != sha256(bundle / "manifest.json"):
        raise ValueError("Input manifest differs from frozen protocol")
    times, values, manifest = open_bundle(bundle)
    reader = event_reader(manifest, read_events)
    verify_study_protocol(lock, manifest)
    protocol_commit = verify_committed_protocol(lock, lock_path)
    if manifest["mission"] != lock["target_mission"]:
        raise ValueError("Target mission differs from protocol")
    if output.resolve() == bundle.resolve():
        raise ValueError("Output must be separate from source bundle")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty benchmark output directory")
    atomic_text(output / "protocol.json", json.dumps(lock, indent=2) + "\n")
    training = reader(bundle / "training_events.json", 0, manifest["training_end_us"])
    original = fit_native_model(
        times,
        values,
        training,
        manifest["training_end_us"],
        output / "training_scores.npy",
        settings["receiver_quantile"],
        components=3,
    )
    bank = fit_bank(times, values, training, original, output)
    atomic_text(output / "receivers.json", json.dumps(bank.to_dict(), indent=2) + "\n")
    start, end = manifest["evaluation_start_us"], manifest["evaluation_end_us"]
    left, right = np.searchsorted(times, [start, end])
    times, values = times[left:right], values[left:right]
    np.save(output / "evaluation_times.npy", times)
    np.save(output / "evaluation_values.npy", values)
    positive = np.lib.format.open_memmap(
        output / "positive.npy", mode="w+", dtype=bool, shape=(len(times), len(NAMES))
    )
    captures = np.lib.format.open_memmap(
        output / "capture_scores.npy",
        mode="w+",
        dtype="<f8",
        shape=(len(times), len(CAPTURE_MODELS)),
    )
    captures[:, 0] = causal_capture_scores(times, values, original.sigma)
    for first in range(0, len(times), CHUNK):
        stop = min(first + CHUNK, len(times))
        scores = bank.scores(values[first:stop])
        positive[first:stop] = scores > bank.thresholds
        captures[first:stop, 1] = scores[:, 0]
        captures[first:stop, 2] = (
            scores[:, 3] / bank.thresholds[3] * settings["threshold"]
            if bank.thresholds[3] > 0
            else (scores[:, 3] > 0) * settings["threshold"]
        )
        captures[first:stop, 3] = 0
    positive.flush()
    captures.flush()
    tasks = [
        dict(
            times=str((output / "evaluation_times.npy").resolve()),
            values=str((output / "evaluation_values.npy").resolve()),
            capture_scores=str((output / "capture_scores.npy").resolve()),
            positive=str((output / "positive.npy").resolve()),
            output=str(output.resolve()),
            settings=settings,
            config=asdict(base_config(settings, budget)),
            mean=original.mean.tolist(),
            sigma=original.sigma.tolist(),
            start_us=start,
            end_us=end,
            context_us=settings["context_us"],
            active_epochs=len(np.unique(times // settings["epoch_us"])),
        )
        for budget in settings["budgets"]
    ]
    if workers == 1:
        streams = [capture_external(task) for task in tasks]
    else:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            streams = list(pool.map(capture_external, tasks))
    # Only after every capture completes do evaluation annotations enter a task.
    events = reader(bundle / "evaluation_events.json", start, end)
    payloads = [(task, events, stream) for task, stream in zip(tasks, streams)]
    if workers == 1:
        evaluated = [evaluate_budget(payload) for payload in payloads]
    else:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(tasks)),
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            evaluated = list(pool.map(evaluate_budget, payloads))
    report = dict(
        provenance=lock,
        protocol_commit=protocol_commit,
        protocol_lock_path=(
            lock_path.resolve()
            .relative_to(Path(__file__).resolve().parents[1])
            .as_posix()
            if protocol_commit
            else None
        ),
        protocol_lock_sha256=sha256(lock_path),
        receivers=bank.to_dict(),
        source_observations=len(times),
        arms={
            name: metrics for result in evaluated for name, metrics in result.items()
        },
        interpretation="Training-calibrated transfer of fixed retention settings; detector ranks are correlated; synthetic contacts do not establish mission downlink requirements",
    )
    atomic_text(
        output / "report.json", json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--study-protocol", type=Path)
    freezing.add_argument(
        "--settings", type=Path, default=Path("protocols/cross-mission-v1.json")
    )
    running = commands.add_parser("run")
    running.add_argument("--output", type=Path, required=True)
    running.add_argument("--workers", type=int, default=4)
    for command in (freezing, running):
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.bundle, args.settings, args.lock, args.study_protocol)
    else:
        run_study(args.bundle, args.lock, args.output, args.workers)


if __name__ == "__main__":
    main()
