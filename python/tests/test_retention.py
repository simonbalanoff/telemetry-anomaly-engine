"""Wire budgets, causality, blind-spot coverage, and pre-trigger retention."""

from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from retention.codec import (
    HEADER,
    RAW_BYTES,
    SUMMARY_BYTES,
    Packet,
    RawRecord,
    Sample,
    SummaryRecord,
    decode_packet,
)
from retention.recorder import Reason, Recorder, RecorderConfig
from run_retention_demo import run_demo


def sample(index, value=0):
    return Sample(index * 1_000_000, (value,) * 6)


class PacketTests(unittest.TestCase):
    def test_exact_costs_and_roundtrip(self):
        self.assertEqual((HEADER.size, RAW_BYTES, SUMMARY_BYTES), (32, 36, 64))
        raw = RawRecord(sample(1, 0.1), int(Reason.TRIGGER))
        summary = SummaryRecord(0, (0.0,) * 6, (1.0,) * 6, 5)
        packet = Packet(0, 10_000_000, 132, (raw, summary))
        self.assertEqual(len(packet.encode()), 132)
        self.assertEqual(decode_packet(packet.encode()), packet)
        with self.assertRaisesRegex(ValueError, "budget"):
            replace(packet, budget_bytes=131).encode()

    def test_rejects_truncation_mutations_and_duplicate_samples(self):
        packet = Packet(0, 10_000_000, 128, (RawRecord(sample(1)),))
        encoded = packet.encode()
        for changed in [
            encoded[:20],
            encoded[:-1],
            b"BAD!" + encoded[4:],
            encoded + b"x",
        ]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                decode_packet(changed)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            replace(packet, records=packet.records * 2).encode()
        with self.assertRaisesRegex(ValueError, "outside"):
            replace(packet, records=(RawRecord(sample(20)),)).encode()
        with self.assertRaises(ValueError):
            Sample(0, (float("nan"),) * 6)
        with self.assertRaises(ValueError):
            RawRecord(sample(1), 128).encode()


class RecorderTests(unittest.TestCase):
    def config(self, **changes):
        return replace(
            RecorderConfig(
                epoch_us=100_000_000,
                budget_bytes=392,
                pre_trigger_samples=3,
                post_trigger_samples=2,
            ),
            **changes,
        )

    def test_pre_trigger_context_and_reserved_background_quota(self):
        recorder = Recorder("adaptive", self.config())
        for index in range(100):
            recorder.observe(sample(index), 10 if index == 10 else 0)
        packet = recorder.finish()
        reasons = {
            record.sample.timestamp_us // 1_000_000: record.reason
            for record in packet.records
        }
        for index in [7, 8, 9]:
            self.assertEqual(reasons[index], Reason.PRE_TRIGGER)
        self.assertEqual(reasons[10], Reason.TRIGGER)
        self.assertEqual(reasons[11], Reason.POST_TRIGGER)
        self.assertEqual(reasons[12], Reason.POST_TRIGGER)
        self.assertEqual(reasons[0], Reason.BACKGROUND)
        self.assertEqual(reasons[50], Reason.BACKGROUND)
        self.assertLessEqual(len(packet.encode()), 392)

    def test_continuous_triggers_cannot_spend_background_reservation(self):
        recorder = Recorder("adaptive", self.config())
        for index in range(100):
            recorder.observe(sample(index), 10)
        packet = recorder.finish()
        background = [
            record for record in packet.records if record.reason == Reason.BACKGROUND
        ]
        self.assertEqual(
            [record.sample.timestamp_us for record in background], [0, 50_000_000]
        )
        self.assertLessEqual(len(packet.records), 10)

    def test_causal_prefix_and_epoch_reset(self):
        def replay(suffix):
            recorder = Recorder("adaptive", self.config())
            first = None
            for index in range(120):
                value = 0 if index < 100 else suffix
                completed = recorder.observe(sample(index, value), abs(value))
                if completed is not None:
                    first = completed.encode()
            recorder.finish()
            return first

        self.assertEqual(replay(0), replay(100))
        recorder = Recorder("threshold", self.config())
        recorder.observe(sample(0), 10)
        recorder.finish()
        with self.assertRaisesRegex(ValueError, "reopen"):
            recorder.observe(sample(1), 10)

    def test_each_policy_is_bounded_on_irregular_multiepoch_input(self):
        generator = random.Random(2026)
        for policy in Recorder.POLICIES:
            recorder = Recorder(policy, self.config(budget_bytes=256))
            packets = []
            timestamp = 0
            for _ in range(3000):
                timestamp += generator.randrange(1, 2000000)
                completed = recorder.observe(
                    Sample(timestamp, (1.0,) * 6), generator.random() * 10
                )
                if completed is not None:
                    packets.append(completed)
            packets.append(recorder.finish())
            for packet in packets:
                self.assertLessEqual(len(packet.encode()), 256)
                self.assertEqual(decode_packet(packet.encode()), packet)

    def test_empty_stream_zero_background_and_invalid_input(self):
        recorder = Recorder("adaptive", self.config(background_fraction=0))
        self.assertIsNone(recorder.finish())
        recorder.observe(sample(1), 0)
        with self.assertRaises(ValueError):
            recorder.observe(sample(1), 0)
        with self.assertRaises(ValueError):
            recorder.observe(sample(2), float("nan"))
        self.assertEqual(len(recorder.finish().records), 0)
        for changes in [
            dict(budget_bytes=50),
            dict(background_fraction=1.1),
            dict(pre_trigger_samples=-1),
        ]:
            with self.assertRaises(ValueError):
                self.config(**changes)


class RetentionDemoTests(unittest.TestCase):
    def test_reproducible_artifacts_and_actual_serialized_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_demo(root / "run", root / "table.tex")
            repeated = run_demo(root / "repeat")
            self.assertEqual(report, repeated)
            self.assertIn("Generated", (root / "table.tex").read_text())
            for policy, metrics in report["policies"].items():
                sizes = [
                    path.stat().st_size
                    for path in (root / "run").glob(f"{policy}-*.taer")
                ]
                self.assertEqual(sum(sizes), metrics["serialized_bytes"])
                self.assertTrue(
                    all(size <= report["config"]["budget_bytes"] for size in sizes)
                )
            json.dumps(report, allow_nan=False)
