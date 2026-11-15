"""Deterministic store-and-forward simulation with byte-limited FIFO storage.

Packets arrive at epoch end. Contacts are discrete service opportunities at
specified times; arrivals at that time enter before service. Each opportunity
has a wire-byte allowance, not a continuous-time radio model. Packets may span
contacts; incomplete or lost packets provide no downstream evidence.
"""

from collections import deque
from dataclasses import asdict, dataclass
import math
import random

from retention.codec import HEADER
from retention.stream import read_packets


@dataclass(frozen=True)
class LinkConfig:
    contact_interval_us: int = 21600000000
    wire_bytes_per_contact: int = 6144
    buffer_bytes: int = 16384
    frame_payload_bytes: int = 128
    frame_overhead_bytes: int = 16
    loss_probability: float = 0.0
    eviction: str = "drop_oldest"
    seed: int = 0

    def __post_init__(self):
        for name in (
            "contact_interval_us",
            "wire_bytes_per_contact",
            "buffer_bytes",
            "frame_payload_bytes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.frame_overhead_bytes) is not int or self.frame_overhead_bytes < 0:
            raise ValueError("Frame overhead must be nonnegative")
        if (
            not math.isfinite(self.loss_probability)
            or not 0 <= self.loss_probability <= 1
        ):
            raise ValueError("Loss probability must be in [0, 1]")
        if self.eviction not in ("drop_oldest", "drop_newest"):
            raise ValueError("Unknown buffer eviction policy")
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise ValueError("Seed must be an unsigned 64-bit integer")

    def wire_size(self, payload_bytes):
        return (
            payload_bytes
            + math.ceil(payload_bytes / self.frame_payload_bytes)
            * self.frame_overhead_bytes
        )


@dataclass
class PendingPacket:
    data: bytes
    arrival_us: int
    remaining_wire_bytes: int


def simulate(source, destination, config, start_us, end_us):
    """Write only complete delivered packets; return auditable byte/packet totals."""
    if source.resolve() == destination.resolve():
        raise ValueError("Delivery output must be separate from captured input")
    if (
        type(start_us) is not int
        or type(end_us) is not int
        or not 0 <= start_us < end_us
    ):
        raise ValueError("Invalid simulation interval")
    rng = random.Random(config.seed)
    queue = deque()
    queued_bytes = 0
    counts = dict(arrived=0, delivered=0, evicted=0, rejected=0, lost=0)
    totals = dict(
        arrived_payload_bytes=0,
        delivered_payload_bytes=0,
        evicted_payload_bytes=0,
        rejected_payload_bytes=0,
        lost_payload_bytes=0,
        transmitted_wire_bytes=0,
        maximum_buffer_payload_bytes=0,
        contacts=0,
    )
    delivered_at = {}
    next_contact = (
        start_us // config.contact_interval_us + 1
    ) * config.contact_interval_us

    with source.open("rb") as incoming, destination.open("xb") as delivered:

        def service(time_us):
            nonlocal queued_bytes
            totals["contacts"] += 1
            capacity = config.wire_bytes_per_contact
            while queue and capacity:
                packet = queue[0]
                used = min(capacity, packet.remaining_wire_bytes)
                capacity -= used
                packet.remaining_wire_bytes -= used
                totals["transmitted_wire_bytes"] += used
                if packet.remaining_wire_bytes:
                    break
                queue.popleft()
                queued_bytes -= len(packet.data)
                if rng.random() < config.loss_probability:
                    counts["lost"] += 1
                    totals["lost_payload_bytes"] += len(packet.data)
                else:
                    counts["delivered"] += 1
                    totals["delivered_payload_bytes"] += len(packet.data)
                    delivered.write(packet.data)
                    # Packet start is encoded by the ordinary decoder, avoiding
                    # a second container or uncharged transport metadata on disk.

                    packet_start = HEADER.unpack_from(packet.data)[3]
                    delivered_at[str(packet_start)] = time_us

        for packet in read_packets(incoming):
            arrival = packet.start_us + packet.duration_us
            if packet.start_us < start_us or arrival > end_us:
                raise ValueError("Captured packet outside simulation interval")
            while next_contact < arrival:
                service(next_contact)
                next_contact += config.contact_interval_us
            data = packet.encode()
            counts["arrived"] += 1
            totals["arrived_payload_bytes"] += len(data)
            if len(data) > config.buffer_bytes:
                counts["rejected"] += 1
                totals["rejected_payload_bytes"] += len(data)
            elif (
                config.eviction == "drop_newest"
                and queued_bytes + len(data) > config.buffer_bytes
            ):
                counts["rejected"] += 1
                totals["rejected_payload_bytes"] += len(data)
            else:
                while queued_bytes + len(data) > config.buffer_bytes:
                    removed = queue.popleft()
                    queued_bytes -= len(removed.data)
                    counts["evicted"] += 1
                    totals["evicted_payload_bytes"] += len(removed.data)
                queue.append(PendingPacket(data, arrival, config.wire_size(len(data))))
                queued_bytes += len(data)
                totals["maximum_buffer_payload_bytes"] = max(
                    totals["maximum_buffer_payload_bytes"], queued_bytes
                )
            if next_contact == arrival:
                service(next_contact)
                next_contact += config.contact_interval_us
        while next_contact <= end_us:
            service(next_contact)
            next_contact += config.contact_interval_us
    counts["pending"] = len(queue)
    totals["pending_payload_bytes"] = queued_bytes
    if counts["arrived"] != sum(
        value for name, value in counts.items() if name != "arrived"
    ):
        raise ValueError("Packet conservation failure")
    if totals["arrived_payload_bytes"] != sum(
        totals[f"{name}_payload_bytes"]
        for name in ("delivered", "evicted", "rejected", "lost", "pending")
    ):
        raise ValueError("Payload conservation failure")
    return dict(
        config=asdict(config),
        packets=counts,
        bytes=totals,
        delivered_at_us=delivered_at,
        interpretation="Discrete contacts; payload-buffer occupancy excludes Python metadata; packet loss after complete transmission, no retransmission; final pending packets provide no evidence",
    )
