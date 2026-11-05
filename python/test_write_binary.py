import math
import struct
import tempfile
import unittest
from pathlib import Path

from write_binary import (
    ALL_CHANNELS,
    FRAME_SIZE,
    HEADER_SIZE,
    Frame,
    FrameWriter,
    Header,
    encode_frame,
    encode_header,
    write_binary,
)


VALUES = (0.5, 0.25, 0.0, -0.5, 1.0, 0.75)
ZERO = (0.0,) * 6

START_US = 946684800000000
VALIDATION_US = 1199145600000000
TEST_US = 1293840000000000
FRAME_COUNT = 14728320


def observed(values=VALUES):
    return Frame(values, ALL_CHANNELS, ALL_CHANNELS, 0)


def filled(staleness, values=VALUES):
    return Frame(values, 0, ALL_CHANNELS, staleness)


def unavailable(staleness):
    return Frame(ZERO, 0, 0, staleness)


def make_header():
    return Header(
        START_US,
        FRAME_COUNT,
        VALIDATION_US,
        TEST_US,
    )


class HeaderTests(unittest.TestCase):
    def test_header_is_64_bytes(self):
        data = encode_header(make_header())
        self.assertEqual(len(data), HEADER_SIZE)

    def test_magic_and_version(self):
        data = encode_header(make_header())

        self.assertEqual(data[:4], b"TAE1")
        self.assertEqual(struct.unpack_from("<H", data, 4)[0], 1)
        self.assertEqual(struct.unpack_from("<H", data, 6)[0], 64)

    def test_header_fields(self):
        data = encode_header(make_header())

        self.assertEqual(struct.unpack_from("<I", data, 8)[0], 6)
        self.assertEqual(struct.unpack_from("<I", data, 12)[0], 30000)
        self.assertEqual(struct.unpack_from("<q", data, 16)[0], START_US)
        self.assertEqual(struct.unpack_from("<Q", data, 24)[0], FRAME_COUNT)
        self.assertEqual(
            struct.unpack_from("<q", data, 32)[0],
            VALIDATION_US,
        )
        self.assertEqual(
            struct.unpack_from("<q", data, 40)[0],
            TEST_US,
        )
        self.assertEqual(struct.unpack_from("<I", data, 48)[0], 28)
        self.assertEqual(data[52:], bytes(12))

    def test_rejects_zero_frames(self):
        header = Header(START_US, 0, VALIDATION_US, TEST_US)

        with self.assertRaises(ValueError):
            encode_header(header)

    def test_rejects_misaligned_timestamp(self):
        header = Header(
            START_US + 1,
            FRAME_COUNT,
            VALIDATION_US,
            TEST_US,
        )

        with self.assertRaises(ValueError):
            encode_header(header)

    def test_rejects_reversed_boundaries(self):
        header = Header(
            START_US,
            FRAME_COUNT,
            TEST_US,
            VALIDATION_US,
        )

        with self.assertRaises(ValueError):
            encode_header(header)

    def test_rejects_out_of_range_boundary(self):
        header = Header(
            START_US,
            10,
            VALIDATION_US,
            TEST_US,
        )

        with self.assertRaises(ValueError):
            encode_header(header)


