"""A small experimental wire format with exact, testable byte accounting."""

from dataclasses import dataclass
import math
import struct

HEADER = struct.Struct("<4sHHqQII")
PREFIX = struct.Struct("<BBH")
RAW = struct.Struct("<q6f")
SUMMARY = struct.Struct("<q6f6fI")
RAW_BYTES = PREFIX.size + RAW.size
SUMMARY_BYTES = PREFIX.size + SUMMARY.size


@dataclass(frozen=True)
class Sample:
    timestamp_us: int
    values: tuple[float, ...]

    def __post_init__(self):
        if type(self.timestamp_us) is not int or not 0 <= self.timestamp_us < 2**63:
            raise ValueError("Expected a nonnegative int64 timestamp")
        if len(self.values) != 6 or not all(
            math.isfinite(value) for value in self.values
        ):
            raise ValueError("Expected six finite measurements")
        # Use the same binary32 precision on both sides of retention decisions.
        try:
            encoded = RAW.pack(self.timestamp_us, *self.values)
        except (OverflowError, struct.error) as error:
            raise ValueError("Measurements must fit binary32") from error
        object.__setattr__(self, "values", RAW.unpack(encoded)[1:])


@dataclass(frozen=True)
class RawRecord:
    sample: Sample
    reason: int = 0

    def encode(self) -> bytes:
        if type(self.reason) is not int or not 0 <= self.reason <= 31:
            raise ValueError("Unknown raw-record reason flags")
        return PREFIX.pack(1, self.reason, RAW.size) + RAW.pack(
            self.sample.timestamp_us, *self.sample.values
        )


@dataclass(frozen=True)
class SummaryRecord:
    start_us: int
    minimum: tuple[float, ...]
    maximum: tuple[float, ...]
    count: int

    def encode(self) -> bytes:
        if (
            len(self.minimum) != 6
            or len(self.maximum) != 6
            or not 0 < self.count < 2**32
        ):
            raise ValueError("Invalid summary dimensions or count")
        if any(
            not math.isfinite(low) or not math.isfinite(high) or low > high
            for low, high in zip(self.minimum, self.maximum)
        ):
            raise ValueError("Invalid summary bounds")
        return PREFIX.pack(2, 0, SUMMARY.size) + SUMMARY.pack(
            self.start_us, *self.minimum, *self.maximum, self.count
        )


@dataclass(frozen=True)
class Packet:
    start_us: int
    duration_us: int
    budget_bytes: int
    records: tuple[RawRecord | SummaryRecord, ...]

    def encode(self) -> bytes:
        if (
            not 0 <= self.start_us < 2**63
            or not 0 < self.duration_us < 2**63
            or self.start_us + self.duration_us >= 2**63
            or not HEADER.size <= self.budget_bytes < 2**32
        ):
            raise ValueError("Invalid packet configuration")
        raw_timestamps = set()
        for record in self.records:
            timestamp = (
                record.sample.timestamp_us
                if isinstance(record, RawRecord)
                else record.start_us
            )
            if not self.start_us <= timestamp < self.start_us + self.duration_us:
                raise ValueError("Record outside packet interval")
            if isinstance(record, RawRecord):
                if timestamp in raw_timestamps:
                    raise ValueError("Duplicate raw timestamp")
                raw_timestamps.add(timestamp)
        body = b"".join(record.encode() for record in self.records)
        encoded = (
            HEADER.pack(
                b"TAER",
                1,
                HEADER.size,
                self.start_us,
                self.duration_us,
                self.budget_bytes,
                len(self.records),
            )
            + body
        )
        if len(encoded) > self.budget_bytes:
            raise ValueError("Packet exceeds its byte budget")
        return encoded


def decode_packet(encoded: bytes) -> Packet:
    if len(encoded) < HEADER.size:
        raise ValueError("Truncated packet header")
    magic, version, size, start, duration, budget, count = HEADER.unpack_from(encoded)
    if magic != b"TAER" or version != 1 or size != HEADER.size or len(encoded) > budget:
        raise ValueError("Invalid packet header")
    offset, records = HEADER.size, []
    for _ in range(count):
        if offset + PREFIX.size > len(encoded):
            raise ValueError("Truncated record prefix")
        kind, reason, length = PREFIX.unpack_from(encoded, offset)
        offset += PREFIX.size
        if offset + length > len(encoded):
            raise ValueError("Truncated record payload")
        payload = encoded[offset : offset + length]
        if kind == 1 and length == RAW.size:
            fields = RAW.unpack(payload)
            record = RawRecord(Sample(fields[0], fields[1:]), reason)
            timestamp = record.sample.timestamp_us
        elif kind == 2 and length == SUMMARY.size and reason == 0:
            fields = SUMMARY.unpack(payload)
            record = SummaryRecord(fields[0], fields[1:7], fields[7:13], fields[13])
            timestamp = record.start_us
        else:
            raise ValueError("Unknown record type, size, or flags")
        if not start <= timestamp < start + duration:
            raise ValueError("Record outside packet interval")
        record.encode()  # Validate summary semantics as well as raw fields.
        records.append(record)
        offset += length
    packet = Packet(start, duration, budget, tuple(records))
    if offset != len(encoded) or packet.encode() != encoded:
        raise ValueError("Trailing bytes or noncanonical encoding")
    return packet
