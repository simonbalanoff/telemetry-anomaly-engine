"""Export audited synchronized native arrays without reading event labels.

This creates source arrays, not a complete labeled benchmark bundle. Every value
must be exactly representable by the current binary32 codec; no interpolation,
intersection, timestamp sorting, or silent precision loss is permitted.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from audit_mission_channels import load_trusted_channel
from dataset import atomic_text, sha256

CHUNK = 262144


def export(source, audit_path, output):
    report = json.loads(audit_path.read_text())
    if not report.get("ready_for_native_adapter"):
        raise ValueError("Source audit did not establish native compatibility")
    if report["metadata_sha256"] != sha256(source / "channels.csv"):
        raise ValueError("Channel metadata differs from the audit")
    if report["adapter_sha256"] != sha256(
        Path(__file__).with_name("audit_mission_channels.py")
    ):
        raise ValueError("Audit implementation changed; create an explicit new audit")
    if output.resolve() in (source.resolve(), audit_path.parent.resolve()):
        raise ValueError("Output must be separate from source and audit directories")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Preserve completed exports; use an empty output directory")
    names = report["channels"]
    if len(names) != 6 or len(set(names)) != 6:
        raise ValueError("Expected six distinct audited channels")
    reference = measurements = None
    source_hashes = {}
    for column, name in enumerate(names):
        path = source / "channels" / f"{name}.zip"
        digest = sha256(path)
        if digest != report["channel_audit"][name]["source_archive_sha256"]:
            raise ValueError(f"Source changed after audit: {name}")
        source_hashes[name] = digest
        series = load_trusted_channel(path, name)
        times = series.index.as_unit("ns").asi8
        if (
            not len(times)
            or np.any(times < 0)
            or np.any(times % 1000)
            or np.any(np.diff(times) <= 0)
        ):
            raise ValueError(
                "Native timestamps must be strictly increasing nonnegative microseconds"
            )
        if reference is None:
            reference = times.copy()
            np.save(output / "timestamps.npy", (times // 1000).astype("<i8"))
            measurements = np.lib.format.open_memmap(
                output / "values.npy", mode="w+", dtype="<f4", shape=(len(times), 6)
            )
        elif not np.array_equal(times, reference):
            raise ValueError(f"Native timestamps do not match: {name}")
        for first in range(0, len(times), CHUNK):
            values = series.iloc[first : first + CHUNK].to_numpy()
            if not np.issubdtype(values.dtype, np.number) or np.issubdtype(
                values.dtype, np.complexfloating
            ):
                raise ValueError("Native measurements must be real numeric values")
            with np.errstate(over="ignore", invalid="ignore"):
                converted = values.astype("<f4")
                roundtrip = converted.astype(values.dtype)
            if not np.isfinite(converted).all() or not np.array_equal(
                values, roundtrip
            ):
                raise ValueError(
                    "Native values must be finite and losslessly representable in binary32"
                )
            measurements[first : first + len(converted), column] = converted
        print(f"Exported {name}: {len(times):,} original observations", flush=True)
    measurements.flush()
    manifest = dict(
        format="TAE-NATIVE-EXPORT",
        version=1,
        mission=source.name,
        channels=names,
        observations=len(reference),
        audit_sha256=sha256(audit_path),
        exporter_sha256=sha256(Path(__file__)),
        source_archive_sha256=source_hashes,
        observation_semantics="synchronized-native-no-fill",
        lossless_binary32=True,
        training_end_us=report["training_end_us"],
        first_timestamp_us=int(reference[0] // 1000),
        last_timestamp_us=int(reference[-1] // 1000),
        files={
            name: sha256(output / name) for name in ("timestamps.npy", "values.npy")
        },
        exposure="Full native timestamp and numeric integrity validation only; no event labels or evaluation outcomes read",
        status="Unlabeled native export; split/annotation protocol and complete mission bundle still required",
    )
    atomic_text(output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = export(args.source, args.audit, args.output)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
