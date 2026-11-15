"""Protocol immutability, split isolation, and decoded cross-mission execution."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from dataset import sha256
from retention.mission import BUNDLE_FILES, open_bundle, read_events
from retention.recorder import Reason, Recorder, RecorderConfig
from retention.codec import Sample
from run_retention_ablations import ablation_configs, run_study as run_ablations
from run_retention_transfer import freeze, run_study, capture
from run_retention_pilot import run_pilot
from write_binary import Header


def write_bundle(root):
    root.mkdir()
    times = np.arange(60, dtype="<i8") * 1000000
    values = np.random.default_rng(19).normal(size=(60, 6)).astype("<f4")
    np.save(root / "timestamps.npy", times)
    np.save(root / "values.npy", values)
    (root / "training_events.json").write_text("[]")
    (root / "evaluation_events.json").write_text(
        json.dumps(
            [
                dict(
                    event_id="fault",
                    category="Anomaly",
                    channel=41,
                    start_us=25000000,
                    end_us=28000000,
                )
            ]
        )
    )
    manifest = dict(
        format="TAE-MISSION",
        version=1,
        mission="Synthetic mission B",
        channels=[f"sensor-{i}" for i in range(6)],
        observation_semantics="synchronized-native-no-fill",
        training_end_us=20000000,
        evaluation_start_us=20000000,
        evaluation_end_us=40000000,
        files={name: sha256(root / name) for name in BUNDLE_FILES},
    )
    (root / "manifest.json").write_text(json.dumps(manifest))
    return times, values, manifest


def write_settings(root):
    settings = json.loads(
        (
            Path(__file__).resolve().parents[2] / "protocols/cross-mission-v1.json"
        ).read_text()
    )
    settings.update(epoch_us=10000000, budgets=[256], seeds=[0, 1])
    path = root / "settings.json"
    path.write_text(json.dumps(settings))
    return path


class AblationTests(unittest.TestCase):
    def test_component_removals_change_actual_retained_reasons(self):
        config = RecorderConfig(
            epoch_us=100000000,
            budget_bytes=1024,
            pre_trigger_samples=3,
            post_trigger_samples=2,
        )
        for name, variant in ablation_configs(config).items():
            recorder = Recorder("adaptive", variant)
            for i in range(100):
                recorder.observe(
                    Sample(i * 1000000, (float(i),) * 6), 10 if i == 10 else 0
                )
            packet = recorder.finish()
            reasons = {r.reason for r in packet.records}
            removed = {
                "no_pre": Reason.PRE_TRIGGER,
                "no_post": Reason.POST_TRIGGER,
                "no_background": Reason.BACKGROUND,
            }
            if name in removed:
                self.assertNotIn(removed[name], reasons)
            else:
                self.assertTrue(set(removed.values()) <= reasons)
            self.assertLessEqual(len(packet.encode()), variant.budget_bytes)

    def test_paired_sweep_reproduces_reference_full_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            times, values, _ = write_bundle(root / "bundle")
            bundle = root / "bundle"
            header = Header(0, 60, 20000000, 40000000)
            events = read_events(bundle / "evaluation_events.json", 20000000, 40000000)
            manifest = dict(
                files={
                    name: sha256(bundle / name)
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
                    bundle,
                    bundle,
                    root / "baseline",
                    20000000,
                    40000000,
                    budgets=(256,),
                    epoch_us=10000000,
                )
            with patch(
                "run_retention_ablations.verify_dataset", return_value=(header, events)
            ), patch(
                "run_retention_ablations.open_native_source",
                return_value=(times, values, manifest),
            ):
                report = run_ablations(
                    root / "source",
                    bundle,
                    bundle,
                    root / "baseline",
                    root / "ablations",
                )
            self.assertEqual(report["model"], reference["model"])
            self.assertEqual(len(report["arms"]), 4)
            self.assertEqual(
                report["arms"]["256-full"]["packet_stream_sha256"],
                reference["arms"]["256-adaptive"]["packet_stream_sha256"],
            )


class TransferTests(unittest.TestCase):
    def test_frozen_end_to_end_and_evaluation_labels_do_not_affect_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, manifest = write_bundle(root / "bundle")
            bundle = root / "bundle"
            settings = write_settings(root)
            lock = root / "lock.json"
            freeze(bundle, settings, lock)
            observed = []
            original_read = read_events

            def guarded_read(path, start, end):
                if path.name == "evaluation_events.json":
                    self.assertTrue(
                        observed,
                        "Evaluation labels were parsed before capture completed",
                    )
                return original_read(path, start, end)

            def observed_capture(*args):
                result = capture(*args)
                observed.append(True)
                return result

            with patch(
                "run_retention_transfer.read_events", side_effect=guarded_read
            ), patch("run_retention_transfer.capture", side_effect=observed_capture):
                report = run_study(bundle, lock, root / "first")
            self.assertEqual(report["model"]["training_count"], 20)
            self.assertEqual(report["model"]["training_end_us"], 20000000)
            self.assertEqual(len(report["arms"]), 11)
            self.assertEqual(report["full_archive"]["source_eligible_events"], 1)
            self.assertEqual(
                report["event_characteristics"]["fault"]["duration_group"], "up_to_60s"
            )
            self.assertEqual(
                report["arms"]["256-adaptive"]["strata"]["duration_group:up_to_60s"][
                    "source_eligible_events"
                ],
                1,
            )
            for metrics in report["arms"].values():
                self.assertLessEqual(metrics["maximum_packet_bytes"], 256)
                self.assertEqual(metrics["source_eligible_events"], 1)
                self.assertEqual(metrics["packets"], 2)
            (bundle / "evaluation_events.json").write_text("[]")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                run_study(bundle, lock, root / "rejected")
            manifest["files"]["evaluation_events.json"] = sha256(
                bundle / "evaluation_events.json"
            )
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "manifest differs"):
                run_study(bundle, lock, root / "rejected")
            # Explicitly create a second protocol, changing labels only, and compare packets/model.
            freeze(bundle, settings, root / "second-lock.json")
            second = run_study(bundle, root / "second-lock.json", root / "second")
            self.assertEqual(second["model"], report["model"])
            for name in report["arms"]:
                self.assertEqual(
                    second["arms"][name]["packet_stream_sha256"],
                    report["arms"][name]["packet_stream_sha256"],
                )
            with self.assertRaisesRegex(ValueError, "already exists"):
                freeze(bundle, settings, lock)
            with patch("run_retention_transfer.code_hashes", return_value={}):
                with self.assertRaisesRegex(ValueError, "Code differs"):
                    run_study(bundle, root / "second-lock.json", root / "bad-code")

    def test_bundle_rejects_filled_data_bad_order_and_training_label_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            times, _, manifest = write_bundle(root / "bundle")
            bundle = root / "bundle"
            manifest["observation_semantics"] = "forward-filled"
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "original observations"):
                open_bundle(bundle)
            manifest["observation_semantics"] = "synchronized-native-no-fill"
            times[5] = times[4]
            np.save(bundle / "timestamps.npy", times)
            manifest["files"]["timestamps.npy"] = sha256(bundle / "timestamps.npy")
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                open_bundle(bundle)
            with self.assertRaisesRegex(ValueError, "outside"):
                read_events(bundle / "evaluation_events.json", 0, 20000000)

    def test_freeze_rejects_development_mission_and_misaligned_epochs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, manifest = write_bundle(root / "bundle")
            bundle = root / "bundle"
            settings = write_settings(root)
            manifest["mission"] = "ESA-Mission1"
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "different mission"):
                freeze(bundle, settings, root / "lock.json")
            manifest["mission"] = "Synthetic mission B"
            manifest["evaluation_end_us"] += 1
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "complete epochs"):
                freeze(bundle, settings, root / "lock.json")
