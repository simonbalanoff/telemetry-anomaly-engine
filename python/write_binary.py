import os
import tempfile
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAGIC = b"TAE1"
VERSION = 1
HEADER_SIZE = 64
FRAME_SIZE = 28
CHANNEL_COUNT = 6
PERIOD_US = 30_000_000
ALL_CHANNELS = 0x3F
MAX_FILL = 5
MAX_STALENESS = 65535

HEADER_FORMAT = "<4sHHIIqQqqIIQ"
FRAME_FORMAT = "<6fBBH"

assert struct.calcsize(HEADER_FORMAT) == HEADER_SIZE
assert struct.calcsize(FRAME_FORMAT) == FRAME_SIZE


@dataclass(frozen=True)
class Header:
    start_us: int
    frame_count: int
    validation_start_us: int
    test_start_us: int


@dataclass(frozen=True)
class Frame:
    values: tuple[float, float, float, float, float, float]
    observed_mask: int
    usable_mask: int
    staleness: int


def encode_header(header: Header) -> bytes:
    if not isinstance(header.frame_count, int):
        raise ValueError("Frame count must be an integer")

    if header.frame_count <= 0:
        raise ValueError("Frame count must be positive")

    for timestamp in (
        header.start_us,
        header.validation_start_us,
        header.test_start_us,
    ):
        if not isinstance(timestamp, int):
            raise ValueError("Timestamps must be integers")

        if timestamp % PERIOD_US != 0:
            raise ValueError("Timestamp is not grid-aligned")

    if not (
        header.start_us
        < header.validation_start_us
        < header.test_start_us
    ):
        raise ValueError("Invalid split boundary ordering")

    max_i64 = (1 << 63) - 1
    max_u64 = (1 << 64) - 1

    if header.frame_count > (max_u64 - HEADER_SIZE) // FRAME_SIZE:
        raise ValueError("File size overflows uint64")

    duration = header.frame_count * PERIOD_US
    end_us = header.start_us + duration

    if not -(1 << 63) <= header.start_us <= max_i64:
        raise ValueError("Start timestamp outside int64 range")

    if end_us > max_i64 or end_us < -(1 << 63):
        raise ValueError("Final timestamp outside int64 range")

    if header.test_start_us > end_us:
        raise ValueError("Test boundary outside telemetry range")

    try:
        return struct.pack(
            HEADER_FORMAT,
            MAGIC,
            VERSION,
            HEADER_SIZE,
            CHANNEL_COUNT,
            30000,
            header.start_us,
            header.frame_count,
            header.validation_start_us,
            header.test_start_us,
            FRAME_SIZE,
            0,
            0,
        )
    except (struct.error, OverflowError) as exc:
        raise ValueError("Header fields cannot be encoded") from exc


def encode_frame(frame: Frame) -> bytes:
    if len(frame.values) != CHANNEL_COUNT:
        raise ValueError("Frame must contain six values")

    if frame.observed_mask not in (0, ALL_CHANNELS):
        raise ValueError("Invalid observed mask")

    if frame.usable_mask not in (0, ALL_CHANNELS):
        raise ValueError("Invalid usable mask")

    if not 0 <= frame.staleness <= MAX_STALENESS:
        raise ValueError("Staleness outside uint16 range")

    if frame.observed_mask == ALL_CHANNELS:
        if frame.usable_mask != ALL_CHANNELS or frame.staleness != 0:
            raise ValueError("Invalid observed frame")

    elif frame.usable_mask == ALL_CHANNELS:
        if not 1 <= frame.staleness <= MAX_FILL:
            raise ValueError("Invalid forward-filled frame")

    elif frame.staleness <= MAX_FILL:
        raise ValueError("Unavailable frame has invalid staleness")

    try:
        encoded = struct.pack(
            FRAME_FORMAT,
            *frame.values,
            frame.observed_mask,
            frame.usable_mask,
            frame.staleness,
        )
    except (struct.error, OverflowError) as exc:
        raise ValueError("Frame fields cannot be encoded") from exc

    if frame.usable_mask == 0:
        if encoded[:24] != bytes(24):
            raise ValueError("Unavailable values must be positive zero")
    else:
        decoded_values = struct.unpack("<6f", encoded[:24])

        if not all(math.isfinite(value) for value in decoded_values):
            raise ValueError("Usable values must be finite")

    return encoded


class FrameWriter:
    def __init__(self):
        self.last_observed = None
        self.previous_staleness = 0

    def validate(self, frame: Frame, encoded: bytes) -> None:
        if self.last_observed is None:
            if frame.observed_mask != ALL_CHANNELS:
                raise ValueError("First frame must be observed")

        elif frame.observed_mask == 0:
            expected = min(self.previous_staleness + 1, MAX_STALENESS)

            if frame.staleness != expected:
                raise ValueError("Invalid staleness transition")

            if frame.usable_mask == ALL_CHANNELS:
                if encoded[:24] != self.last_observed:
                    raise ValueError("Filled values differ from observation")

        if frame.observed_mask == ALL_CHANNELS:
            self.last_observed = encoded[:24]

        self.previous_staleness = frame.staleness



def write_binary(
    path: Path,
    header: Header,
    frames: Iterable[Frame],
) -> None:
    destination = Path(path)
    header_bytes = encode_header(header)
    validator = FrameWriter()
    count = 0

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(header_bytes)

            for frame in frames:
                if count >= header.frame_count:
                    raise ValueError("More frames than declared")

                encoded = encode_frame(frame)
                validator.validate(frame, encoded)
                stream.write(encoded)
                count += 1

            if count != header.frame_count:
                raise ValueError(
                    f"Expected {header.frame_count} frames, received {count}"
                )

            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary_path, destination)

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
