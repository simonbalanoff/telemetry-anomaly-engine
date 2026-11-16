"""Report the declared independent temporal contrast without selecting winners."""

import argparse
import json
from pathlib import Path

from dataset import atomic_text, sha256


def compare(benchmark, temporal, budget=1024):
    names = (f"{budget}-disabled-adaptive", f"{budget}-disabled-burst")
    first, second = [temporal["arms"][name] for name in names]

    def eligible(arm):
        return {row["event_id"]: row for row in arm["events"] if row["source_eligible"]}

    singleton, paired = eligible(first), eligible(second)
    for arm, selected in ((first, singleton), (second, paired)):
        if (
            len(selected) != arm["source_eligible_events"]
            or sum(row["retained_evidence"] for row in selected.values())
            != arm["retained_events"]
        ):
            raise ValueError("Primary report counts differ from eligible event rows")

    if singleton.keys() != paired.keys():
        raise ValueError("Primary arms use different source-eligible events")
    counts = dict(both=0, pair_only=0, singleton_only=0, neither=0)
    rows = []
    for event_id in sorted(singleton):
        left, right = singleton[event_id], paired[event_id]
        if left["full_archive_evidence"] != right["full_archive_evidence"]:
            raise ValueError("Full-archive recoverability differs between arms")
        a, b = left["retained_evidence"], right["retained_evidence"]
        key = (
            "both"
            if a and b
            else "singleton_only" if a else "pair_only" if b else "neither"
        )
        counts[key] += 1
        rows.append(
            dict(
                event_id=event_id,
                full_archive_evidence=left["full_archive_evidence"],
                singleton_evidence=a,
                pair_evidence=b,
            )
        )
    available = sum(row["full_archive_evidence"] for row in rows)
    return dict(
        primary_contrast="disabled-trigger pair versus singleton background; AR(1), 1024-byte cap",
        source_eligible_events=len(rows),
        full_archive_recoverable_events=available,
        informative=bool(rows and available),
        paired_counts=counts,
        singleton_events=first["retained_events"],
        pair_events=second["retained_events"],
        actual_encoded_bytes={
            name: benchmark["arms"][name]["serialized_bytes"] for name in names
        },
        events=rows,
        interpretation="Shared cap, not equal expenditure; descriptive paired counts, no independence or significance claim. Empty eligibility/recoverability is uninformative, not success.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--temporal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Preserve completed analyses; use a new output file")
    benchmark = json.loads(args.benchmark.read_text())
    temporal = json.loads(args.temporal.read_text())
    from run_retention_bundle_benchmark import verify_completed_study

    verify_completed_study(benchmark)
    if temporal["benchmark_sha256"] != sha256(args.benchmark):
        raise ValueError("Temporal report belongs to a different benchmark")
    result = compare(benchmark, temporal)
    result.update(
        benchmark_sha256=sha256(args.benchmark),
        temporal_sha256=sha256(args.temporal),
        analysis_sha256=sha256(Path(__file__)),
    )
    atomic_text(args.output, json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Wrote declared primary contrast: {args.output}")


if __name__ == "__main__":
    main()
