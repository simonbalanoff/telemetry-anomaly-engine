"""Prepare a verified mission bundle from native NumPy arrays and split labels.

This adapter preserves synchronized source arrays exactly. It never interpolates,
resamples, or chooses channels using evaluation outcomes. Source provenance and
channel/split rationale must be supplied by the dataset owner.
"""

import argparse
import json
from pathlib import Path
import shutil

from dataset import atomic_text, sha256
from retention.mission import BUNDLE_FILES, open_bundle, read_events


def prepare(
    timestamps,
    values,
    training_events,
    evaluation_events,
    output,
    *,
    mission,
    channels,
    training_end_us,
    evaluation_start_us,
    evaluation_end_us,
    rationale,
):
    inputs = dict(
        zip(BUNDLE_FILES, (timestamps, values, training_events, evaluation_events))
    )
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError(
            "Document source identity, channel selection, and split rationale"
        )
    if any(
        output.resolve() == path.resolve() or output.resolve() == path.parent.resolve()
        for path in inputs.values()
    ):
        raise ValueError("Bundle output must be separate from source directories")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty bundle directory")
    for name, path in inputs.items():
        shutil.copyfile(path, output / name)
    manifest = dict(
        format="TAE-MISSION",
        version=1,
        mission=mission,
        channels=list(channels),
        observation_semantics="synchronized-native-no-fill",
        training_end_us=training_end_us,
        evaluation_start_us=evaluation_start_us,
        evaluation_end_us=evaluation_end_us,
        source_provenance=dict(
            rationale=rationale,
            adapter_sha256=sha256(Path(__file__)),
            input_sha256={name: sha256(path) for name, path in inputs.items()},
        ),
        files={name: sha256(output / name) for name in BUNDLE_FILES},
    )
    atomic_text(
        output / "manifest.json", json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    )
    open_bundle(output)
    read_events(output / "training_events.json", 0, training_end_us)
    read_events(
        output / "evaluation_events.json", evaluation_start_us, evaluation_end_us
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "timestamps",
        "values",
        "training-events",
        "evaluation-events",
        "output",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--mission", required=True)
    parser.add_argument("--channels", nargs=6, required=True)
    parser.add_argument("--training-end-us", type=int, required=True)
    parser.add_argument("--evaluation-start-us", type=int, required=True)
    parser.add_argument("--evaluation-end-us", type=int, required=True)
    parser.add_argument("--rationale", required=True)
    args = parser.parse_args()
    prepare(
        args.timestamps,
        args.values,
        args.training_events,
        args.evaluation_events,
        args.output,
        mission=args.mission,
        channels=args.channels,
        training_end_us=args.training_end_us,
        evaluation_start_us=args.evaluation_start_us,
        evaluation_end_us=args.evaluation_end_us,
        rationale=args.rationale,
    )
    print(f"Verified mission bundle: {args.output}")


if __name__ == "__main__":
    main()
