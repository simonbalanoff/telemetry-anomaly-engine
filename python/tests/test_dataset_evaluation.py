import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from dataset import (
    COLUMNS,
    POLICY,
    cell_interval,
    export_metadata,
    load_events,
    read_header,
    sha256,
    timestamp_us,
    verify_dataset,
)
from evaluate import (
    alarm_intervals,
    average_precision,
    event_metrics,
    label_masks,
    partition_events,
    select_thresholds,
)
from write_binary import Frame, Header, PERIOD_US, write_binary


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.header = Header(0, 100, 30 * PERIOD_US, 60 * PERIOD_US)
        self.row = [
            "id_1",
            "41",
            "Anomaly",
            "1970-01-01T00:00:30.000000Z",
            "1970-01-01T00:01:00.000000Z",
        ]

    def write_events(self, rows):
        path = self.root / "events.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            writer.writerows(rows)
        return path

    def test_point_and_half_open_boundary_labels(self):
        row2 = self.row.copy()
        row2[0], row2[1], row2[3] = "id_2", "44", row2[4]
        events = load_events(self.write_events([self.row, row2]), self.header)
        self.assertEqual(cell_interval(events[0], self.header), (1, 2))
        self.assertEqual(cell_interval(events[1], self.header), (2, 3))
        masks = label_masks(events, self.header)
        self.assertEqual(masks["Anomaly"][1], 1)
        self.assertEqual(masks["Anomaly"][2], 8)
        self.assertEqual(masks["Rare Event"].sum(), 0)

    def test_rejects_duplicates_categories_ranges_and_inconsistent_ids(self):
        for column, value in [
            (1, "47"),
            (2, "Normal"),
            (3, "1970-01-02T00:00:00.000000Z"),
            (4, "1970-01-01T00:00:00.000000Z"),
        ]:
            row = self.row.copy()
            row[column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                load_events(self.write_events([row]), self.header)
        with self.assertRaises(ValueError):
            load_events(self.write_events([self.row, self.row]), self.header)
        alternate_channel = self.row.copy()
        alternate_channel[1] = "041"
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_events(self.write_events([self.row, alternate_channel]), self.header)
        row = self.row.copy()
        row[2] = "Rare Event"
        with self.assertRaises(ValueError):
            load_events(self.write_events([self.row, row]), self.header)

    def test_rejects_invalid_precision_or_timezone(self):
        for text in ["1970-01-01T00:00:00", "1970-01-01T00:00:00.000000001Z", "NaTZ"]:
            with self.assertRaises(ValueError):
                timestamp_us(text)

    def test_binary_header_roundtrip_and_corruption(self):
        path = self.root / "telemetry.bin"
        write_binary(path, self.header, [Frame((0.0,) * 6, 63, 63, 0)] * 100)
        self.assertEqual(read_header(path), self.header)
        with path.open("ab") as f:
            f.write(b"x")
        with self.assertRaises(ValueError):
            read_header(path)

    def test_manifest_hash_and_safe_paths(self):
        (self.root / "telemetry.bin").write_bytes(b"telemetry")
        self.write_events([self.row])
        manifest = dict(
            POLICY,
            files={
                key: dict(path=name, sha256=sha256(self.root / name))
                for key, name in [
                    ("telemetry", "telemetry.bin"),
                    ("events", "events.csv"),
                ]
            },
        )
        # Mock only header parsing to exercise manifest checks with tiny files.
        production = Header(0, 100, 1199145600000000, 1293840000000000)
        with patch("dataset.read_header", return_value=production):
            (self.root / "manifest.json").write_text(json.dumps(manifest))
            verify_dataset(self.root)
            manifest["files"]["telemetry"]["path"] = "../telemetry.bin"
            (self.root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "path"):
                verify_dataset(self.root)
            manifest["files"]["telemetry"]["path"] = "telemetry.bin"
            (self.root / "manifest.json").write_text(json.dumps(manifest))
            (self.root / "events.csv").write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_dataset(self.root)

    def test_export_preserves_channel_specific_intervals(self):
        write_binary(
            self.root / "telemetry.bin",
            self.header,
            [Frame((0.0,) * 6, 63, 63, 0)] * 100,
        )
        (self.root / "labels.csv").write_text(
            "ID,Channel,StartTime,EndTime\n"
            "id_1,channel_41,1970-01-01T00:00:30Z,1970-01-01T00:01:00Z\n"
            "id_1,channel_44,1970-01-01T00:01:30Z,1970-01-01T00:01:30Z\n"
        )
        (self.root / "anomaly_types.csv").write_text("ID,Category\nid_1,Anomaly\n")
        with patch("dataset.verify_dataset", return_value=(self.header, [])):
            export_metadata(self.root, self.root)
        events = load_events(self.root / "events.csv", self.header)
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0]["start_us"], events[1]["start_us"])
        self.assertEqual(events[1]["start_us"], events[1]["end_us"])


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.header = Header(0, 12, 4 * PERIOD_US, 8 * PERIOD_US)
        self.events = [
            dict(
                event_id="a",
                category="Anomaly",
                channel=41,
                start_us=5 * PERIOD_US + 1000000,
                end_us=5 * PERIOD_US + 1000000,
            ),
            dict(
                event_id="b",
                category="Rare Event",
                channel=44,
                start_us=7 * PERIOD_US,
                end_us=8 * PERIOD_US,
            ),
        ]

    def test_event_dedup_exclusions_and_availability_delay(self):
        scores = np.array([0, 0, 0, 0, 0, 10, 10, 10, 0, 10, 0, 0.0])
        masks = label_masks(self.events, self.header)
        eligible = masks["Rare Event"] == 0
        result = event_metrics(
            scores, eligible, self.events, self.header, 5, masks["Anomaly"]
        )
        self.assertEqual(result["detected_events"], 1)
        self.assertEqual(result["false_alarms"], 1)
        self.assertEqual(result["alarm_episodes"], 2)
        self.assertEqual(result["detection_delay_seconds"]["50"], 29)
        self.assertEqual(result["event_f1"], 2 / 3)

    def test_excluded_or_warmup_events_not_counted_as_detectable(self):
        eligible = np.zeros(12, dtype=bool)
        result = event_metrics(
            np.zeros(12), eligible, self.events, self.header, 1, np.zeros(12)
        )
        self.assertEqual(result["unscorable_events"], 1)
        self.assertEqual(result["eligible_events"], 0)
        self.assertIsNone(result["false_alarms_per_eligible_day"])

    def test_tied_average_precision(self):
        self.assertAlmostEqual(
            average_precision(np.array([1.0, 1.0, 0]), np.array([1, 0, 1])), 7 / 12
        )

    def test_nan_and_excluded_cells_break_alarm_episodes(self):
        self.assertEqual(
            alarm_intervals(
                np.array([2.0, np.nan, 2.0, 2.0]), np.array([1, 1, 0, 1], bool), 1
            ),
            [(0, 1), (3, 4)],
        )

    def test_threshold_selection_never_uses_test_scores_or_labels(self):
        header = Header(0, 90, 30 * PERIOD_US, 60 * PERIOD_US)
        events = [
            dict(
                event_id="validation",
                category="Anomaly",
                channel=41,
                start_us=40 * PERIOD_US,
                end_us=41 * PERIOD_US,
            ),
            dict(
                event_id="test",
                category="Anomaly",
                channel=41,
                start_us=70 * PERIOD_US,
                end_us=71 * PERIOD_US,
            ),
        ]
        scores = np.tile(np.linspace(0, 1, 90)[:, None], (1, 2))
        scores[40] = 10
        expected = select_thresholds(
            scores, label_masks(events, header), events, header, 30, 60
        )
        scores[60:] = 1e100
        events[1]["start_us"] = 80 * PERIOD_US
        events[1]["end_us"] = 81 * PERIOD_US
        actual = select_thresholds(
            scores, label_masks(events, header), events, header, 30, 60
        )
        self.assertEqual(actual, expected)

    def test_split_clips_event_without_leaking_history(self):
        crossing = dict(self.events[0], start_us=3 * PERIOD_US, end_us=6 * PERIOD_US)
        clipped = partition_events([crossing], self.header, 4, 8)
        self.assertEqual(clipped[0]["start_us"], 4 * PERIOD_US)
