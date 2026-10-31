import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from ps3_rename import audit, catalogue, safe_title, audit_extracted, duplicate_target, internal_disc_id

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

    def test_extracted_game_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = root / "BCES00141-[LittleBigPlanet]"
            (entry / "PS3_GAME" / "USRDIR" / "gamedata").mkdir(parents=True)
            rows = audit_extracted(root)
            self.assertEqual(rows[0]["status"], "SKIPPED_EXTRACTED")
            self.assertEqual(rows[0]["disc_id"], "BCES00141")
            self.assertEqual(entry.name, "BCES00141-[LittleBigPlanet]")

    def test_duplicate_suffix_stays_review_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WRONG [BLES00246].iso").write_bytes(b"source")
            (root / "Metal Gear Solid 4 [BLES00246].iso").write_bytes(b"target")
            rows, plans = audit(root, {"BLES00246": "Metal Gear Solid 4"})
            duplicates = [row for row in rows if row["status"] == "REVIEW_DUPLICATE"]
            self.assertEqual(len(duplicates), 1)
            self.assertTrue(duplicates[0]["proposed_iso"].endswith(" - duplicate [BLES00246].iso"))
            self.assertFalse(plans)

    def test_identical_iso_proposes_old_not_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "WRONG [BLES00246].iso").write_bytes(b"identical")
            (root / "Metal Gear Solid 4 [BLES00246].iso").write_bytes(b"identical")
            rows, plans = audit(root, {"BLES00246": "Metal Gear Solid 4"})
            flagged = [x for x in rows if x["status"] == "REVIEW_IDENTICAL"]
            self.assertEqual(len(flagged), 1)
            self.assertTrue(flagged[0]["proposed_iso"].startswith("OLD_"))
            self.assertFalse(plans)

    def test_gt5_xl_edition_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Gran Turismo 5 - XL Edition [BCUS98114].iso").touch()
            rows, _ = audit(root, {"BCUS98114": "Gran Turismo 5"})
            self.assertIn("XL Edition", rows[0]["proposed_iso"])

    def test_street_fighter_arcade_edition_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Super Street Fighter IV - Arcade Edition [BLES00770].iso").touch()
            rows, _ = audit(root, {"BLES00770": "Super Street Fighter IV"})
            self.assertIn("Arcade Edition", rows[0]["proposed_iso"])

    def test_missing_id_unreadable_iso_does_not_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "F1 2010.ISO"
            path.write_bytes(b"not an ISO volume")
            self.assertFalse(internal_disc_id(path)[0])
            rows, plans = audit(root, {})
            self.assertEqual(rows[0]["status"], "REVIEW")
            self.assertFalse(plans)

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
            self.assertIn("REVIEW_DUPLICATE", {r["status"] for r in rows})

if __name__ == "__main__":
    unittest.main()
