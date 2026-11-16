"""Metadata-only selection and training-limited numeric inspection."""

from pathlib import Path
import pickle
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

from audit_mission_channels import audit, select_channels, load_trusted_channel


def metadata():
    return pd.DataFrame(
        [
            dict(
                Channel=f"channel_{number}", Group=group, Target="YES", Categorical="NO"
            )
            for group, numbers in ((14, range(70, 76)), (13, range(86, 92)))
            for number in numbers
        ]
    )


def write_channels(root, *, shift=None, training_nan=False):
    (root / "channels").mkdir()
    metadata().to_csv(root / "channels.csv", index=False)
    times = pd.to_datetime(
        ["2000-01-01", "2000-02-01", "2000-03-01", "2002-01-01"]
    ).as_unit("us")
    for number in range(86, 92):
        name = f"channel_{number}"
        index = times.copy()
        if number == 91 and shift is not None:
            index = index + pd.Timedelta(microseconds=shift)
        # A nonnumeric evaluation sentinel must never be converted or summarized.
        values = [0.0, 1.0, np.nan if training_nan else 2.0, "UNINSPECTED-EVALUATION"]
        frame = pd.DataFrame({name: values}, index=index)
        with zipfile.ZipFile(root / "channels" / f"{name}.zip", "w") as archive:
            archive.writestr(name, pickle.dumps(frame))
    (root / "labels.csv").write_text("THIS FILE MUST NOT BE PARSED")


class MissionChannelAuditTests(unittest.TestCase):
    def test_selection_uses_lowest_complete_numeric_target_group(self):
        rows = metadata()
        self.assertEqual(
            select_channels(rows), (13, [f"channel_{n}" for n in range(86, 92)])
        )
        rows.loc[rows.Channel == "channel_86", "Categorical"] = "YES"
        self.assertEqual(select_channels(rows)[0], 14)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_channels(pd.concat([rows, rows.iloc[:1]]))

    def test_training_only_values_microsecond_units_and_unread_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_channels(root)
            cutoff = int(pd.Timestamp("2001-10-01", tz="UTC").value // 1000)
            report = audit(root, cutoff)
            self.assertTrue(report["ready_for_native_adapter"])
            self.assertFalse(report["full_numeric_validation_performed"])
            self.assertEqual(
                report["channel_audit"]["channel_86"]["training_observations"], 3
            )
            self.assertEqual(
                load_trusted_channel(
                    root / "channels/channel_86.zip", "channel_86"
                ).iloc[-1],
                "UNINSPECTED-EVALUATION",
            )

    def test_rejects_native_misalignment_and_nonfinite_training_values(self):
        cutoff = int(pd.Timestamp("2001-10-01", tz="UTC").value // 1000)
        for changes in (dict(shift=1), dict(training_nan=True)):
            with self.subTest(
                changes=changes
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_channels(root, **changes)
                self.assertFalse(audit(root, cutoff)["ready_for_native_adapter"])


class NativeExportTests(unittest.TestCase):
    def source(self, root, precision_loss=False):
        write_channels(root)
        for number in range(86, 92):
            name = f"channel_{number}"
            path = root / "channels" / f"{name}.zip"
            frame = load_trusted_channel(path, name).to_frame()
            frame[name] = np.array([0, 1, 2, 3], dtype="<f4")
            if precision_loss and number == 86:
                frame[name] = np.array([2**53 + 1] * 4, dtype=np.uint64)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(name, pickle.dumps(frame))

    def test_export_preserves_values_and_never_needs_labels(self):
        import json
        from export_mission_native import export

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root)
            cutoff = int(pd.Timestamp("2001-10-01", tz="UTC").value // 1000)
            report = audit(root, cutoff)
            path = root / "audit.json"
            path.write_text(json.dumps(report))
            manifest = export(root, path, root / "export")
            actual = np.load(root / "export/values.npy")
            self.assertEqual(actual.shape, (4, 6))
            np.testing.assert_array_equal(actual[:, 0], [0, 1, 2, 3])
            self.assertTrue(manifest["lossless_binary32"])
            self.assertEqual(
                np.load(root / "export/timestamps.npy").dtype, np.dtype("<i8")
            )
            with self.assertRaisesRegex(ValueError, "empty"):
                export(root, path, root / "export")

    def test_export_rejects_hidden_integer_precision_loss(self):
        import json
        from export_mission_native import export

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source(root, precision_loss=True)
            report = audit(
                root, int(pd.Timestamp("2001-10-01", tz="UTC").value // 1000)
            )
            path = root / "audit.json"
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "losslessly"):
                export(root, path, root / "export")
