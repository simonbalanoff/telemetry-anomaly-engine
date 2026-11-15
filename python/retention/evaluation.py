"""Retention evaluation on decoded packets, independent of the capture trigger."""

from dataclasses import dataclass

from retention.codec import Packet, RawRecord, SummaryRecord, SUMMARY_BYTES, HEADER


@dataclass(frozen=True)
class Event:
    event_id: str
    start_us: int
    end_us: int
    affected_channels: tuple[int, ...]


def raw_samples(packets: list[Packet]):
    return {
        record.sample.timestamp_us: record.sample
        for packet in packets
        for record in packet.records
        if isinstance(record, RawRecord)
    }


def evaluate_retention(
    packets, source, events, downstream_threshold=4.0, context_us=15_000_000
):
    """Synthetic receiver uses absolute amplitude, not the capture difference score.

    Summary evidence can intersect an event only at bucket resolution. Its result
    is reported separately from exact raw event coverage, never as a recovered
    precise onset. Packets become available at epoch end in this simulation.
    """
    retained = raw_samples(packets)
    per_event = []
    for event in events:
        stop = event.end_us if event.end_us > event.start_us else event.start_us + 1
        event_source = [
            sample for sample in source if event.start_us <= sample.timestamp_us < stop
        ]
        kept = [sample for sample in event_source if sample.timestamp_us in retained]
        context = [
            sample
            for sample in source
            if event.start_us - context_us <= sample.timestamp_us < event.start_us
        ]
        context_kept = sum(sample.timestamp_us in retained for sample in context)
        evidence_deliveries = []
        for packet in packets:
            delivery = packet.start_us + packet.duration_us
            for record in packet.records:
                if isinstance(record, RawRecord):
                    if (
                        event.start_us <= record.sample.timestamp_us < stop
                        and max(
                            abs(record.sample.values[c])
                            for c in event.affected_channels
                        )
                        >= downstream_threshold
                    ):
                        evidence_deliveries.append(delivery)
                else:
                    capacity = (packet.budget_bytes - HEADER.size) // SUMMARY_BYTES
                    slot = (
                        (record.start_us - packet.start_us)
                        * capacity
                        // packet.duration_us
                    )
                    end = (
                        packet.start_us
                        + ((slot + 1) * packet.duration_us + capacity - 1) // capacity
                    )
                    if record.start_us < stop and event.start_us < end:
                        if (
                            max(
                                max(abs(record.minimum[c]), abs(record.maximum[c]))
                                for c in event.affected_channels
                            )
                            >= downstream_threshold
                        ):
                            evidence_deliveries.append(delivery)
        per_event.append(
            dict(
                event_id=event.event_id,
                source_samples=len(event_source),
                retained_raw_samples=len(kept),
                raw_sample_coverage=(
                    len(kept) / len(event_source) if event_source else None
                ),
                pre_context_samples=len(context),
                retained_pre_context_samples=context_kept,
                raw_onset_error_us=min(
                    (sample.timestamp_us - event.start_us for sample in kept),
                    default=None,
                ),
                receiver_evidence=bool(evidence_deliveries),
                receiver_delivery_delay_us=(
                    min(evidence_deliveries) - event.start_us
                    if evidence_deliveries
                    else None
                ),
            )
        )
    sizes = [len(packet.encode()) for packet in packets]
    return dict(
        packets=len(packets),
        serialized_bytes=sum(sizes),
        maximum_packet_bytes=max(sizes, default=0),
        allocated_bytes=sum(packet.budget_bytes for packet in packets),
        retained_raw_samples=len(retained),
        source_samples=len(source),
        events_with_raw_samples=sum(
            item["retained_raw_samples"] > 0 for item in per_event
        ),
        events_with_receiver_evidence=sum(
            item["receiver_evidence"] for item in per_event
        ),
        events=per_event,
    )
