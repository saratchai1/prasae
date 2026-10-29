#!/usr/bin/env python3
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "audit_drive_batches.py"
BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL"]


class DriveBatchAuditTests(unittest.TestCase):
    def test_macos_sidecars_do_not_count_as_imagery_or_create_fake_months(self):
        scene = "S2A_MSIL2A_20240318T032521_N0511_R018_T47PRP_20240318T075334"
        second_scene = "S2B_MSIL2A_20230922T032521_N0511_R018_T47PRP_20230922T071450"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            incoming = root / "incoming"
            output = root / "audit-artifacts"
            incoming.mkdir()
            archive = incoming / "Archive.zip"

            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for band in BANDS:
                    z.writestr(f"1-STC/2024-03/{scene}/{band}.tif", b"source-tiff")
                    z.writestr(f"__MACOSX/1-STC/2024-03/{scene}/._{band}.tif", b"appledouble")
                z.writestr(f"PLOT_090/2023-09/{second_scene}/B08.tif", b"source-tiff")
                z.writestr(f"__MACOSX/PLOT_090/2023-09/{second_scene}/._B08.tif", b"appledouble")
                z.writestr("__MACOSX/._1-STC", b"appledouble")

            env = os.environ.copy()
            env["DRIVE_BATCH_INPUT"] = str(incoming)
            env["DRIVE_BATCH_OUTPUT"] = str(output)
            subprocess.run(
                [sys.executable, str(SCRIPT)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            report = json.loads((output / "drive_batch_inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(report["zip_count"], 1)
            self.assertEqual(report["archive_entries"], 25)
            self.assertEqual(report["metadata_files"], 13)
            self.assertEqual(report["source_tiff_files"], 12)
            self.assertEqual(report["other_files"], 0)
            self.assertEqual(report["resolved_plot_month_scene_band_paths"], 12)
            self.assertEqual(report["unresolved_source_tiffs"], 0)
            self.assertEqual(report["unique_business_codes"], 1)
            self.assertEqual(report["unique_plot_ids"], 1)
            self.assertEqual(report["unique_scene_ids"], 2)
            self.assertEqual(report["months"], {"2023-09": 1, "2024-03": 11})
            self.assertEqual(sum(report["bands"].values()), 12)
            self.assertEqual(report["bands"]["B08"], 2)
            self.assertEqual(report["summary"][0]["integrity"], "PASS")
            self.assertEqual(report["summary"][0]["files"], 25)
            self.assertEqual(report["summary"][0]["source_tiff_files"], 12)
            self.assertEqual(report["summary"][0]["metadata_files"], 13)

            self.assertTrue(all(x["entry_type"] == "source_tiff" for x in report["sample_paths"]))
            self.assertTrue(all(x["entry_type"] == "macos_metadata" for x in report["sample_metadata_paths"]))
            with (output / "drive_batch_entries.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(Counter(x["entry_type"] for x in rows), {
                "source_tiff": 12,
                "macos_metadata": 13,
            })
            self.assertEqual(sum(1 for x in rows if x["month"] == "2024-03"), 11)
            self.assertEqual(sum(1 for x in rows if x["month"] == "2023-09"), 1)


if __name__ == "__main__":
    unittest.main()
