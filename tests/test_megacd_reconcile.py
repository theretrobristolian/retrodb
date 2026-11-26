import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from report_megacd_audit import reconcile

def row(title, state, ident=""):
    return dict(title=title, folder=title, ra_status=state, ra_game_id=ident,
                ra_hash="a"*32, reason="")

def test_local_alternatives_preserve_unmatched_hash():
    rows = [row("Battle Frenzy (USA) (Unl)", "UNMATCHED"),
            row("Bloodshot ~ Battle Frenzy (Europe)", "SUPPORTED", "33773"),
            row("Cobra Command (Europe)", "UNMATCHED"),
            row("Cobra Command (USA)", "NO_SET", "16011")]
    reconcile(rows, {})
    assert rows[0]["collection_status"] == "SOFT_PASS"
    assert rows[0]["ra_game_id"] == ""
    assert rows[0]["ra_status"] == "UNMATCHED"
    assert rows[2]["collection_status"] == "SOFT_PASS_NO_SET"

def test_alias_is_only_candidate():
    rows = [row("Beast II (Europe)", "UNMATCHED")]
    reconcile(rows, {"b"*32: [{"ID":16046,"Title":"Shadow of the Beast II","NumAchievements":19}]})
    assert rows[0]["collection_status"] == "ALTERNATIVE_REQUIRED"
    assert rows[0]["candidate_ra_id"] == "16046"
    assert rows[0]["ra_game_id"] == ""

def test_unknown_remains_review():
    rows = [row("Unknown game (USA)", "UNMATCHED")]
    reconcile(rows, {})
    assert rows[0]["collection_status"] == "REVIEW"
