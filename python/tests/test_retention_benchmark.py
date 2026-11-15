"""Causality, frozen receiver diversity, and transport conservation checks."""

from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np

from retention.codec import Sample
from retention.coverage import CoverageRecorder
from retention.downlink import LinkConfig, simulate
from retention.native_model import fit_native_model
from retention.receiver_bank import NAMES, ReceiverBank, fit_bank
from retention.recorder import Recorder, RecorderConfig
from retention.stream import read_packets


class CoverageTests(unittest.TestCase):
    def test_budget_determinism_and_context_protection(self):
        config = RecorderConfig(
            epoch_us=1000,
            budget_bytes=392,
            pre_trigger_samples=3,
            post_trigger_samples=2,
            background_fraction=0.4,
        )
        outputs = []
        for _ in range(2):
            recorder = CoverageRecorder(config, np.zeros(6), np.ones(6))
            for i in range(100):
                packet = recorder.observe(
                    Sample(i * 20, (float(i % 13),) * 6), 10 if i % 17 == 0 else 0
                )
                if packet:
                    self.assertLessEqual(len(packet.encode()), config.budget_bytes)
            packet = recorder.finish()
            self.assertLessEqual(len(packet.encode()), config.budget_bytes)
            outputs.append(packet.encode())
        self.assertEqual(*outputs)

    def test_future_epoch_cannot_change_finalized_packet_and_bad_scale_rejected(self):
        outputs = []
        for future in (0.0, 1000.0):
            recorder = CoverageRecorder(
                RecorderConfig(epoch_us=100, budget_bytes=392), np.zeros(6), np.ones(6)
            )
            for i in range(10):
                recorder.observe(Sample(i * 10, (float(i),) * 6), 0)
            outputs.append(
                recorder.observe(Sample(100, (future,) * 6), future).encode()
            )
        self.assertEqual(*outputs)
        with self.assertRaises(ValueError):
            CoverageRecorder(RecorderConfig(), np.zeros(6), np.zeros(6))


class ReceiverBankTests(unittest.TestCase):
    def test_training_only_calibration_and_original_receiver_identity(self):
        times = np.arange(100, dtype=np.int64) * 1000000
        values = np.random.default_rng(10).normal(size=(100, 6)).astype("<f4")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = fit_native_model(
                times, values, [], 60000000, root / "original.npy"
            )
            first = root / "first"
            first.mkdir()
            bank = fit_bank(times, values, [], original, first)
            values[60:] = 1e10
            second = root / "second"
            second.mkdir()
            changed = fit_bank(times, values, [], original, second)
            np.testing.assert_array_equal(bank.thresholds, changed.thresholds)
            np.testing.assert_array_equal(bank.basis, changed.basis)
            np.testing.assert_array_equal(
                bank.scores(values)[:, [0, 3]], original.scores(values)
            )
            self.assertEqual(
                ReceiverBank.from_dict(bank.to_dict()).to_dict(), bank.to_dict()
            )
            self.assertEqual(len(NAMES), 6)


