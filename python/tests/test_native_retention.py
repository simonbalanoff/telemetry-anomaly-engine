"""Native parity, leakage isolation, fixed denominators, and real replay integration."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from preprocess import iter_grid_frames
from retention.codec import Packet, RawRecord, Sample, SummaryRecord
from retention.native_metrics import build_event_cases, evaluate_stream
from retention.native_model import (
    NativeModel,
    annotation_mask,
    causal_capture_scores,
    fit_native_model,
)
from retention.native_source import verify_native_against_grid
from retention.recorder import RecorderConfig
from retention.stream import read_packets
from run_retention_pilot import run_pilot, write_latex
from write_binary import Header, PERIOD_US, write_binary


class PacketStreamTests(unittest.TestCase):
    def test_concatenation_and_malformed_streams(self):
        first = Packet(0, 10, 128, (RawRecord(Sample(1, (1.0,) * 6)),)).encode()
        second = Packet(10, 10, 128, (RawRecord(Sample(11, (2.0,) * 6)),)).encode()
        self.assertEqual(len(list(read_packets(BytesIO(first + second)))), 2)
        for broken in [first + first, first + second[:-1], first + b"x"]:
            with self.assertRaises(ValueError):
                list(read_packets(BytesIO(broken)))


class NativeSourceTests(unittest.TestCase):
    def test_native_collision_samples_are_not_discarded_by_parity_check(self):
        timestamps = np.array([0, 10000000, 30000000, 90000000], dtype=np.int64)
        values = np.zeros((4, 6), dtype=np.float32)
        values[0, 0] = 9  # This raw excursion precedes the retained zero in its cell.
        header = Header(0, 4, PERIOD_US, 2 * PERIOD_US)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "telemetry.bin"
            write_binary(binary, header, iter_grid_frames(timestamps, values))
            verify_native_against_grid(timestamps, values, header, binary)
            self.assertEqual(len(timestamps), 4)
            changed = values.copy()
            changed[1, 0] = 1
            with self.assertRaisesRegex(ValueError, "keep-last"):
                verify_native_against_grid(timestamps, changed, header, binary)


class NativeModelTests(unittest.TestCase):
    def test_training_statistics_exclusions_and_future_mutation(self):
        generator = np.random.default_rng(4)
        timestamps = np.arange(100, dtype=np.int64)
        values = generator.normal(size=(100, 6)).astype(np.float32)
        values[20] = 1e6
        events = [dict(category="Anomaly", start_us=20, end_us=20)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = fit_native_model(
                timestamps, values, events, 60, root / "first.npy"
            )
            expected = values[:60][~annotation_mask(timestamps[:60], events)].astype(
                float
            )
            np.testing.assert_allclose(actual.mean, expected.mean(axis=0), atol=1e-12)
            np.testing.assert_allclose(
                actual.sigma, expected.std(axis=0, ddof=1), atol=1e-12
            )
            np.testing.assert_allclose(
                actual.thresholds,
                np.quantile(actual.scores(expected), 0.999, axis=0),
                atol=1e-12,
            )
            values[60:] = 1e20
            changed = fit_native_model(
                timestamps,
                values,
                events + [dict(category="Rare Event", start_us=80, end_us=90)],
                60,
                root / "changed.npy",
            )
            self.assertEqual(actual.to_dict(), changed.to_dict())
            self.assertEqual(actual.training_count, 59)

    def test_capture_is_causal_and_resets_across_long_gaps(self):
        times = np.array([0, 1, 200000000, 200000001])
        values = np.array([[0] * 6, [1] * 6, [10] * 6, [11] * 6], dtype=float)
        actual = causal_capture_scores(times, values, np.ones(6))
        np.testing.assert_array_equal(actual, [0, 1, 0, 1])
        values[-1] = 100
        np.testing.assert_array_equal(
            causal_capture_scores(times, values, np.ones(6))[:3], actual[:3]
        )


class NativeMetricTests(unittest.TestCase):
    def fixture(self):
        times = np.arange(5, dtype=np.int64)
        values = np.zeros((5, 6), dtype=np.float32)
        values[2, 4] = 5
        model = NativeModel(
            np.zeros(6), np.ones(6), np.eye(6)[:, :3], np.array([2.0, 0.2]), 2, 0, 0.999
        )
        events = [
            dict(event_id="point", category="Anomaly", channel=45, start_us=2, end_us=2)
        ]
        cases, _, normal = build_event_cases(times, events, 0, 5, 2)
        return times, values, model, cases, normal

    def test_dropped_event_remains_a_miss_in_fixed_denominator(self):
        times, values, model, cases, normal = self.fixture()
        config = RecorderConfig(epoch_us=5, budget_bytes=128)
        packet = Packet(0, 5, 128, (RawRecord(Sample(1, tuple(values[1]))),))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.taers"
            path.write_bytes(packet.encode())
            report = evaluate_stream(
                path, times, values, model, cases, normal, config, 0, 5
            )
            self.assertEqual(report["source_eligible_events"], 1)
            self.assertEqual(report["receivers"]["pca"]["evidence_recall"], 0)
            self.assertEqual(report["events"][0]["sample_coverage"], 0)

    def test_summary_evidence_is_separate_from_raw_receiver_recall(self):
        times, values, model, cases, normal = self.fixture()
        config = RecorderConfig(epoch_us=5, budget_bytes=96)
        packet = Packet(
            0,
            5,
            96,
            (
                SummaryRecord(
                    0, tuple(values.min(axis=0)), tuple(values.max(axis=0)), 5
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.taers"
            path.write_bytes(packet.encode())
            report = evaluate_stream(
                path, times, values, model, cases, normal, config, 0, 5
            )
            self.assertFalse(report["receivers"]["pca"]["supported"])
            self.assertIsNone(report["receivers"]["pca"]["evidence_recall"])
            self.assertEqual(report["coarse_summary"]["overlap_events"], 1)
            self.assertEqual(report["events_with_raw_evidence"], 0)


class NativePilotIntegrationTests(unittest.TestCase):
    def test_complete_replay_and_test_partition_isolation(self):
        generator = np.random.default_rng(2026)
        timestamps = np.arange(60, dtype=np.int64) * 1000000
        values = generator.normal(size=(60, 6)).astype(np.float32)
        header = Header(0, 60, 20000000, 40000000)
        events = [
            dict(
                event_id="anomaly",
                category="Anomaly",
                channel=41,
                start_us=25000000,
                end_us=27000000,
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset, cache = root / "dataset", root / "cache"
            dataset.mkdir()
            cache.mkdir()
            (dataset / "manifest.json").write_text("{}")
            (cache / "manifest.json").write_text("{}")
            manifest = dict(
                files={"timestamps.npy": "fixture", "values.npy": "fixture"}
            )
            with patch(
                "run_retention_pilot.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_pilot.open_native_source",
                return_value=(timestamps, values, manifest),
            ):
                report = run_pilot(
                    root / "source",
                    dataset,
                    cache,
                    root / "first",
                    20000000,
                    40000000,
                    (256, 512),
                    epoch_us=10000000,
                )
                values[40:] = 1e20
                repeated = run_pilot(
                    root / "source",
                    dataset,
                    cache,
                    root / "second",
                    20000000,
                    40000000,
                    (256, 512),
                    epoch_us=10000000,
                )
            self.assertEqual(report["model"], repeated["model"])
            self.assertEqual(report["arms"], repeated["arms"])
            self.assertEqual(len(report["arms"]), 8)
            for metrics in report["arms"].values():
                self.assertEqual(metrics["packets"], 2)
                self.assertLessEqual(
                    metrics["maximum_packet_bytes"], metrics["config"]["budget_bytes"]
                )
            write_latex(report, root / "results.tex")
            self.assertIn("Uniform", (root / "results.tex").read_text())
            json.dumps(report, allow_nan=False)
            with patch(
                "run_retention_pilot.verify_dataset", return_value=(header, events)
            ), self.assertRaisesRegex(ValueError, "validation"):
                run_pilot(
                    root / "source",
                    dataset,
                    cache,
                    root / "invalid",
                    40000000,
                    50000000,
                )
