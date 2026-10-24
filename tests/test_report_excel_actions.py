"""Cross-platform Action Required export checks."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("report_excel", Path(__file__).resolve().parents[1] / "server" / "report_excel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def entry(filename, status, gameid="", decision="COUNT", patchable="NO"):
    row = ["Test Game", filename, "SLUS-12345", status, patchable, "Review release", gameid, "", "USA", "", "", "", "standard", decision]
    return row + [""] * (len(module.COLS) - len(row))


def test_actions_include_incompatible_and_unknown_but_not_no_set_or_verified():
    entries = [entry("a.iso", "UNKNOWN"), entry("b.iso", "NO"),
               entry("c.iso", "ERROR"), entry("d.iso", "NO SET"), entry("e.iso", "YES")]
    actions = module.action_rows(entries, "Sony PlayStation 2")
    assert {row[2] for row in actions} == {"a.iso", "b.iso", "c.iso"}
    assert all(row[0] == "Sony PlayStation 2" for row in actions)


def test_excludes_duplicate_when_verified_copy_covers_its_ra_id():
    entries = [entry("supported.iso", "YES", "7788"),
               entry("wrong-release.iso", "NO", "7788", "EXCLUDE — compatible copy present")]
    assert module.action_rows(entries, "Sony PlayStation 2") == []


def test_action_sheet_has_identity_and_hash_evidence_columns():
    assert "Platform" in module.ACTION_COLS
    assert "Recommended release" in module.ACTION_COLS
    assert "Local RA hash" in module.ACTION_COLS
    assert "File path" in module.ACTION_COLS