class DownlinkTests(unittest.TestCase):
    def source(self, root, count=4):
        recorder = Recorder("uniform", RecorderConfig(epoch_us=100, budget_bytes=140))
        path = root / "capture.taers"
        with path.open("wb") as stream:
            for i in range(count):
                packet = recorder.observe(Sample(i * 100, (float(i),) * 6))
                if packet:
                    stream.write(packet.encode())
            stream.write(recorder.finish().encode())
        return path

    def test_no_loss_identity_and_contact_boundary_arrival_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            link = LinkConfig(contact_interval_us=100, wire_bytes_per_contact=1000)
            report = simulate(source, root / "delivered", link, 0, 400)
            self.assertEqual(source.read_bytes(), (root / "delivered").read_bytes())
            self.assertEqual(report["delivered_at_us"]["0"], 100)
            self.assertEqual(report["packets"]["delivered"], 4)
            self.assertEqual(
                report["bytes"]["transmitted_wire_bytes"], 4 * link.wire_size(68)
            )
            with self.assertRaises(ValueError):
                simulate(source, source, link, 0, 400)

    def test_fragmentation_pending_loss_and_eviction_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            partial = simulate(
                source,
                root / "partial",
                LinkConfig(
                    contact_interval_us=100,
                    wire_bytes_per_contact=40,
                    buffer_bytes=1000,
                ),
                0,
                400,
            )
            self.assertEqual(partial["packets"]["delivered"], 1)
            self.assertEqual(partial["packets"]["pending"], 3)
            self.assertEqual(partial["bytes"]["transmitted_wire_bytes"], 160)
            lost = simulate(
                source,
                root / "lost",
                LinkConfig(contact_interval_us=100, loss_probability=1),
                0,
                400,
            )
            self.assertEqual(lost["packets"]["lost"], 4)
            self.assertEqual((root / "lost").read_bytes(), b"")
            for policy in ("drop_oldest", "drop_newest"):
                report = simulate(
                    source,
                    root / policy,
                    LinkConfig(
                        contact_interval_us=400, buffer_bytes=136, eviction=policy
                    ),
                    0,
                    400,
                )
                self.assertEqual(report["packets"]["delivered"], 2)
                self.assertLessEqual(
                    report["bytes"]["maximum_buffer_payload_bytes"], 136
                )
                packets = list(read_packets(io.BytesIO((root / policy).read_bytes())))
                self.assertEqual(
                    [p.start_us for p in packets],
                    [200, 300] if policy == "drop_oldest" else [0, 100],
                )

    def test_oversized_packet_rejected_and_invalid_link_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root)
            report = simulate(
                source, root / "tiny", LinkConfig(buffer_bytes=32), 0, 400
            )
            self.assertEqual(report["packets"]["rejected"], 4)
        for changes in (
            dict(buffer_bytes=0),
            dict(loss_probability=float("nan")),
            dict(seed=-1),
            dict(eviction="random"),
        ):
            with self.assertRaises(ValueError):
                replace(LinkConfig(), **changes)


