import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from convert_esa import grid_statistics, load_aligned_channels


class ChannelLoadingTests(unittest.TestCase):
    def make_channels(self):
        index = pd.to_datetime([
            "2000-01-01T00:00:00Z",
            "2000-01-01T00:00:10Z",
            "2000-01-01T00:01:00Z",
        ])

        return {
            f"channel_{i}": pd.Series(
                [float(i), float(i + 1), float(i + 2)],
                index=index,
            )
            for i in range(41, 47)
        }

    def test_loads_all_six_channels_in_order(self):
        channels = self.make_channels()

        with patch(
            "convert_esa.load_channel",
            side_effect=lambda root, name: channels[name],
        ):
            timestamps, values = load_aligned_channels(Path("unused"))

        self.assertEqual(values.shape, (3, 6))
        self.assertEqual(values.dtype, np.float32)
        np.testing.assert_array_equal(
            values[0],
            np.array([41, 42, 43, 44, 45, 46], dtype=np.float32),
        )
        self.assertEqual(timestamps[1] - timestamps[0], 10_000_000)

    def test_rejects_misaligned_channels(self):
        channels = self.make_channels()

        shifted = channels["channel_44"].copy()
        shifted.index = shifted.index + pd.Timedelta(microseconds=1)
        channels["channel_44"] = shifted

        with patch(
            "convert_esa.load_channel",
            side_effect=lambda root, name: channels[name],
        ):
            with self.assertRaisesRegex(ValueError, "Timestamp alignment"):
                load_aligned_channels(Path("unused"))

    def test_rejects_nonfinite_measurements(self):
        channels = self.make_channels()
        channels["channel_42"].iloc[0] = np.nan

        with patch(
            "convert_esa.load_channel",
            side_effect=lambda root, name: channels[name],
        ):
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                load_aligned_channels(Path("unused"))

    def test_rejects_submicrosecond_timestamps(self):
        channels = self.make_channels()

        modified = channels["channel_41"].copy()
        modified.index = modified.index + pd.Timedelta(nanoseconds=1)
        channels["channel_41"] = modified

        with patch(
            "convert_esa.load_channel",
            side_effect=lambda root, name: channels[name],
        ):
            with self.assertRaisesRegex(ValueError, "sub-microsecond"):
                load_aligned_channels(Path("unused"))

    def test_rejects_duplicate_timestamps(self):
        channels = self.make_channels()

        for name, series in channels.items():
            modified = series.copy()
            modified.index = pd.DatetimeIndex([
                series.index[0],
                series.index[0],
                series.index[2],
            ])
            channels[name] = modified

        with patch(
            "convert_esa.load_channel",
            side_effect=lambda root, name: channels[name],
        ):
            with self.assertRaisesRegex(ValueError, "not increasing"):
                load_aligned_channels(Path("unused"))


class GridStatisticsTests(unittest.TestCase):
    def test_counts_collisions_and_missing_cells(self):
        timestamps = np.array([
            0,
            10_000_000,
            29_000_000,
            30_000_000,
            120_000_000,
        ], dtype=np.int64)

        stats = grid_statistics(timestamps)

        self.assertEqual(stats["raw_samples"], 5)
        self.assertEqual(stats["frame_count"], 5)
        self.assertEqual(stats["occupied"], 3)
        self.assertEqual(stats["empty"], 2)
        self.assertEqual(stats["collisions"], 1)
        self.assertEqual(stats["start_us"], 0)

    def test_nonzero_grid_start(self):
        timestamps = np.array([
            65_000_000,
            95_000_000,
        ], dtype=np.int64)

        stats = grid_statistics(timestamps)

        self.assertEqual(stats["start_us"], 60_000_000)
        self.assertEqual(stats["frame_count"], 2)


if __name__ == "__main__":
    unittest.main()
