import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from ps3_rename import audit, catalogue, safe_title

class TestPS3Rename(unittest.TestCase):
    def test_grouped_sidecars_and_uppercase_iso(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stem = "METAL GEAR SOLID 4GUNS OF THE PATRIOTS [BLES00246]"
            for ext in (".ISO", ".dkey", ".png"):
                (root / (stem + ext)).write_bytes(b"test")
            db = root / "titles.json"
            db.write_text(json.dumps({"BLES-00246": "Metal Gear Solid 4: Guns of the Patriots"}))
            rows, plans = audit(root, catalogue(db))
            self.assertEqual(rows[0]["status"], "RENAME_CANDIDATE")
            self.assertEqual(len(plans), 1)
            self.assertEqual(len(plans[0]), 3)
            self.assertEqual({Path(target).suffix for _, target in plans[0]}, {".iso", ".png", ".dkey"})
            self.assertEqual(rows[0]["proposed_iso"], "Metal Gear Solid 4 Guns of the Patriots [BLES00246].iso")

    def test_unknown_id_not_renamed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "A Game.iso").touch()
            rows, plans = audit(root, {"BLES00246": "Metal Gear Solid 4"})
            self.assertEqual(rows[0]["status"], "REVIEW")
            self.assertFalse(plans)

    def test_target_conflict_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WRONG [BLES00246].iso").touch()
            (root / "Metal Gear Solid 4 [BLES00246].iso").touch()
            rows, plans = audit(root, {"BLES00246": "Metal Gear Solid 4"})
            self.assertFalse(plans)
            self.assertIn("REVIEW", {r["status"] for r in rows})

if __name__ == "__main__":
    unittest.main()
