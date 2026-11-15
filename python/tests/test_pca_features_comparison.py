"""Independent numerical references and evidence-retention regression tests."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from comparison import (
    alarm_catalog,
    score_raw_evidence,
    grouped_metrics,
    held_alarm_intervals,
    channel_evidence,
    select_with_budget,
    validation_selection,
)
from evaluate import label_masks, partition_events
from dataset import sha256
from export_features import verify_features, write_features
from verify_export import FRAME_DTYPE
from write_binary import Frame, Header, PERIOD_US, write_binary


class RawFeatureTests(unittest.TestCase):
    def test_discarded_spike_is_retained_and_filled_cells_have_no_raw_evidence(self):
        header = Header(0, 5, PERIOD_US, 3 * PERIOD_US)
        timestamps = np.array([0, 10_000_000, 20_000_000, 120_000_000], dtype=np.int64)
        values = np.zeros((4, 6), dtype=np.float32)
        values[1, 2] = 9
        frames = np.zeros(5, dtype=FRAME_DTYPE)
        frames["observed"][[0, 4]] = 63
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_features(root / "features.npy", timestamps, values, header, frames)
            features = np.load(root / "features.npy")
            np.testing.assert_array_equal(features["sample_count"], [3, 0, 0, 0, 1])
            self.assertEqual(features["maximum"][0, 2], 9)
            self.assertTrue(np.all(np.isnan(features["minimum"][1:4])))
            runtime = dict(normalization=[dict(mean=0, variance=1)] * 6)
            scores = score_raw_evidence(root / "scores.npy", features, frames, runtime)
            np.testing.assert_array_equal(scores[0], [0, 9, 9])
            self.assertTrue(np.all(np.isnan(scores[1:4])))
            explanation = channel_evidence(
                "raw_excursion", frames[0], features[0], runtime
            )
            self.assertEqual(explanation["channels"][0]["channel"], 43)
            self.assertEqual(explanation["channels"][0]["contribution"], 9)

    def test_feature_verifier_checks_binding_hash_and_extrema_invariants(self):
        header = Header(0, 3, PERIOD_US, 2 * PERIOD_US)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telemetry = root / "telemetry.bin"
            write_binary(telemetry, header, [Frame((1.0,) * 6, 63, 63, 0)] * 3)
            frames = np.memmap(
                telemetry, mode="r", dtype=FRAME_DTYPE, offset=64, shape=(3,)
            )
            write_features(
                root / "cell_features.npy",
                np.arange(3) * PERIOD_US,
                np.ones((3, 6), dtype=np.float32),
                header,
                frames,
            )
            manifest = dict(
                format="TAE-CELL-FEATURES",
                version=1,
                channels=list(range(41, 47)),
                frame_count=3,
                grid_period_us=PERIOD_US,
                telemetry_sha256=sha256(telemetry),
                features_sha256=sha256(root / "cell_features.npy"),
            )
            (root / "manifest.json").write_text(json.dumps(manifest))
            verify_features(root, root, header)
            changed = np.load(root / "cell_features.npy", mmap_mode="r+")
            changed["maximum"][0] = 0
            changed.flush()
            del changed
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_features(root, root, header)
            manifest["features_sha256"] = sha256(root / "cell_features.npy")
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "extrema"):
                verify_features(root, root, header)
            manifest["telemetry_sha256"] = "0" * 64
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "different telemetry"):
                verify_features(root, root, header)

    def test_export_rejects_mismatched_source_values(self):
        header = Header(0, 3, PERIOD_US, 2 * PERIOD_US)
        timestamps = np.array([0, 2 * PERIOD_US], dtype=np.int64)
        values = np.ones((2, 6), dtype=np.float32)
        frames = np.zeros(3, dtype=FRAME_DTYPE)
        frames["observed"][[0, 2]] = 63
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "keep-last"):
                write_features(
                    Path(directory) / "features.npy", timestamps, values, header, frames
                )


class AlarmHoldTests(unittest.TestCase):
    def test_holds_only_across_short_unscored_permitted_gaps(self):
        scores = np.array([10.0, np.nan, 10.0, 0.0, 10.0])
        eligible = np.array([True, False, True, True, True])
        bridgeable = np.array([False, True, False, False, False])
        self.assertEqual(
            held_alarm_intervals(scores, eligible, 5, bridgeable, 5), [(0, 3), (4, 5)]
        )
        self.assertEqual(
            held_alarm_intervals(scores, eligible, 5, bridgeable, 0),
            [(0, 1), (2, 3), (4, 5)],
        )
        # Excluded labels and unavailable cells are represented by bridgeable=False.
        bridgeable[1] = False
        self.assertEqual(
            len(held_alarm_intervals(scores, eligible, 5, bridgeable, 5)), 3
        )
        # Even an incorrectly supplied mask cannot bridge observed low-score cells.
        bridgeable[:] = True
        self.assertEqual(
            held_alarm_intervals(scores, eligible, 5, bridgeable, 5), [(0, 3), (4, 5)]
        )

    def test_held_missing_cell_never_receives_event_detection_credit(self):
        header = Header(0, 3, PERIOD_US, 2 * PERIOD_US)
        scores = np.array([10.0, np.nan, 20.0])
        eligible = np.array([True, False, True])
        bridgeable = ~eligible
        event = dict(
            event_id="missing-point",
            category="Anomaly",
            channel=41,
            start_us=PERIOD_US,
            end_us=PERIOD_US,
        )
        metrics = grouped_metrics(
            scores, eligible, [event], header, 5, np.zeros(3), bridgeable, 5
        )
        self.assertEqual(metrics["detected_events"], 0)
        self.assertEqual(metrics["unscorable_events"], 1)
        self.assertEqual(metrics["alarm_held_unscored_cells"], 1)
        self.assertEqual(metrics["false_alarms"], 1)
        catalog = alarm_catalog(scores, eligible, [event], header, 5, bridgeable, 5)
        self.assertEqual(catalog[0]["peak_cell"], 2)
        json.dumps(catalog, allow_nan=False)


class ComparisonSelectionTests(unittest.TestCase):
    def test_selection_can_use_thresholds_above_maximum_normal_score(self):
        header = Header(0, 100, 10 * PERIOD_US, 90 * PERIOD_US)
        scores = np.ones(100)
        scores[20:60:2] = 10
        scores[70] = 1000
        events = [
            dict(
                event_id="fragmented",
                channel=41,
                category="Anomaly",
                start_us=20 * PERIOD_US,
                end_us=60 * PERIOD_US,
            ),
            dict(
                event_id="spike",
                channel=41,
                category="Anomaly",
                start_us=70 * PERIOD_US,
                end_us=70 * PERIOD_US,
            ),
        ]
        eligible = np.zeros(100, dtype=bool)
        eligible[10:90] = True
        masks = label_masks(events, header)
        selected, _ = select_with_budget(
            scores, eligible, events, header, masks["Anomaly"], 0
        )
        self.assertGreater(selected["threshold"], 10)
        self.assertEqual(selected["detected_events"], 1)
        self.assertEqual(selected["false_alarms"], 0)

    def test_budget_is_hard_constraint_and_selection_ignores_test_changes(self):
        header = Header(0, 100, 30 * PERIOD_US, 70 * PERIOD_US)
        events = [
            dict(
                event_id="validation",
                channel=41,
                category="Anomaly",
                start_us=40 * PERIOD_US,
                end_us=41 * PERIOD_US,
            ),
            dict(
                event_id="test",
                channel=41,
                category="Anomaly",
                start_us=80 * PERIOD_US,
                end_us=81 * PERIOD_US,
            ),
        ]
        masks = label_masks(events, header)
        eligible = np.zeros(100, dtype=bool)
        eligible[30:70] = True
        scores = np.zeros(100)
        scores[40] = 10
        scores[50] = 5
        partition = partition_events(events, header, 30, 70)
        selected, _ = select_with_budget(
            scores, eligible, partition, header, masks["Anomaly"], 0
        )
        self.assertEqual(selected["detected_events"], 1)
        self.assertEqual(selected["false_alarms"], 0)
        expected = validation_selection(
            {"pca_1": scores, "raw_excursion": scores},
            eligible,
            partition,
            header,
            masks["Anomaly"],
            0,
        )
        scores[70:] = 1e100
        actual = validation_selection(
            {"pca_1": scores, "raw_excursion": scores},
            eligible,
            partition,
            header,
            masks["Anomaly"],
            0,
        )
        self.assertEqual(actual, expected)
        # NumPy scalars must not leak into persisted selection metadata.
        json.dumps(actual, allow_nan=False)
        eligible[80] = True
        with self.assertRaisesRegex(ValueError, "validation-only"):
            validation_selection(
                {"pca_1": scores}, eligible, events, header, masks["Anomaly"], 0
            )
