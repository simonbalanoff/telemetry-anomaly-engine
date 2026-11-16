"""Apply the declared Mission2 split without clipping original event intervals.

Reads annotations solely to validate and partition the fixed six-channel source.
It does not fit a model, calculate detection outcomes, or choose channels/splits.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from dataset import atomic_text, sha256
from retention.mission import open_bundle
from retention.partitioned_events import (
    POLICY,
    CATEGORIES,
    partition_rows,
    read_partition_events,
)
from run_retention_transfer import validate_settings

CHANNELS = [f"channel_{number}" for number in range(86, 92)]
TRAIN_END = 1001894400000000
EVAL_END = 1057017600000000


def timestamp_us(text):
    value = pd.Timestamp(text)
    if pd.isna(value) or value.tzinfo is None or value.value % 1000:
        raise ValueError("Source timestamps must be timezone-aware exact microseconds")
    return int(value.value // 1000)


def selected_annotations(source):
    categories = {}
    with (source / "anomaly_types.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"ID", "Category"} <= set(reader.fieldnames or []):
            raise ValueError("Unexpected anomaly-type schema")
        for row in reader:
            event_id, category = row["ID"], row["Category"]
            if event_id in categories and categories[event_id] != category:
                raise ValueError("Event ID has inconsistent source categories")
            categories[event_id] = category
    rows, seen = [], set()
    with (source / "labels.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"ID", "Channel", "StartTime", "EndTime"} <= set(
            reader.fieldnames or []
        ):
            raise ValueError("Unexpected source annotation schema")
        for source_row in reader:
            if source_row["Channel"] not in CHANNELS:
                continue
            category = categories.get(source_row["ID"])
            if category not in CATEGORIES:
                raise ValueError("Unknown category on a selected channel")
            row = dict(
                event_id=source_row["ID"],
                source_channel=source_row["Channel"],
                channel=41 + CHANNELS.index(source_row["Channel"]),
                category=category,
                start_us=timestamp_us(source_row["StartTime"]),
                end_us=timestamp_us(source_row["EndTime"]),
            )
            key = (
                row["event_id"],
                row["channel"],
                row["category"],
                row["start_us"],
                row["end_us"],
            )
            if key in seen:
                raise ValueError("Duplicate selected source annotation")
            seen.add(key)
            rows.append(row)
    return rows


def settings_digest(settings):
    return hashlib.sha256(
        json.dumps(
            settings, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def prepare(source, native, study_protocol, settings_path, output):
    if output.resolve() in {
        p.resolve() for p in (source, native, study_protocol.parent)
    }:
        raise ValueError("Output must be separate from inputs")
    settings = json.loads(settings_path.read_text())
    validate_settings(settings)
    if settings != json.loads(
        (
            Path(__file__).resolve().parents[1] / "protocols/cross-mission-v1.json"
        ).read_text()
    ):
        raise ValueError("Mission2 must use the declared unchanged retention settings")
    provenance = json.loads((native / "manifest.json").read_text())
    if (
        provenance.get("format") != "TAE-NATIVE-EXPORT"
        or provenance.get("mission") != "ESA-Mission2"
        or provenance.get("channels") != CHANNELS
        or not provenance.get("lossless_binary32")
        or provenance.get("training_end_us") != TRAIN_END
        or (provenance["last_timestamp_us"] // settings["epoch_us"] + 1)
        * settings["epoch_us"]
        != EVAL_END
    ):
        raise ValueError(
            "Native export differs from the declared Mission2 source/split"
        )
    for name, digest in provenance["files"].items():
        if (
            name not in ("timestamps.npy", "values.npy")
            or sha256(native / name) != digest
        ):
            raise ValueError("Native array hash mismatch")
    for name in CHANNELS:
        if (
            sha256(source / "channels" / f"{name}.zip")
            != provenance["source_archive_sha256"][name]
        ):
            raise ValueError("Original source channel differs from audited export")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Preserve prepared bundles; use an empty output directory")
    # Fix all choices and record their digest before opening source annotations.
    binding = dict(
        study_protocol_sha256=sha256(study_protocol),
        retention_settings_digest=settings_digest(settings),
        native_manifest_sha256=sha256(native / "manifest.json"),
        converter_sha256=sha256(Path(__file__)),
    )
    atomic_text(output / "preparation.json", json.dumps(binding, indent=2) + "\n")
    rows = selected_annotations(source)
    splits = {
        "training_events.json": (0, TRAIN_END),
        "evaluation_events.json": (TRAIN_END, EVAL_END),
    }
    for name, (start, end) in splits.items():
        annotations = partition_rows(rows, start, end)
        atomic_text(
            output / name, json.dumps(annotations, indent=2, allow_nan=False) + "\n"
        )
        read_partition_events(output / name, start, end)
    for name in ("timestamps.npy", "values.npy"):
        shutil.copyfile(native / name, output / name)
        if sha256(output / name) != provenance["files"][name]:
            raise ValueError("Array copy did not preserve native bytes")
    manifest = dict(
        format="TAE-MISSION",
        version=1,
        mission="ESA-Mission2",
        channels=CHANNELS,
        observation_semantics="synchronized-native-no-fill",
        annotation_policy=POLICY,
        training_end_us=TRAIN_END,
        evaluation_start_us=TRAIN_END,
        evaluation_end_us=EVAL_END,
        **binding,
        source_annotation_sha256={
            name: sha256(source / name) for name in ("labels.csv", "anomaly_types.csv")
        },
        files={
            name: sha256(output / name)
            for name in (*splits, "timestamps.npy", "values.npy")
        },
        interpretation="Original intervals and IDs preserved; group-level censorship excludes crossing events from source-eligible recall, never from training exclusion masks",
    )
    atomic_text(
        output / "manifest.json", json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    )
    open_bundle(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/ESA-Mission2"))
    parser.add_argument("--native", type=Path, default=Path("data/native-mission2"))
    parser.add_argument(
        "--study-protocol", type=Path, default=Path("protocols/mission2-study-v1.md")
    )
    parser.add_argument(
        "--settings", type=Path, default=Path("protocols/cross-mission-v1.json")
    )
    parser.add_argument("--output", type=Path, default=Path("data/mission2-bundle-v1"))
    args = parser.parse_args()
    prepare(args.source, args.native, args.study_protocol, args.settings, args.output)
    print(
        f"Prepared verified Mission2 bundle: {args.output}; no model fitted or outcomes evaluated"
    )


if __name__ == "__main__":
    main()
