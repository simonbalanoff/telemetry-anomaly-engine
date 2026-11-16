"""Original-interval partitioning, committed protocols, and fixed primary analysis."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from dataset import sha256
from prepare_mission2_bundle import prepare, timestamp_us, TRAIN_END, EVAL_END, CHANNELS
from retention.partitioned_events import (
    POLICY,
    partition_rows,
    read_partition_events,
    event_reader,
    build_partition_cases,
)
from retention.mission import read_events
from retention.native_model import annotation_mask
from run_retention_bundle_benchmark import verify_committed_protocol
from summarize_independent_retention import compare


def row(event_id, start, end, channel=41, category="Anomaly"):
    return dict(
        event_id=event_id,
        start_us=start,
        end_us=end,
        channel=channel,
        category=category,
    )


class PartitionTests(unittest.TestCase):
    def test_crossing_disjoint_channel_rows_and_endpoint_points_are_censored(self):
        original = [
            row("cross", 8, 12),
            row("disjoint", 5, 8),
            row("disjoint", 12, 14, 42),
            row("endpoint", 15, 18),
            row("endpoint", 20, 20, 42),
            row("inside", 13, 17),
            row("point", 10, 10),
        ]
        rows = partition_rows(original, 10, 20)
        by_id = {item["event_id"]: item for item in rows}
        self.assertEqual(
            (by_id["cross"]["start_us"], by_id["cross"]["end_us"]), (8, 12)
        )
        self.assertTrue(by_id["disjoint"]["boundary_censored"])
        self.assertTrue(by_id["endpoint"]["boundary_censored"])
        self.assertFalse(by_id["inside"]["boundary_censored"])
        self.assertFalse(by_id["point"]["boundary_censored"])
        times = np.arange(10, 20, dtype=np.int64)
        cases, _, normal = build_partition_cases(times, rows, 10, 20, 2)
        self.assertEqual(
            {c.event_id for c in cases if not c.censored}, {"inside", "point"}
        )
        self.assertFalse(normal[0])
        training = partition_rows(original, 0, 10)
        np.testing.assert_array_equal(
            annotation_mask(np.arange(10), training)[8:], [True, True]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(rows))
            self.assertEqual(read_partition_events(path, 10, 20), rows)
            with self.assertRaises(ValueError):
                read_events(path, 10, 20)  # Legacy contract remains strict.
            rows[0]["boundary_censored"] = False
            path.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                read_partition_events(path, 10, 20)
        with self.assertRaises(ValueError):
            event_reader({"annotation_policy": "unknown"})

    def test_timestamp_precision_and_category_validation(self):
        self.assertEqual(timestamp_us("2001-10-01T00:00:00Z"), TRAIN_END)
        for text in ("2001-10-01", "2001-10-01T00:00:00.000000001Z"):
            with self.assertRaises(ValueError):
                timestamp_us(text)
        with self.assertRaises(ValueError):
            partition_rows([row("bad", 12, 11)], 0, 20)
        with self.assertRaises(ValueError):
            partition_rows(
                [row("x", 1, 2), row("x", 2, 3, category="Rare Event")], 0, 20
            )


class PreparationTests(unittest.TestCase):
    def test_fixed_converter_preserves_crossings_and_source_arrays(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, native = root / "source", root / "native"
            (source / "channels").mkdir(parents=True)
            native.mkdir()
            for name in CHANNELS:
                (source / "channels" / f"{name}.zip").write_bytes(name.encode())
            times = np.array(
                [
                    TRAIN_END - 2000000,
                    TRAIN_END - 1000000,
                    TRAIN_END,
                    TRAIN_END + 1000000,
                    EVAL_END - 1000000,
                ],
                dtype="<i8",
            )
            np.save(native / "timestamps.npy", times)
            np.save(native / "values.npy", np.arange(30, dtype="<f4").reshape(5, 6))
            provenance = dict(
                format="TAE-NATIVE-EXPORT",
                mission="ESA-Mission2",
                channels=CHANNELS,
                lossless_binary32=True,
                training_end_us=TRAIN_END,
                last_timestamp_us=int(times[-1]),
                files={
                    name: sha256(native / name)
                    for name in ("timestamps.npy", "values.npy")
                },
                source_archive_sha256={
                    name: sha256(source / "channels" / f"{name}.zip")
                    for name in CHANNELS
                },
            )
            (native / "manifest.json").write_text(json.dumps(provenance))
            (source / "anomaly_types.csv").write_text(
                "ID,Category\nx,Anomaly\ny,Anomaly\n"
            )
            (source / "labels.csv").write_text(
                "ID,Channel,StartTime,EndTime\n"
                "x,channel_86,2001-09-30T23:59:59Z,2001-10-01T00:00:01Z\n"
                "y,channel_87,2001-10-01T00:00:01Z,2001-10-01T00:00:01Z\n"
            )
            repository = Path(__file__).resolve().parents[2]
            protocol = repository / "protocols/mission2-study-v1.md"
            settings = repository / "protocols/cross-mission-v1.json"
            output = root / "bundle"
            manifest = prepare(source, native, protocol, settings, output)
            self.assertEqual(manifest["annotation_policy"], POLICY)
            self.assertEqual(
                manifest["files"]["values.npy"], provenance["files"]["values.npy"]
            )
            events = read_partition_events(
                output / "evaluation_events.json", TRAIN_END, EVAL_END
            )
            self.assertTrue(
                next(e for e in events if e["event_id"] == "x")["boundary_censored"]
            )
            cases, _, _ = build_partition_cases(
                times[2:], events, TRAIN_END, EVAL_END, 300000000
            )
            self.assertEqual(
                [case.event_id for case in cases if not case.censored], ["y"]
            )
            from dataclasses import asdict
            from retention.codec import Sample
            from retention.recorder import Recorder, RecorderConfig
            from run_retention_benchmark import evaluate_budget

            config = RecorderConfig()
            recorder = Recorder("uniform", config)
            captured = root / "captured.taers"
            values = np.load(output / "values.npy")[2:]
            with captured.open("wb") as stream:
                for stamp, vector in zip(times[2:], values):
                    packet = recorder.observe(Sample(int(stamp), tuple(vector)))
                    if packet is not None:
                        stream.write(packet.encode())
                stream.write(recorder.finish().encode())
            np.save(root / "eval-times.npy", times[2:])
            np.save(root / "eval-values.npy", values)
            np.save(root / "capture.npy", np.zeros((3, 4)))
            np.save(root / "positive.npy", np.ones((3, 6), dtype=bool))
            task = dict(
                times=str(root / "eval-times.npy"),
                values=str(root / "eval-values.npy"),
                capture_scores=str(root / "capture.npy"),
                positive=str(root / "positive.npy"),
                config=asdict(config),
                start_us=TRAIN_END,
                end_us=EVAL_END,
                context_us=300000000,
                output=str(root),
                active_epochs=2,
            )
            measured = evaluate_budget(
                (task, events, {"1024-disabled-adaptive": str(captured)})
            )
            self.assertEqual(
                measured["1024-disabled-adaptive"]["source_eligible_events"], 1
            )
            self.assertTrue(
                next(
                    r
                    for r in measured["1024-disabled-adaptive"]["events"]
                    if r["event_id"] == "x"
                )["boundary_censored"]
            )

            with self.assertRaisesRegex(ValueError, "empty"):
                prepare(source, native, protocol, settings, output)


class CommitBarrierTests(unittest.TestCase):
    def test_real_git_commit_is_required_and_dirty_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "python").mkdir()
            (root / "python/model.py").write_text("version = 1\n")
            (root / "study.md").write_text("Frozen choices\n")
            lock_path = root / "lock.json"
            lock_path.write_text("{}")
            lock = dict(
                study_protocol=dict(path="study.md"), scripts={"model.py": "hash"}
            )
            subprocess.run(
                ["git", "init", "-q", str(root)], check=True, capture_output=True
            )
            with self.assertRaisesRegex(ValueError, "Commit"):
                verify_committed_protocol(lock, lock_path, root)
            subprocess.run(
                ["git", "add", "."], cwd=root, check=True, capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "Freeze test protocol",
                ],
                cwd=root,
                check=True,
                capture_output=True,
            )
            commit = verify_committed_protocol(lock, lock_path, root)
            self.assertEqual(len(commit), 40)
            (root / "python/model.py").write_text("version = 2\n")
            with self.assertRaisesRegex(ValueError, "Commit"):
                verify_committed_protocol(lock, lock_path, root)


class PrimaryContrastTests(unittest.TestCase):
    def test_reports_all_paired_outcomes_and_uninformative_empty_case(self):
        names = ("1024-disabled-adaptive", "1024-disabled-burst")
        rows = lambda hits: [
            dict(
                event_id=str(i),
                source_eligible=True,
                full_archive_evidence=True,
                retained_evidence=hit,
            )
            for i, hit in enumerate(hits)
        ]
        temporal = dict(
            arms={
                names[0]: dict(
                    events=rows([True, False, True, False]),
                    retained_events=2,
                    source_eligible_events=4,
                ),
                names[1]: dict(
                    events=rows([True, True, False, False]),
                    retained_events=2,
                    source_eligible_events=4,
                ),
            }
        )
        benchmark = dict(arms={name: dict(serialized_bytes=100) for name in names})
        result = compare(benchmark, temporal)
        self.assertEqual(
            result["paired_counts"],
            dict(both=1, pair_only=1, singleton_only=1, neither=1),
        )
        for name in names:
            temporal["arms"][name] = dict(
                events=[], retained_events=0, source_eligible_events=0
            )
        self.assertFalse(compare(benchmark, temporal)["informative"])
