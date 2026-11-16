"""Evidence loss under receiver mismatch, with source-fixed event denominators."""

import numpy as np

from retention.codec import RawRecord
from retention.native_model import observation_interval
from retention.receiver_bank import NAMES
from retention.stream import read_packets


def evaluate_bank_stream(
    path,
    timestamps,
    values,
    positive,
    cases,
    eligible,
    normal,
    config,
    start_us,
    end_us,
    capture_scores=None,
    delivered_at=None,
    context_us=300000000,
):
    retained = np.zeros(len(timestamps), dtype=bool)
    packets = total_bytes = maximum = 0
    with path.open("rb") as stream:
        for packet in read_packets(stream):
            if (
                packet.duration_us != config.epoch_us
                or packet.budget_bytes != config.budget_bytes
                or packet.start_us < start_us
                or packet.start_us + packet.duration_us > end_us
            ):
                raise ValueError("Packet differs from declared benchmark arm")
            if any(not isinstance(record, RawRecord) for record in packet.records):
                raise ValueError(
                    "Receiver mismatch requires raw records, not extrema summaries"
                )
            times = np.array(
                [r.sample.timestamp_us for r in packet.records], dtype=np.int64
            )
            positions = np.searchsorted(timestamps, times)
            if np.any(positions >= len(timestamps)) or not np.array_equal(
                timestamps[positions], times
            ):
                raise ValueError("Retained timestamps are not original observations")
            measured = np.asarray(
                [r.sample.values for r in packet.records], dtype="<f4"
            ).reshape(-1, 6)
            expected = np.ascontiguousarray(values[positions])
            if not np.array_equal(measured.view("<u4"), expected.view("<u4")):
                raise ValueError("Retained values differ from native measurements")
            retained[positions] = True
            size = len(packet.encode())
            packets += 1
            total_bytes += size
            maximum = max(maximum, size)
    if total_bytes != path.stat().st_size:
        raise ValueError("Byte accounting mismatch")
    rows = []
    for case in cases:
        indices = case.indices
        onset = min(row["start_us"] for row in case.annotations)
        ending = max(row["end_us"] for row in case.annotations)
        post_start = ending + int(ending == onset)
        left, right = observation_interval(timestamps, post_start, ending + context_us)
        post = np.arange(left, right, dtype=np.int64)
        post = post[eligible[post]]
        row = dict(
            event_id=case.event_id,
            source_eligible=bool(len(indices)) and not case.censored,
            boundary_censored=bool(case.censored),
            source_samples=len(indices),
            retained_samples=int(retained[indices].sum()),
            pre_context_coverage=(
                float(retained[case.context].mean()) if len(case.context) else None
            ),
            post_context_coverage=float(retained[post].mean()) if len(post) else None,
            post_context_boundary_censored=ending + context_us > end_us,
            within_event_trigger_blind=(
                not bool(np.any(capture_scores[indices] >= config.threshold))
                if capture_scores is not None
                else None
            ),
            receivers={},
        )
        for column, name in enumerate(NAMES):
            source_hits = indices[positive[indices, column]]
            hits = source_hits[retained[source_hits]]
            delay = None
            if len(hits):
                epochs = timestamps[hits] // config.epoch_us * config.epoch_us
                arrival = (
                    min(delivered_at[str(int(epoch))] for epoch in epochs)
                    if delivered_at is not None
                    else int(epochs[0]) + config.epoch_us
                )
                delay = (arrival - onset) / 1e6
            row["receivers"][name] = dict(
                full_archive_evidence=bool(len(source_hits)),
                retained_evidence=bool(len(hits)),
                delivery_delay_seconds=delay,
            )
        rows.append(row)
    scored = [row for row in rows if row["source_eligible"]]
    receivers = {}
    for column, name in enumerate(NAMES):
        recoverable = [
            r for r in scored if r["receivers"][name]["full_archive_evidence"]
        ]
        blind = [r for r in recoverable if r["within_event_trigger_blind"]]
        receivers[name] = dict(
            source_eligible_events=len(scored),
            full_archive_events=len(recoverable),
            retained_events=sum(
                r["receivers"][name]["retained_evidence"] for r in scored
            ),
            retention_misses=sum(
                not r["receivers"][name]["retained_evidence"] for r in recoverable
            ),
            trigger_blind_recoverable_events=(
                len(blind) if capture_scores is not None else None
            ),
            trigger_blind_retained_events=(
                sum(r["receivers"][name]["retained_evidence"] for r in blind)
                if capture_scores is not None
                else None
            ),
            positive_normal_observations=int(
                np.count_nonzero(retained & normal & positive[:, column])
            ),
            scored_normal_observations=int(np.count_nonzero(retained & normal)),
        )

    def context_mean(key):
        entries = [row[key] for row in scored if row[key] is not None]
        return float(np.mean(entries)) if entries else None

    return dict(
        serialized_bytes=total_bytes,
        packets=packets,
        maximum_packet_bytes=maximum,
        source_eligible_events=len(scored),
        raw_events=sum(r["retained_samples"] > 0 for r in scored),
        pre_context_coverage=context_mean("pre_context_coverage"),
        post_context_coverage=context_mean("post_context_coverage"),
        receivers=receivers,
        events=rows,
    )
