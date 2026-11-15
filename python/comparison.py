"""Validation-only selection, workload metrics, and inspectable alarm episodes."""

import numpy as np

from dataset import cell_interval
from export_features import CHUNK_CELLS
from evaluate import alarm_intervals, average_precision, event_metrics, partition_events
from write_binary import PERIOD_US

# Resolve the extreme tail finely enough for budgets of a few episodes per year.
QUANTILES = [
    0.9,
    0.95,
    0.99,
    0.995,
    0.999,
    0.9995,
    0.9999,
    0.99995,
    0.99999,
    0.999995,
    0.999999,
    1.0,
]


def held_alarm_intervals(scores, eligible, threshold, bridgeable=None, max_gap=0):
    """Hold across short unobserved-but-usable gaps; never invent scored cells."""
    episodes = alarm_intervals(scores, eligible, threshold)
    if bridgeable is None or max_gap == 0:
        return episodes
    merged = []
    for first, stop in episodes:
        if merged:
            previous_first, previous_stop = merged[-1]
            gap = first - previous_stop
            if (
                0 < gap <= max_gap
                and np.all(bridgeable[previous_stop:first])
                and not np.any(eligible[previous_stop:first])
            ):
                merged[-1] = (previous_first, stop)
                continue
        merged.append((first, stop))
    return merged


def grouped_metrics(
    scores,
    eligible,
    events,
    header,
    threshold,
    anomaly_mask,
    bridgeable=None,
    max_gap=0,
):
    episodes = held_alarm_intervals(scores, eligible, threshold, bridgeable, max_gap)
    metrics = event_metrics(
        scores, eligible, events, header, threshold, anomaly_mask, episodes=episodes
    )
    scored_alarm_cells = sum(
        int(np.count_nonzero(eligible[first:stop])) for first, stop in episodes
    )
    metrics["alarm_scored_cells"] = scored_alarm_cells
    metrics["alarm_held_unscored_cells"] = metrics["alarm_cells"] - scored_alarm_cells
    return metrics


def threshold_candidates(scores, eligible, anomaly_mask):
    normal = scores[eligible & (anomaly_mask == 0)]
    if not len(normal):
        raise ValueError("No eligible validation normal cells")
    validation_scores = scores[eligible]
    maximum = float(np.max(validation_scores))
    # Episode fragmentation is not monotone in threshold. Include the labelled
    # validation tail too, rather than jumping from max-normal straight to silence.
    return np.unique(
        np.r_[
            np.quantile(normal, QUANTILES),
            np.quantile(validation_scores, QUANTILES),
            np.nextafter(maximum, np.inf),
        ]
    )


def selection_rank(metrics):
    """Within budget: maximize recall, then reduce false alarms and alarm burden."""
    return (
        metrics["event_recall"],
        -metrics["false_alarms"],
        -metrics["total_alarm_seconds"],
        metrics["threshold"],
    )


def select_with_budget(
    scores, eligible, events, header, anomaly_mask, budget, bridgeable=None, max_gap=0
):
    if not np.isfinite(budget) or budget < 0:
        raise ValueError("False-alarm budget must be finite and nonnegative")
    trials = []
    for threshold in threshold_candidates(scores, eligible, anomaly_mask):
        metrics = grouped_metrics(
            scores,
            eligible,
            events,
            header,
            float(threshold),
            anomaly_mask,
            bridgeable,
            max_gap,
        )
        metrics["threshold"] = float(threshold)
        rate = metrics["false_alarms_per_eligible_day"]
        metrics["within_budget"] = bool(rate is not None and rate <= budget)
        trials.append(metrics)
    feasible = [trial for trial in trials if trial["within_budget"]]
    if not feasible:
        raise ValueError("No feasible validation threshold")
    return max(feasible, key=selection_rank), trials


def validation_selection(
    score_columns,
    eligible,
    events,
    header,
    anomaly_mask,
    budget,
    bridgeable=None,
    max_gap=0,
):
    """All inputs are already restricted to validation by the caller's mask."""
    first = (header.validation_start_us - header.start_us) // PERIOD_US
    stop = (header.test_start_us - header.start_us) // PERIOD_US
    if np.any(eligible[:first]) or np.any(eligible[stop:]):
        raise ValueError("Threshold selection requires validation-only eligibility")
    events = partition_events(events, header, first, stop)
    selected, trials = {}, {}
    for name, scores in score_columns.items():
        selected[name], trials[name] = select_with_budget(
            scores, eligible, events, header, anomaly_mask, budget, bridgeable, max_gap
        )
    pca_names = [name for name in selected if name.startswith("pca_")]
    # Resolve exact ties in favour of fewer retained components.
    best_pca = max(
        pca_names,
        key=lambda name: (
            selection_rank(selected[name])[:-1],
            -int(name.split("_")[1]),
        ),
    )
    return dict(detectors=selected, best_pca=best_pca, validation_trials=trials)