class BenchmarkIntegrationTests(unittest.TestCase):
    def test_complete_mismatch_matrix_reuses_reference_and_reports_delivery(self):
        import json
        from unittest.mock import patch
        from dataset import sha256
        from run_retention_pilot import run_pilot
        from run_retention_randomized import run_study as randomized_study
        from run_retention_benchmark import run_study
        from write_binary import Header

        times = np.arange(60, dtype="<i8") * 1000000
        values = np.random.default_rng(7).normal(size=(60, 6)).astype("<f4")
        header = Header(0, 60, 20000000, 40000000)
        events = [
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
            np.save(cache / "timestamps.npy", times)
            np.save(cache / "values.npy", values)
            manifest = dict(
                files={
                    name: sha256(cache / name)
                    for name in ("timestamps.npy", "values.npy")
                }
            )
            with patch(
                "run_retention_pilot.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_pilot.open_native_source",
                return_value=(times, values, manifest),
            ):
                reference = run_pilot(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    20000000,
                    40000000,
                    (256,),
                    epoch_us=10000000,
                )
            with patch(
                "run_retention_randomized.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_randomized.open_native_source",
                return_value=(times, values, manifest),
            ):
                randomized_study(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    root / "randomized",
                    seeds=(0,),
                    workers=1,
                )
            with patch(
                "run_retention_benchmark.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_benchmark.open_native_source",
                return_value=(times, values, manifest),
            ), patch(
                "run_retention_benchmark.SCENARIOS",
                {"ample": LinkConfig(contact_interval_us=10000000)},
            ):
                report = run_study(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    root / "randomized",
                    root / "benchmark",
                    seeds=(0,),
                    workers=1,
                )
            self.assertEqual(len(report["arms"]), 15)
            original = report["arms"]["256-difference-adaptive"]
            self.assertEqual(
                original["serialized_bytes"],
                reference["arms"]["256-adaptive"]["serialized_bytes"],
            )
            self.assertEqual(
                original["receivers"]["pca_3"]["retained_events"],
                reference["arms"]["256-adaptive"]["receivers"]["pca"][
                    "detected_events"
                ],
            )
            self.assertEqual(
                original["delivery"]["ample"]["evidence"]["serialized_bytes"],
                original["serialized_bytes"],
            )
            for arm in report["arms"].values():
                self.assertEqual(arm["source_eligible_events"], 1)
                for receiver in arm["receivers"].values():
                    self.assertLessEqual(
                        receiver["retained_events"], receiver["full_archive_events"]
                    )
            json.dumps(report, allow_nan=False)
            from run_retention_sequence import run_study as sequence_study
            from run_retention_bursts import run_study as burst_study

            with patch(
                "run_retention_sequence.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_sequence.open_native_source",
                return_value=(times, values, manifest),
            ):
                temporal = sequence_study(
                    root / "source",
                    dataset,
                    cache,
                    root / "benchmark",
                    root / "baseline",
                    root / "sequence",
                )
            self.assertEqual(len(temporal["arms"]), 7)
            with patch(
                "run_retention_bursts.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_bursts.open_native_source",
                return_value=(times, values, manifest),
            ):
                bursts = burst_study(
                    root / "source",
                    dataset,
                    cache,
                    root / "baseline",
                    root / "benchmark",
                    root / "sequence",
                    root / "bursts",
                )
            self.assertEqual(len(bursts["arms"]), 2)
            for metrics in bursts["arms"].values():
                self.assertLessEqual(metrics["maximum_packet_bytes"], 256)
                self.assertEqual(metrics["forecast"]["source_eligible_events"], 1)


class ExternalBenchmarkTests(unittest.TestCase):
    def test_prepare_freeze_and_run_with_all_arms_and_settings_tamper_rejection(self):
        import json
        from unittest.mock import patch
        from prepare_retention_bundle import prepare
        from run_retention_bundle_benchmark import (
            freeze,
            run_study,
            capture_external,
            read_events,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            np.save(source / "timestamps.npy", np.arange(60, dtype="<i8") * 1000000)
            np.save(
                source / "values.npy",
                np.random.default_rng(16).normal(size=(60, 6)).astype("<f4"),
            )
            (source / "training.json").write_text("[]")
            (source / "evaluation.json").write_text(
                json.dumps(
                    [
                        dict(
                            event_id="event",
                            category="Anomaly",
                            channel=41,
                            start_us=25000000,
                            end_us=27000000,
                        )
                    ]
                )
            )
            bundle = root / "bundle"
            manifest = prepare(
                source / "timestamps.npy",
                source / "values.npy",
                source / "training.json",
                source / "evaluation.json",
                bundle,
                mission="Synthetic independent mission",
                channels=list("abcdef"),
                training_end_us=20000000,
                evaluation_start_us=20000000,
                evaluation_end_us=40000000,
                rationale="Synthetic software test; fixed seeded channels and chronological split",
            )
            self.assertEqual(manifest["channels"], list("abcdef"))
            settings = json.loads(
                (
                    Path(__file__).resolve().parents[2]
                    / "protocols/cross-mission-v1.json"
                ).read_text()
            )
            settings.update(epoch_us=10000000, budgets=[256], seeds=[0])
            settings_path = root / "settings.json"
            settings_path.write_text(json.dumps(settings))
            lock_path = root / "protocol.json"
            freeze(bundle, settings_path, lock_path)
            captured = []

            def checked_events(path, start, end):
                if path.name == "evaluation_events.json":
                    self.assertTrue(captured, "Evaluation labels opened before capture")
                return read_events(path, start, end)

            def checked_capture(task):
                result = capture_external(task)
                captured.append(True)
                return result

            with patch(
                "run_retention_bundle_benchmark.capture_external",
                side_effect=checked_capture,
            ), patch(
                "run_retention_bundle_benchmark.read_events", side_effect=checked_events
            ):
                report = run_study(bundle, lock_path, root / "results", workers=1)
            self.assertEqual(len(report["arms"]), 19)
            from run_retention_sequence import run_bundle_study

            temporal = run_bundle_study(bundle, root / "results", root / "temporal")
            self.assertEqual(len(temporal["arms"]), 9)
            self.assertEqual(report["receivers"]["original"]["training_count"], 20)
            self.assertTrue(
                all(
                    arm["source_eligible_events"] == 1
                    for arm in report["arms"].values()
                )
            )
            lock = json.loads(lock_path.read_text())
            lock["settings"]["threshold"] += 1
            lock_path.write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, "frozen digest"):
                run_study(bundle, lock_path, root / "rejected", workers=1)
            with self.assertRaisesRegex(ValueError, "empty bundle"):
                prepare(
                    source / "timestamps.npy",
                    source / "values.npy",
                    source / "training.json",
                    source / "evaluation.json",
                    bundle,
                    mission="Another",
                    channels=list("abcdef"),
                    training_end_us=20000000,
                    evaluation_start_us=20000000,
                    evaluation_end_us=40000000,
                    rationale="Test",
                )

    def test_host_profile_has_reproducible_bytes_without_performance_assertions(self):
        from profile_retention import profile

        report = profile(1000)
        self.assertEqual(len(report["results"]), 7)
        for measured in report["results"].values():
            self.assertLessEqual(measured["maximum_packet_bytes"], 1024)
            self.assertGreater(measured["python_traced_peak_bytes"], 0)
            self.assertGreater(measured["samples_per_second"], 0)


class ForecastTests(unittest.TestCase):
    def test_training_only_fit_gap_resets_and_no_missing_predecessor_credit(self):
        from retention.forecast import fit_forecast, pair_evidence

        times = np.arange(100, dtype="<i8") * 1000000
        values = np.random.default_rng(32).normal(size=(100, 6)).astype("<f4")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normalizer = fit_native_model(
                times, values, [], 60000000, root / "base.npy"
            )
            model = fit_forecast(times, values, [], normalizer, root)
            self.assertEqual(model.training_pairs, 59)
            values[60:] = 1e10
            second = root / "second"
            second.mkdir()
            changed = fit_forecast(times, values, [], normalizer, second)
            np.testing.assert_array_equal(model.coefficients, changed.coefficients)
            self.assertEqual(model.threshold, changed.threshold)
            gap_times = times.copy()
            gap_times[50:] += 200000000
            score = model.scores(gap_times, values)
            self.assertTrue(np.isnan(score[0]))
            self.assertTrue(np.isnan(score[50]))
            self.assertTrue(np.isfinite(score[51]))
        np.testing.assert_array_equal(
            pair_evidence([True, False, True], [True] * 3), [False] * 3
        )
        np.testing.assert_array_equal(
            pair_evidence([True, True, False], [True] * 3), [False, True, False]
        )


class BurstTests(unittest.TestCase):
    def test_background_pairs_obey_quota_gap_and_epoch_boundaries(self):
        from retention.burst import BurstRecorder

        config = RecorderConfig(
            epoch_us=1000, budget_bytes=392, background_fraction=0.4
        )
        recorder = BurstRecorder(config, reset_gap_us=20)
        for time_us in (0, 10, 20, 30, 500, 600, 610, 620):
            recorder.observe(Sample(time_us, (float(time_us),) * 6))
        packet = recorder.finish()
        self.assertEqual(
            [r.sample.timestamp_us for r in packet.records], [0, 10, 600, 610]
        )
        self.assertLessEqual(len(packet.encode()), config.budget_bytes)
        # An unmatched observation at epoch end cannot borrow a partner from the next epoch.
        recorder = BurstRecorder(config)
        recorder.observe(Sample(999, (0.0,) * 6))
        previous = recorder.observe(Sample(1000, (1.0,) * 6))
        self.assertEqual(len(previous.records), 0)

    def test_trigger_overlap_is_deduplicated_and_continuous_triggers_remain_bounded(
        self,
    ):
        from retention.burst import BurstRecorder

        for background in (0.0, 0.2, 0.5, 1.0):
            config = RecorderConfig(
                epoch_us=1000, budget_bytes=392, background_fraction=background
            )
            recorder = BurstRecorder(config)
            for i in range(100):
                recorder.observe(Sample(i * 10, (float(i),) * 6), 100)
            packet = recorder.finish()
            self.assertLessEqual(len(packet.encode()), config.budget_bytes)
            self.assertEqual(
                len({r.sample.timestamp_us for r in packet.records}),
                len(packet.records),
            )
