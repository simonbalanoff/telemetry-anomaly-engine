"""Seed reproducibility, uniform reservoir inclusion, causality, and frozen-study integration."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from dataset import sha256
from retention.codec import Sample, decode_packet
from retention.randomized import RANDOMIZED_POLICIES, RandomizedRecorder
from retention.recorder import RecorderConfig
from run_retention_pilot import run_pilot
from run_retention_randomized import run_study, validate_reference, write_latex
from write_binary import Header


def replay(policy, seed, count=100, scores=0, start=0):
    config = RecorderConfig(epoch_us=1000, budget_bytes=140)
    recorder = RandomizedRecorder(policy, config, seed)
    for index in range(count):
        recorder.observe(Sample(start + index * 10, (float(index),) * 6), scores)
    return recorder.finish()


class RandomizedRecorderTests(unittest.TestCase):
    def test_seed_reproducibility_and_score_independence(self):
        for policy in RANDOMIZED_POLICIES:
            first = replay(policy, 4)
            self.assertEqual(first.encode(), replay(policy, 4, scores=1000).encode())
            self.assertNotEqual(first.encode(), replay(policy, 5).encode())
            self.assertEqual(decode_packet(first.encode()), first)
            self.assertLessEqual(len(first.encode()), 140)

    def test_reservoir_fills_capacity_without_replacement_and_handles_short_epochs(
        self,
    ):
        packet = replay("reservoir", 2026)
        self.assertEqual(len(packet.records), 3)
        self.assertEqual(
            len({record.sample.timestamp_us for record in packet.records}), 3
        )
        self.assertEqual(len(replay("reservoir", 2026, count=2).records), 2)

    def test_reservoir_inclusion_has_no_early_or_late_position_bias(self):
        counts = np.zeros(20, dtype=int)
        for seed in range(2000):
            packet = replay("reservoir", seed, count=20)
            for record in packet.records:
                counts[record.sample.timestamp_us // 10] += 1
        # Expected inclusion is K/N=3/20. Wide deterministic bounds detect a broken
        # replacement rule without treating this test as a scientific estimate.
        self.assertTrue(np.all((counts > 180) & (counts < 420)), counts)
        self.assertEqual(int(counts.sum()), 6000)

    def test_epoch_randomness_is_independent_of_skipped_earlier_epochs(self):
        config = RecorderConfig(epoch_us=1000, budget_bytes=140)
        for policy in RANDOMIZED_POLICIES:
            recorder = RandomizedRecorder(policy, config, 9)
            for index in range(100):
                recorder.observe(Sample(index * 10, (0.0,) * 6))
            for index in range(100):
                recorder.observe(Sample(2000 + index * 10, (float(index),) * 6))
            self.assertEqual(
                recorder.finish().encode(), replay(policy, 9, start=2000).encode()
            )

    def test_randomized_targets_do_not_duplicate_after_a_long_gap(self):
        recorder = RandomizedRecorder(
            "randomized_uniform", RecorderConfig(epoch_us=100, budget_bytes=392), 7
        )
        recorder.observe(Sample(0, (0.0,) * 6))
        recorder.observe(Sample(99, (1.0,) * 6))
        packet = recorder.finish()
        self.assertLessEqual(len(packet.records), 2)
        self.assertEqual(
            len({record.sample.timestamp_us for record in packet.records}),
            len(packet.records),
        )

    def test_future_epoch_changes_cannot_change_a_finalized_packet(self):
        for policy in RANDOMIZED_POLICIES:
            outputs = []
            for suffix in [0.0, 100.0]:
                recorder = RandomizedRecorder(
                    policy, RecorderConfig(epoch_us=100, budget_bytes=140), 8
                )
                for index in range(10):
                    recorder.observe(Sample(index * 10, (0.0,) * 6))
                outputs.append(recorder.observe(Sample(100, (suffix,) * 6)).encode())
            self.assertEqual(outputs[0], outputs[1])
        with self.assertRaises(ValueError):
            RandomizedRecorder("reservoir", RecorderConfig(), -1)


class SeededStudyIntegrationTests(unittest.TestCase):
    def test_serialized_seeded_sweep_reuses_frozen_models_and_reports_seed_ranges(self):
        rng = np.random.default_rng(1)
        timestamps = np.arange(60, dtype=np.int64) * 1000000
        values = rng.normal(size=(60, 6)).astype("<f4")
        header = Header(0, 60, 20000000, 40000000)
        annotations = [
            dict(
                event_id="event",
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
            np.save(cache / "timestamps.npy", timestamps)
            np.save(cache / "values.npy", values)
            manifest = dict(
                files={
                    name: sha256(cache / name)
                    for name in ["timestamps.npy", "values.npy"]
                }
            )
            with patch(
                "run_retention_pilot.verify_dataset", return_value=(header, annotations)
            ), patch(
                "run_retention_pilot.open_native_source",
                return_value=(timestamps, values, manifest),
            ):
                reference = run_pilot(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    20000000,
                    40000000,
                    (256, 512),
                    epoch_us=10000000,
                )
            with patch(
                "run_retention_randomized.verify_dataset",
                return_value=(header, annotations),
            ), patch(
                "run_retention_randomized.open_native_source",
                return_value=(timestamps, values, manifest),
            ):
                report = run_study(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    root / "study",
                    seeds=(0, 1),
                    workers=1,
                )
            self.assertEqual(report["model"], reference["model"])
            self.assertEqual(len(report["runs"]), 8)
            self.assertEqual(len(report["summary"]["groups"]), 4)
            for name, metrics in report["runs"].items():
                self.assertLessEqual(
                    metrics["maximum_packet_bytes"], int(name.split("-")[0])
                )
                self.assertEqual(metrics["source_eligible_events"], 1)
                self.assertEqual(metrics["packets"], 2)
            for group in report["summary"]["groups"].values():
                self.assertEqual(group["seeds"], 2)
                self.assertLessEqual(
                    group["pca_events"]["minimum"], group["pca_events"]["mean"]
                )
                self.assertLessEqual(
                    group["pca_events"]["mean"], group["pca_events"]["maximum"]
                )
            write_latex(report, root / "table.tex")
            self.assertIn("Reservoir", (root / "table.tex").read_text())
            json.dumps(report, allow_nan=False)
            changed = json.loads(json.dumps(reference))
            changed["model"]["mean"][0] += 1
            with self.assertRaisesRegex(ValueError, "model file"):
                validate_reference(changed, root / "baseline", dataset, cache, header)
