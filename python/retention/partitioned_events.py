"""Versioned annotation handling that preserves source intervals at split edges.

The original strict bundle reader remains unchanged. Bundles explicitly declaring
this policy retain original rows and event-level boundary flags. Source eligibility
is adjusted without changing the historical native evaluator's semantics.
"""

from dataclasses import replace
import json

from retention.mission import read_events
from retention.native_metrics import build_event_cases

POLICY = "original-intervals-event-censorship-v1"
CATEGORIES = ("Anomaly", "Rare Event", "Communication Gap")


def intersects(row, start, end):
    if row["start_us"] == row["end_us"]:
        return start <= row["start_us"] < end
    return row["start_us"] < end and row["end_us"] > start


def contained(row, start, end):
    return start <= row["start_us"] < end and row["end_us"] <= end


def validate_row(row):
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("event_id"), str)
        or not row["event_id"]
        or row.get("category") not in CATEGORIES
        or type(row.get("channel")) is not int
        or not 41 <= row["channel"] <= 46
        or type(row.get("start_us")) is not int
        or type(row.get("end_us")) is not int
        or not 0 <= row["start_us"] <= row["end_us"] < 2**63
    ):
        raise ValueError("Invalid original annotation")


def partition_rows(rows, start, end):
    """A disjoint row on another channel can still censor the whole event ID."""
    groups = {}
    for row in rows:
        validate_row(row)
        groups.setdefault(row["event_id"], []).append(row)
    partition = []
    for event_id in sorted(groups):
        group = groups[event_id]
        if len({row["category"] for row in group}) != 1:
            raise ValueError("Event ID has inconsistent categories")
        censored = not all(contained(row, start, end) for row in group)
        event_start = min(row["start_us"] for row in group)
        event_end = max(row["end_us"] for row in group)
        for row in group:
            if intersects(row, start, end):
                partition.append(
                    dict(
                        row,
                        boundary_censored=censored,
                        event_start_us=event_start,
                        event_end_us=event_end,
                    )
                )
    return sorted(
        partition,
        key=lambda row: (
            row["start_us"],
            row["event_id"],
            row["channel"],
            row["end_us"],
        ),
    )


def read_partition_events(path, start, end):
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("Annotations must be a list")
    for row in rows:
        validate_row(row)
        if (
            type(row.get("boundary_censored")) is not bool
            or type(row.get("event_start_us")) is not int
            or type(row.get("event_end_us")) is not int
            or not 0
            <= row["event_start_us"]
            <= row["start_us"]
            <= row["end_us"]
            <= row["event_end_us"]
            < 2**63
            or not intersects(row, start, end)
        ):
            raise ValueError("Invalid partition annotation or event span")
        span_contained = (
            start <= row["event_start_us"] < end and row["event_end_us"] <= end
        )
        if not row["boundary_censored"] and (
            not contained(row, start, end) or not span_contained
        ):
            raise ValueError("Crossing event must be boundary-censored")
    for event_id in {row["event_id"] for row in rows}:
        group = [row for row in rows if row["event_id"] == event_id]
        if (
            len(
                {
                    (
                        row["category"],
                        row["event_start_us"],
                        row["event_end_us"],
                        row["boundary_censored"],
                    )
                    for row in group
                }
            )
            != 1
        ):
            raise ValueError("Inconsistent event-level boundary metadata")
    return rows


def event_reader(manifest, legacy_reader=read_events):
    policy = manifest.get("annotation_policy")
    if policy is None:
        return legacy_reader
    if policy != POLICY:
        raise ValueError("Unsupported annotation boundary policy")
    return read_partition_events


def build_partition_cases(timestamps, rows, start, end, context):
    cases, eligible, normal = build_event_cases(timestamps, rows, start, end, context)
    cases = [
        replace(
            case,
            censored=case.censored
            or any(row.get("boundary_censored", False) for row in case.annotations),
        )
        for case in cases
    ]
    return cases, eligible, normal