class FrameTests(unittest.TestCase):
    def test_frame_is_28_bytes(self):
        data = encode_frame(observed())
        self.assertEqual(len(data), FRAME_SIZE)

    def test_float_encoding(self):
        data = encode_frame(observed())

        expected = (
            "0000003f"
            "0000803e"
            "00000000"
            "000000bf"
            "0000803f"
            "0000403f"
        )

        self.assertEqual(data[:24].hex(), expected)

    def test_mask_offsets(self):
        data = encode_frame(observed())

        self.assertEqual(data[24], ALL_CHANNELS)
        self.assertEqual(data[25], ALL_CHANNELS)
        self.assertEqual(data[26:28], b"\x00\x00")

    def test_forward_fill_encoding(self):
        data = encode_frame(filled(3))

        self.assertEqual(data[24], 0)
        self.assertEqual(data[25], ALL_CHANNELS)
        self.assertEqual(data[26:28], b"\x03\x00")

    def test_unavailable_encoding(self):
        data = encode_frame(unavailable(6))

        self.assertEqual(data[:24], bytes(24))
        self.assertEqual(data[24:28], b"\x00\x00\x06\x00")

    def test_rejects_wrong_value_count(self):
        frame = Frame((1.0, 2.0), ALL_CHANNELS, ALL_CHANNELS, 0)

        with self.assertRaises(ValueError):
            encode_frame(frame)

    def test_rejects_invalid_mask(self):
        frame = Frame(VALUES, 0x01, ALL_CHANNELS, 0)

        with self.assertRaises(ValueError):
            encode_frame(frame)

    def test_rejects_fill_beyond_limit(self):
        with self.assertRaises(ValueError):
            encode_frame(filled(6))

    def test_rejects_unavailable_too_early(self):
        with self.assertRaises(ValueError):
            encode_frame(unavailable(5))

    def test_rejects_negative_zero_when_unavailable(self):
        frame = Frame((-0.0,) + ZERO[1:], 0, 0, 6)

        with self.assertRaises(ValueError):
            encode_frame(frame)

    def test_rejects_nan(self):
        values = (math.nan,) + VALUES[1:]

        with self.assertRaises(ValueError):
            encode_frame(observed(values))

    def test_rejects_infinity(self):
        values = (math.inf,) + VALUES[1:]

        with self.assertRaises(ValueError):
            encode_frame(observed(values))


class SequenceTests(unittest.TestCase):
    def test_twelve_frame_fixture(self):
        frames = [
            observed(),
            observed(),
            filled(1),
            filled(2),
            filled(3),
            filled(4),
            filled(5),
            unavailable(6),
            unavailable(7),
            observed((1.0, 2.0, 3.0, 4.0, 5.0, 6.0)),
            observed(),
            observed(),
        ]

        validator = FrameWriter()
        payload = bytearray()

        for frame in frames:
            encoded = encode_frame(frame)
            validator.validate(frame, encoded)
            payload.extend(encoded)

        self.assertEqual(len(payload), 12 * FRAME_SIZE)

    def test_rejects_missing_first_observation(self):
        validator = FrameWriter()
        frame = filled(1)

        with self.assertRaises(ValueError):
            validator.validate(frame, encode_frame(frame))

    def test_rejects_skipped_staleness(self):
        validator = FrameWriter()
        first = observed()

        validator.validate(first, encode_frame(first))

        frame = filled(3)

        with self.assertRaises(ValueError):
            validator.validate(frame, encode_frame(frame))

    def test_rejects_changed_filled_values(self):
        validator = FrameWriter()
        first = observed()

        validator.validate(first, encode_frame(first))

        changed = filled(1, (0.9,) + VALUES[1:])

        with self.assertRaises(ValueError):
            validator.validate(changed, encode_frame(changed))

    def test_saturates_staleness(self):
        validator = FrameWriter()

        first = observed()
        validator.validate(first, encode_frame(first))

        validator.previous_staleness = 65534

        frame = unavailable(65535)
        validator.validate(frame, encode_frame(frame))
        validator.validate(frame, encode_frame(frame))


class FileTests(unittest.TestCase):
    def test_writes_small_synthetic_file(self):
        header = Header(
            start_us=0,
            frame_count=4,
            validation_start_us=30_000_000,
            test_start_us=60_000_000,
        )

        frames = [
            observed(),
            filled(1),
            filled(2),
            observed((1.0,) * 6),
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.bin"

            write_binary(path, header, frames)

            data = path.read_bytes()

            self.assertEqual(len(data), 64 + 4 * 28)
            self.assertEqual(data[:4], b"TAE1")
            self.assertEqual(data[64:92], encode_frame(frames[0]))
            self.assertEqual(data[92:120], encode_frame(frames[1]))

    def test_rejects_wrong_frame_count(self):
        header = Header(
            start_us=0,
            frame_count=4,
            validation_start_us=30_000_000,
            test_start_us=60_000_000,
        )

        frames = [observed(), filled(1)]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete.bin"

            with self.assertRaises(ValueError):
                write_binary(path, header, frames)


if __name__ == "__main__":
    unittest.main()