def summarize_detector(
    scores,
    eligible,
    events,
    header,
    anomaly_mask,
    threshold,
    bridgeable=None,
    max_gap=0,
):
    metrics = grouped_metrics(
        scores, eligible, events, header, threshold, anomaly_mask, bridgeable, max_gap
    )
    metrics["threshold"] = threshold
    metrics["cell_average_precision"] = average_precision(
        scores[eligible], anomaly_mask[eligible] != 0
    )
    scored_cells = int(np.count_nonzero(eligible))
    metrics["scored_cells"] = scored_cells
    metrics["alarm_fraction"] = (
        metrics["alarm_scored_cells"] / scored_cells if scored_cells else None
    )
    # An always-on control exposes how episode matching can conceal alarm duration.
    metrics["controls"] = {
        "always_off": grouped_metrics(
            scores, eligible, events, header, np.inf, anomaly_mask, bridgeable, max_gap
        ),
        "always_on": grouped_metrics(
            scores, eligible, events, header, -np.inf, anomaly_mask, bridgeable, max_gap
        ),
    }
    return metrics


def alarm_catalog(
    scores, eligible, events, header, threshold, bridgeable=None, max_gap=0
):
    """Emit an inspectable record for each maximal eligible alarm episode."""
    catalog = []
    for first, stop in held_alarm_intervals(
        scores, eligible, threshold, bridgeable, max_gap
    ):
        scored_values = np.where(eligible[first:stop], scores[first:stop], -np.inf)
        peak = first + int(np.argmax(scored_values))
        overlap = set()
        for event in events:
            if event["category"] == "Anomaly":
                event_first, event_stop = cell_interval(event, header)
                if first < event_stop and event_first < stop:
                    overlap.add(event["event_id"])
        catalog.append(
            dict(
                first_cell=first,
                stop_cell=stop,
                peak_cell=peak,
                first_available_us=header.start_us + (first + 1) * PERIOD_US,
                last_available_us=header.start_us + stop * PERIOD_US,
                duration_seconds=(stop - first) * 30,
                peak_score=float(scores[peak]),
                threshold=threshold,
                overlapping_event_ids=sorted(overlap),
            )
        )
    return catalog


def channel_evidence(name, frame, feature, runtime):
    """Score contributions describe model evidence, not a root-cause diagnosis."""
    mean = np.array([entry["mean"] for entry in runtime["normalization"]])
    sigma = np.maximum(
        1e-12, np.sqrt([entry["variance"] for entry in runtime["normalization"]])
    )
    normalized = (frame["values"].astype(float) - mean) / sigma
    if name.startswith("pca_"):
        count = int(name.split("_")[1])
        basis = np.asarray(runtime["pca_eigenvectors"])[:, :count]
        contributions = (normalized - basis @ (basis.T @ normalized)) ** 2 / 6
        description = "PCA reconstruction error contribution"
    elif name == "raw_excursion":
        contributions = np.maximum(
            np.abs((feature["minimum"] - mean) / sigma),
            np.abs((feature["maximum"] - mean) / sigma),
        )
        description = "Largest raw deviation from training mean in standard deviations"
    elif name == "within_cell_range":
        contributions = (feature["maximum"].astype(float) - feature["minimum"]) / sigma
        description = "Raw within-cell range in training standard deviations"
    else:
        contributions = np.abs(normalized)
        description = "Retained value deviation from training mean; not a rolling-score attribution"
    order = np.argsort(-contributions, kind="stable")
    return dict(
        description=description,
        raw_sample_count=int(feature["sample_count"]),
        frame_quality=dict(
            observed_mask=int(frame["observed"]),
            usable_mask=int(frame["usable"]),
            staleness=int(frame["staleness"]),
        ),
        channels=[
            dict(
                channel=int(channel + 41),
                contribution=float(contributions[channel]),
                retained_value=float(frame["values"][channel]),
                minimum=float(feature["minimum"][channel]),
                maximum=float(feature["maximum"][channel]),
            )
            for channel in order
        ],
    )


def score_raw_evidence(path, features, frames, runtime):
    """Matched extrema/keep-last controls share the same frozen normalizer."""
    mean = np.array([entry["mean"] for entry in runtime["normalization"]])
    sigma = np.maximum(
        1e-12, np.sqrt([entry["variance"] for entry in runtime["normalization"]])
    )
    output = np.lib.format.open_memmap(
        path, mode="w+", dtype="<f8", shape=(len(frames), 3)
    )
    for first in range(0, len(frames), CHUNK_CELLS):
        stop = min(first + CHUNK_CELLS, len(frames))
        block = features[first:stop]
        observed = block["sample_count"] > 0
        retained = (frames["values"][first:stop].astype(float) - mean) / sigma
        minimum = (block["minimum"].astype(float) - mean) / sigma
        maximum = (block["maximum"].astype(float) - mean) / sigma
        output[first:stop, 0] = np.max(np.abs(retained), axis=1)
        output[first:stop, 1] = np.max(
            np.maximum(np.abs(minimum), np.abs(maximum)), axis=1
        )
        output[first:stop, 2] = np.max(maximum - minimum, axis=1)
        output[first:stop][~observed] = np.nan
    output.flush()
    return output
