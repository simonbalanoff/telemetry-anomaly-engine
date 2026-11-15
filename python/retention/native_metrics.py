"""Source-fixed denominators and independent receivers on decoded native packets."""

from dataclasses import dataclass

import numpy as np

from retention.codec import HEADER, SUMMARY_BYTES, RawRecord
from retention.native_model import RECEIVERS, annotation_mask, observation_interval
from retention.stream import read_packets


@dataclass(frozen=True)
class EventCase:
    event_id: str
    start_us: int
    annotations: tuple[dict, ...]
    indices: np.ndarray
    context: np.ndarray
    censored: bool


def build_event_cases(timestamps, events, start_us, end_us, context_us):
    eligible = ~annotation_mask(
        timestamps, [event for event in events if event["category"] != "Anomaly"]
    )
    groups = {}
    for event in events:
        if event["category"] != "Anomaly":
            continue
        intersects = (
            start_us <= event["start_us"] < end_us
            if event["start_us"] == event["end_us"]
            else event["start_us"] < end_us and event["end_us"] > start_us
        )
        if intersects:
            groups.setdefault(event["event_id"], []).append(event)
    cases = []
    for event_id, rows in sorted(groups.items()):
        ranges = []
        for row in rows:
            left, right = observation_interval(
                timestamps, row["start_us"], row["end_us"]
            )
            ranges.append(np.arange(left, right, dtype=np.int64))
        indices = np.unique(np.concatenate(ranges))
        indices = indices[eligible[indices]]
        onset = min(row["start_us"] for row in rows)
        left, right = observation_interval(timestamps, onset - context_us, onset)
        context = np.arange(left, right, dtype=np.int64)
        context = context[eligible[context]]
        censored = any(
            row["start_us"] < start_us or row["end_us"] > end_us for row in rows
        )
        cases.append(
            EventCase(event_id, onset, tuple(rows), indices, context, censored)
        )
    normal = ~annotation_mask(timestamps, events)
    return cases, eligible, normal


def summary_end(packet, record):
    capacity = (packet.budget_bytes - HEADER.size) // SUMMARY_BYTES
    slot = (record.start_us - packet.start_us) * capacity // packet.duration_us
    return (
        packet.start_us + ((slot + 1) * packet.duration_us + capacity - 1) // capacity
    )


def quantiles_or_none(values):
    return (
        {str(q): float(np.percentile(values, q)) for q in [50, 95, 99]}
        if values
        else None
    )


