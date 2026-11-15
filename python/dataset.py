"""Versioned dataset metadata, integrity checks and channel-preserving labels."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile

import pandas as pd

from exploration.esa import read_labels, read_types
from write_binary import (
    Header,
    HEADER_FORMAT,
    HEADER_SIZE,
    FRAME_SIZE,
    PERIOD_US,
    encode_header,
)

COLUMNS = ["event_id", "channel", "category", "start_utc", "end_utc"]
CATEGORIES = {"Anomaly", "Rare Event", "Communication Gap"}
POLICY = dict(
    format="TAE-DATASET",
    version=1,
    dataset="ESA-ADB/Mission1",
    channels=list(range(41, 47)),
    grid_period_ms=30000,
    collision_policy="last",
    max_forward_fill_cells=5,
    time_unit="unix_microseconds_utc",
)


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_header(path):
    with open(path, "rb") as f:
        raw = f.read(HEADER_SIZE)
    if len(raw) != HEADER_SIZE:
        raise ValueError("Truncated header")
    fields = struct.unpack(HEADER_FORMAT, raw)
    header = Header(*fields[5:9])
    if encode_header(header) != raw:
        raise ValueError("Invalid binary header")
    if Path(path).stat().st_size != HEADER_SIZE + FRAME_SIZE * header.frame_count:
        raise ValueError("Incorrect binary length")
    return header


def timestamp_us(text):
    if not isinstance(text, str) or not text.endswith("Z"):
        raise ValueError("Expected UTC timestamp ending in Z")
    ts = pd.Timestamp(text)
    if pd.isna(ts) or ts.value % 1000:
        raise ValueError("Invalid microsecond timestamp")
    if ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != text:
        raise ValueError("Expected canonical microsecond UTC timestamp")
    return ts.value // 1000


def load_events(path, header):
    result, seen, categories = [], set(), {}
    end = header.start_us + header.frame_count * PERIOD_US
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError("Invalid events columns")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed event row")
            event_id = row["event_id"]
            channel = int(row["channel"])
            category = row["category"]
            start, stop = timestamp_us(row["start_utc"]), timestamp_us(row["end_utc"])
            key = (event_id, channel, category, start, stop)
            if key in seen:
                raise ValueError("Duplicate event-channel interval")
            seen.add(key)
            if (
                not event_id.strip()
                or channel not in range(41, 47)
                or category not in CATEGORIES
                or not header.start_us <= start <= stop <= end
                or start == end
            ):
                raise ValueError("Invalid event metadata or range")
            if categories.setdefault(event_id, category) != category:
                raise ValueError("Inconsistent event category")
            result.append(dict(row, channel=channel, start_us=start, end_us=stop))
    return result


def cell_interval(event, header):
    """Half-open cell-index interval; point events belong to their containing cell."""
    first = (event["start_us"] - header.start_us) // PERIOD_US
    stop = (
        (event["end_us"] - header.start_us + PERIOD_US - 1) // PERIOD_US
        if event["end_us"] > event["start_us"]
        else first + 1
    )
    return first, stop


def export_metadata(root, directory):
    directory = Path(directory)
    header = read_header(directory / "telemetry.bin")
    labels, types = read_labels(root), read_types(root)
    labels = labels[labels.Channel.isin([f"channel_{c}" for c in range(41, 47)])]
    merged = labels.merge(
        types[["ID", "Category"]], on="ID", how="left", validate="many_to_one"
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for row in merged.itertuples():
        for timestamp in (row.StartTime, row.EndTime):
            if pd.isna(timestamp) or timestamp.value % 1000:
                raise ValueError(
                    "Source labels must have microsecond-representable timestamps"
                )
        writer.writerow(
            [
                row.ID,
                int(row.Channel.split("_")[1]),
                row.Category,
                row.StartTime.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                row.EndTime.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ]
        )
    # Validate before replacing any metadata.
    fd, name = tempfile.mkstemp(dir=directory)
    os.close(fd)
    try:
        Path(name).write_text(output.getvalue())
        load_events(name, header)
    finally:
        os.unlink(name)
    atomic_text(directory / "events.csv", output.getvalue())
    manifest = dict(
        POLICY,
        files={
            key: dict(path=name, sha256=sha256(directory / name))
            for key, name in [("telemetry", "telemetry.bin"), ("events", "events.csv")]
        },
    )
    atomic_text(directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return verify_dataset(directory)


def verify_dataset(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    for key, value in POLICY.items():
        if type(manifest.get(key)) is not type(value) or manifest[key] != value:
            raise ValueError(f"Manifest policy mismatch: {key}")
    for key, name in [("telemetry", "telemetry.bin"), ("events", "events.csv")]:
        entry = manifest["files"][key]
        digest = entry["sha256"]
        if (
            entry["path"] != name
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid manifest path or hash")
        if sha256(directory / name) != digest:
            raise ValueError(f"SHA-256 mismatch: {name}")
    header = read_header(directory / "telemetry.bin")
    if (
        header.validation_start_us != 1199145600000000
        or header.test_start_us != 1293840000000000
    ):
        raise ValueError("Unexpected production split boundaries")
    return header, load_events(directory / "events.csv", header)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        help="Export annotations and manifest for existing binary",
    )
    args = parser.parse_args()
    header, events = (
        export_metadata(args.source, args.directory)
        if args.source
        else verify_dataset(args.directory)
    )
    print(
        f"Integrity verified: {header.frame_count} frames, {len(events)} event-channel intervals"
    )


if __name__ == "__main__":
    main()
