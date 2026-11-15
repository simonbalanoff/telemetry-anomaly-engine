"""Independent numerical references and evidence-retention regression tests."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from comparison import (
    alarm_catalog,
    grouped_metrics,
    held_alarm_intervals,
    channel_evidence,
    select_with_budget,
    validation_selection,
)
from evaluate import label_masks, partition_events
from dataset import sha256
from export_features import verify_features, write_features
from run_comparison import score_raw_evidence
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


class PcaCppParityTests(unittest.TestCase):
    def test_all_five_pca_ranks_match_numpy_and_ignore_label_ineligible_training(self):
        executable = Path(
            os.environ.get("TAE_EXECUTABLE", "build/debug/apps/cli/tae")
        ).resolve()
        if not executable.exists():
            self.skipTest("Build tae or set TAE_EXECUTABLE")
        generator = np.random.default_rng(2026)
        mixing = generator.normal(size=(6, 6))
        values = (generator.normal(size=(180, 6)) @ mixing + np.arange(6)).astype(
            np.float32
        )
        header = Header(0, 180, 100 * PERIOD_US, 140 * PERIOD_US)
        frames = [Frame(tuple(row), 63, 63, 0) for row in values]
        # An excluded training outlier must not affect normalization or covariance.
        frames[70] = Frame((1e6,) * 6, 63, 63, 0)
        for index in range(120, 125):
            frames[index] = Frame(frames[119].values, 0, 63, index - 119)
        frames[125] = Frame((0.0,) * 6, 0, 0, 6)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_binary(root / "telemetry.bin", header, frames)
            mask = np.zeros(180, dtype=np.uint8)
            mask[:70] = 1
            mask.tofile(root / "mask.bin")
            command = [
                str(executable),
                "score-pca",
                str(root / "telemetry.bin"),
                str(root / "mask.bin"),
                str(root / "scores.bin"),
                str(root / "runtime.json"),
                "4",
                ".2",
                "--synthetic-fixture",
            ]
            subprocess.run(command, check=True, capture_output=True)
            runtime = json.loads((root / "runtime.json").read_text())
            actual = np.fromfile(root / "scores.bin", dtype="<f8").reshape(-1, 7)
            training = values[:70].astype(float)
            mean, sigma = training.mean(axis=0), training.std(axis=0, ddof=1)
            covariance = np.cov(((training - mean) / sigma).T)
            eigenvalues, eigenvectors = np.linalg.eigh(covariance)
            eigenvalues, eigenvectors = eigenvalues[::-1], eigenvectors[:, ::-1]
            np.testing.assert_allclose(
                runtime["pca_eigenvalues"], eigenvalues, atol=1e-11
            )
            basis = np.asarray(runtime["pca_eigenvectors"])
            np.testing.assert_allclose(
                basis @ np.diag(eigenvalues) @ basis.T, covariance, atol=1e-11
            )
            for rank in range(1, 6):
                expected = np.full(180, np.nan)
                for index, frame in enumerate(frames):
                    if np.isfinite(actual[index, 0]) and frame.observed_mask:
                        normalized = (np.asarray(frame.values) - mean) / sigma
                        projector = eigenvectors[:, :rank] @ eigenvectors[:, :rank].T
                        expected[index] = np.mean(
                            (normalized - projector @ normalized) ** 2
                        )
                np.testing.assert_allclose(
                    actual[:, rank + 1], expected, rtol=1e-9, atol=1e-10, equal_nan=True
                )
            self.assertTrue(np.all(np.isnan(actual[120:130, 2:])))
            self.assertTrue(np.all(np.isnan(actual[140:144, 2:])))
            command[1] = "score"
            subprocess.run(command, check=True, capture_output=True)
            baseline = np.fromfile(root / "scores.bin", dtype="<f8").reshape(-1, 2)
            np.testing.assert_array_equal(actual[:, :2], baseline)
