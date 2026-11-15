"""Independent source comparison retains full-frame validation without a native CLI."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from convert_esa import grid_statistics
from preprocess import iter_grid_frames
from verify_export import FRAME_DTYPE, verify_export
from write_binary import Header, PERIOD_US, write_binary


class SourceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.timestamps = np.array([0, 10000000, PERIOD_US, 8 * PERIOD_US], dtype="<i8")
        self.values = np.arange(24, dtype="<f4").reshape(4, 6)
        self.header = Header(0, 9, 3 * PERIOD_US, 6 * PERIOD_US)
        write_binary(
            self.root / "telemetry.bin",
            self.header,
            iter_grid_frames(self.timestamps, self.values),
        )
        (self.root / "events.csv").write_text(
            "event_id,channel,category,start_utc,end_utc\n"
        )
        self.enterContext(
            patch("verify_export.verify_dataset", return_value=(self.header, []))
        )
        self.enterContext(
            patch(
                "verify_export.load_aligned_channels",
                return_value=(self.timestamps, self.values),
            )
        )
        self.enterContext(
            patch("verify_export.REFERENCE", grid_statistics(self.timestamps))
        )

    def test_compares_every_frame_and_counts_observed_filled_and_unavailable(self):
        report = verify_export(self.root / "source", self.root)
        self.assertEqual(
            report["frame_states"], dict(observed=3, filled=5, unavailable=1)
        )
        self.assertTrue(report["full_source_parity"])
        self.assertNotIn("cpp_scan", report)

    def test_rejects_changed_measurements_and_each_quality_field(self):
        path = self.root / "telemetry.bin"
        original = path.read_bytes()
        for field, index, value in [
            ("values", (2, 0), 999),
            ("observed", 2, 63),
            ("usable", 7, 63),
            ("staleness", 3, 100),
        ]:
            with self.subTest(field=field):
                path.write_bytes(original)
                frames = np.memmap(
                    path, dtype=FRAME_DTYPE, offset=64, mode="r+", shape=(9,)
                )
                frames[field][index] = value
                frames.flush()
                del frames
                with self.assertRaisesRegex(ValueError, "Frame parity failure"):
                    verify_export(self.root / "source", self.root)
