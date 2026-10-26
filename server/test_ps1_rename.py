#!/usr/bin/env python3
"""Disposable-file PS1 rename smoke tests. Never accesses RetroNAS."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ps1_rename

SERIAL = "SLUS-01272"
FIELDS = ["status","issues","internal_serial","selected_serial","relative_cue","relative_bin","proposed_cue","proposed_bin"]

class PS1RenameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.iso = self.root / "iso"
        self.iso.mkdir()
        self.original = "Example [SLUS_012.72]"
        self.target = "Example [SLUS-01272]"
        self.cue = self.iso / (self.original + ".cue")
        self.bin = self.iso / (self.original + ".bin")
        self.bin.write_bytes(b"TEST DISPOSABLE IMAGE")
        self.original_cue = ('FILE "' + self.bin.name + '" BINARY\r\n'
                             '  TRACK 01 MODE2/2352\r\n'
                             '    INDEX 01 00:00:00\r\n').encode()
        self.cue.write_bytes(self.original_cue)
        self.csvpath = self.root / "audit.csv"
        self.row = dict(status="RENAME_CANDIDATE", issues="",internal_serial=SERIAL, selected_serial=SERIAL,
                        relative_cue="iso/" + self.cue.name,
                        relative_bin="iso/" + self.bin.name,
                        proposed_cue="iso/" + self.target + ".cue",
                        proposed_bin="iso/" + self.target + ".bin")
        self.write_csv()
    def write_csv(self):
        with self.csvpath.open("w", newline="") as f:
            writer=csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(self.row)
    def proposals(self):
        with patch.object(ps1_rename, "disc_serial", return_value=SERIAL):
            return ps1_rename.parse(SimpleNamespace(csv=self.csvpath, root=self.root))
    def test_preview_does_not_modify_files(self):
        self.assertEqual(len(self.proposals()), 1)
        self.assertTrue(self.cue.exists())
        self.assertTrue(self.bin.exists())
        self.assertEqual(self.cue.read_bytes(), self.original_cue)
    def test_apply_rewrites_cue_without_changing_track_layout(self):
        ops=self.proposals()
        journal=self.root / "journal.json"
        with patch.object(ps1_rename, "disc_serial", return_value=SERIAL):
            ps1_rename.apply(ops, journal)
        newcue=self.iso / (self.target+".cue")
        newbin=self.iso / (self.target+".bin")
        self.assertTrue(newcue.exists())
        self.assertTrue(newbin.exists())
        self.assertFalse(self.cue.exists())
        self.assertFalse(self.bin.exists())
        expected=self.original_cue.replace(self.bin.name.encode(), newbin.name.encode())
        self.assertEqual(newcue.read_bytes(), expected)
        self.assertEqual(json.loads(journal.read_text())["operations"][0]["state"], "applied")
    def test_rollback_restores_original_files(self):
        ops = self.proposals()
        journal = self.root / "journal.json"
        with patch.object(ps1_rename, "disc_serial", return_value=SERIAL):
            ps1_rename.apply(ops, journal)
            ps1_rename.rollback(journal)
        self.assertEqual(self.cue.read_bytes(), self.original_cue)
        self.assertTrue(self.bin.exists())
        self.assertFalse((self.iso / (self.target + ".cue")).exists())
        self.assertFalse((self.iso / (self.target + ".bin")).exists())
        self.assertEqual(json.loads(journal.read_text())["operations"][0]["state"], "rolled_back")

    def test_mismatch_skips_rename(self):
        self.row["internal_serial"] = "SLUS-99999"
        self.write_csv()
        self.assertEqual(self.proposals(), [])
    def test_collision_skips_rename(self):
        (self.iso / (self.target+".bin")).write_bytes(b"existing")
        self.assertEqual(self.proposals(), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
