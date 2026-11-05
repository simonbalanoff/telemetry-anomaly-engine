import unittest

import numpy as np

from preprocess import iter_grid_frames


class GridTests(unittest.TestCase):
    def test_single_observation(self):
        timestamps = np.array([0], dtype=np.int64)
        values = np.ones((1, 6), dtype=np.float32)

        frames = list(iter_grid_frames(timestamps, values))

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].observed_mask, 0x3F)

    def test_keep_last_collision(self):
        timestamps = np.array([
            0,
            10_000_000,
            29_000_000,
            30_000_000,
        ])

        values = np.array([
            [1.0] * 6,
            [2.0] * 6,
            [3.0] * 6,
            [4.0] * 6,
        ])

        frames = list(iter_grid_frames(timestamps, values))

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].values, (3.0,) * 6)
        self.assertEqual(frames[1].values, (4.0,) * 6)

    def test_five_missing_cells(self):
        timestamps = np.array([
            0,
            180_000_000,
        ])

        values = np.array([
            [1.0] * 6,
            [2.0] * 6,
        ])

        frames = list(iter_grid_frames(timestamps, values))

        self.assertEqual(len(frames), 7)

        for i in range(1, 6):
            self.assertEqual(frames[i].staleness, i)
            self.assertEqual(frames[i].observed_mask, 0)
            self.assertEqual(frames[i].usable_mask, 0x3F)
            self.assertEqual(frames[i].values, (1.0,) * 6)

    def test_sixth_missing_cell_becomes_unavailable(self):
        timestamps = np.array([
            0,
            210_000_000,
        ])

        values = np.array([
            [1.0] * 6,
            [2.0] * 6,
        ])

        frames = list(iter_grid_frames(timestamps, values))

        self.assertEqual(len(frames), 8)
        self.assertEqual(frames[6].staleness, 6)
        self.assertEqual(frames[6].usable_mask, 0)
        self.assertEqual(frames[6].values, (0.0,) * 6)
        self.assertEqual(frames[7].staleness, 0)
        self.assertEqual(frames[7].values, (2.0,) * 6)

    def test_rejects_duplicate_timestamps(self):
        timestamps = np.array([0, 0])
        values = np.ones((2, 6))

        with self.assertRaises(ValueError):
            list(iter_grid_frames(timestamps, values))

    def test_rejects_nonfinite_values(self):
        timestamps = np.array([0])
        values = np.full((1, 6), np.nan)

        with self.assertRaises(ValueError):
            list(iter_grid_frames(timestamps, values))


if __name__ == "__main__":
    unittest.main()