class NativeEvaluator:
    """Evaluation may use annotations; capture is finished before this object runs."""

    def __init__(
        self, timestamps, values, model, cases, normal, epoch_us, start_us, end_us
    ):
        self.timestamps, self.values, self.model = timestamps, values, model
        self.cases, self.normal = cases, normal
        self.epoch_us, self.start_us, self.end_us = epoch_us, start_us, end_us
        self.retained = np.zeros(len(timestamps), dtype=bool)
        self.positive = np.zeros((len(timestamps), len(RECEIVERS)), dtype=bool)
        self.coarse_events = set()
        self.packet_count = self.bytes = self.maximum_bytes = 0
        self.coarse_positive_buckets = self.coarse_normal_positive_buckets = 0
        self.has_summaries = False

    def consume(self, packet):
        encoded_bytes = len(packet.encode())
        self.bytes += encoded_bytes
        self.maximum_bytes = max(self.maximum_bytes, encoded_bytes)
        self.packet_count += 1
        raw = [record for record in packet.records if isinstance(record, RawRecord)]
        if raw:
            timestamps = np.array(
                [record.sample.timestamp_us for record in raw], dtype=np.int64
            )
            positions = np.searchsorted(self.timestamps, timestamps)
            if np.any(positions == len(self.timestamps)) or not np.array_equal(
                self.timestamps[positions], timestamps
            ):
                raise ValueError(
                    "Retained timestamps are not original native observations"
                )
            values = np.array([record.sample.values for record in raw], dtype="<f4")
            expected = np.ascontiguousarray(self.values[positions])
            if not np.array_equal(values.view("<u4"), expected.view("<u4")):
                raise ValueError(
                    "Retained measurements differ from original binary32 values"
                )
            self.retained[positions] = True
            self.positive[positions] = self.model.scores(values) > self.model.thresholds
        for record in packet.records:
            if isinstance(record, RawRecord):
                continue
            self.has_summaries = True
            end = summary_end(packet, record)
            left, right = np.searchsorted(self.timestamps, [record.start_us, end])
            source = self.values[left:right]
            if (
                len(source) != record.count
                or not len(source)
                or not np.array_equal(source.min(axis=0), record.minimum)
                or not np.array_equal(source.max(axis=0), record.maximum)
            ):
                raise ValueError("Summary does not match its original native bucket")
            low = (np.array(record.minimum) - self.model.mean) / self.model.sigma
            high = (np.array(record.maximum) - self.model.mean) / self.model.sigma
            bounds = np.maximum(np.abs(low), np.abs(high))
            if np.max(bounds) > self.model.thresholds[0]:
                self.coarse_positive_buckets += 1
                if np.all(self.normal[left:right]):
                    self.coarse_normal_positive_buckets += 1
            for case in self.cases:
                for annotation in case.annotations:
                    stop = (
                        annotation["end_us"]
                        if annotation["end_us"] > annotation["start_us"]
                        else annotation["start_us"] + 1
                    )
                    if (
                        record.start_us < stop
                        and annotation["start_us"] < end
                        and bounds[annotation["channel"] - 41]
                        > self.model.thresholds[0]
                    ):
                        self.coarse_events.add(case.event_id)

    def report(self, budget_bytes):
        rows = []
        for case in self.cases:
            kept = case.indices[self.retained[case.indices]]
            row = dict(
                event_id=case.event_id,
                source_samples=len(case.indices),
                retained_samples=len(kept),
                source_eligible=bool(len(case.indices)) and not case.censored,
                boundary_censored=case.censored,
                sample_coverage=(
                    len(kept) / len(case.indices) if len(case.indices) else None
                ),
                context_samples=len(case.context),
                retained_context_samples=int(self.retained[case.context].sum()),
                context_coverage=(
                    float(self.retained[case.context].mean())
                    if len(case.context)
                    else None
                ),
                raw_onset_error_seconds=(
                    float((self.timestamps[kept[0]] - case.start_us) / 1e6)
                    if len(kept)
                    else None
                ),
                receivers={},
                coarse_summary_level_evidence=case.event_id in self.coarse_events,
                annotations=list(case.annotations),
            )
            for column, name in enumerate(RECEIVERS):
                hits = case.indices[self.positive[case.indices, column]]
                row["receivers"][name] = dict(
                    evidence=bool(len(hits)),
                    delivery_delay_seconds=(
                        float(
                            (
                                (int(self.timestamps[hits[0]]) // self.epoch_us + 1)
                                * self.epoch_us
                                - case.start_us
                            )
                            / 1e6
                        )
                        if len(hits)
                        else None
                    ),
                )
            rows.append(row)
        eligible = [row for row in rows if row["source_eligible"]]
        receiver_metrics = {}
        for column, name in enumerate(RECEIVERS):
            hits = sum(row["receivers"][name]["evidence"] for row in eligible)
            receiver_metrics[name] = dict(
                supported=not self.has_summaries,
                detected_events=hits if not self.has_summaries else None,
                source_eligible_events=len(eligible),
                evidence_recall=(
                    hits / len(eligible)
                    if eligible and not self.has_summaries
                    else None
                ),
                positive_normal_observations=(
                    int(np.count_nonzero(self.positive[:, column] & self.normal))
                    if not self.has_summaries
                    else None
                ),
                scored_normal_observations=int(
                    np.count_nonzero(self.retained & self.normal)
                ),
                delivery_delay_seconds=quantiles_or_none(
                    [
                        row["receivers"][name]["delivery_delay_seconds"]
                        for row in eligible
                        if row["receivers"][name]["evidence"]
                    ]
                ),
            )
        return dict(
            packets=self.packet_count,
            serialized_bytes=self.bytes,
            maximum_packet_bytes=self.maximum_bytes,
            allocated_bytes=self.packet_count * budget_bytes,
            source_observations=len(self.timestamps),
            retained_raw_observations=int(self.retained.sum()),
            source_eligible_events=len(eligible),
            unavailable_or_censored_events=len(rows) - len(eligible),
            events_with_raw_evidence=sum(
                row["retained_samples"] > 0 for row in eligible
            ),
            macro_event_sample_coverage=(
                float(np.mean([row["sample_coverage"] for row in eligible]))
                if eligible
                else None
            ),
            macro_pre_context_coverage=(
                float(
                    np.mean(
                        [
                            row["context_coverage"]
                            for row in eligible
                            if row["context_coverage"] is not None
                        ]
                    )
                )
                if any(row["context_coverage"] is not None for row in eligible)
                else None
            ),
            onset_error_seconds=quantiles_or_none(
                [
                    row["raw_onset_error_seconds"]
                    for row in eligible
                    if row["raw_onset_error_seconds"] is not None
                ]
            ),
            receivers=receiver_metrics,
            coarse_summary=dict(
                overlap_events=len(self.coarse_events),
                annotated_events=len(rows),
                positive_buckets=self.coarse_positive_buckets,
                positive_pure_normal_buckets=self.coarse_normal_positive_buckets,
                interpretation="Bucket overlap only; not precise raw event recall",
            ),
            events=rows,
        )


def evaluate_stream(
    path, timestamps, values, model, cases, normal, config, start_us, end_us
):
    evaluator = NativeEvaluator(
        timestamps, values, model, cases, normal, config.epoch_us, start_us, end_us
    )
    with path.open("rb") as stream:
        for packet in read_packets(stream):
            if (
                packet.duration_us != config.epoch_us
                or packet.budget_bytes != config.budget_bytes
            ):
                raise ValueError(
                    "Packet stream configuration differs from declared arm"
                )
            if (
                packet.start_us < start_us
                or packet.start_us + packet.duration_us > end_us
            ):
                raise ValueError(
                    "Packet epoch outside the declared validation interval"
                )
            evaluator.consume(packet)
    if evaluator.bytes != path.stat().st_size:
        raise ValueError("Stream byte accounting mismatch")
    return evaluator.report(config.budget_bytes)
