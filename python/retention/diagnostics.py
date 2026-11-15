"""Descriptive event strata fixed before the independent-mission experiment."""

import numpy as np


def event_characteristics(timestamps, cases):
    rows = {}
    for case in cases:
        duration = (
            max(row["end_us"] for row in case.annotations) - case.start_us
        ) / 1e6
        # Include pre-event context when detecting gaps around an event.
        indices = np.union1d(case.context, case.indices)
        maximum_gap = (
            int(np.diff(timestamps[indices]).max()) if len(indices) > 1 else None
        )
        rows[case.event_id] = dict(
            duration_seconds=duration,
            duration_group=(
                "up_to_60s"
                if duration <= 60
                else "60_to_600s" if duration <= 600 else "over_600s"
            ),
            maximum_observation_gap_us=maximum_gap,
            gap_group=(
                "insufficient_observations"
                if maximum_gap is None
                else "over_150s" if maximum_gap > 150000000 else "up_to_150s"
            ),
            source_samples=len(case.indices),
            boundary_censored=case.censored,
        )
    return rows


def summarize_strata(metrics, characteristics):
    """Use source-eligible events only; no inference from these small strata."""
    groups = {}
    for field in ("duration_group", "gap_group"):
        for label in sorted({row[field] for row in characteristics.values()}):
            selected = [
                row
                for row in metrics["events"]
                if row["source_eligible"]
                and characteristics[row["event_id"]][field] == label
            ]
            contexts = [
                row["context_coverage"]
                for row in selected
                if row["context_coverage"] is not None
            ]
            groups[f"{field}:{label}"] = dict(
                source_eligible_events=len(selected),
                pca_events=(
                    sum(row["receivers"]["pca"]["evidence"] for row in selected)
                    if metrics["receivers"]["pca"]["supported"]
                    else None
                ),
                raw_events=sum(row["retained_samples"] > 0 for row in selected),
                mean_pre_context_coverage=(
                    float(np.mean(contexts)) if contexts else None
                ),
            )
    return groups
