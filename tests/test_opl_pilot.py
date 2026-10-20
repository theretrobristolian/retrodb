"""Controlled OPL pilot planner, journal and rollback tests (local test filesystem only)."""
import csv
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "opl_pilot", Path(__file__).resolve().parents[1] / "server" / "opl_pilot.py"
)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

def row(title, old, new, status="PROPOSED"):
    return {"GameDB title": title, "Current relative path": old,
            "Proposed relative path": new, "Status": status}

def test_all_eligible_sorted_and_exclusions():
    rows = [row(f"Game {i:02d}", f"x/{i}.iso", f"x/renamed-{i}.iso")
            for i in range(50, 0, -1)]
    rows += [row("AAA", "x/Case.iso", "x/case.iso"),
             row("AAB", "x/Collision.iso", "x/New.iso", "COLLISION")]
    chosen = pilot.plan(rows)
    assert len(chosen) == 51
    assert chosen[0]["GameDB title"] == "AAA"
    assert chosen[-1]["GameDB title"] == "Game 50"

def test_round_trip(tmp_path):
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "Old.iso").write_bytes(b"important ISO bytes")
    selected = [row("Demo", "games/Old.iso", "games/New.iso")]
    journal = tmp_path / "backup" / "pilot.json"
    journal.parent.mkdir()
    pilot.do_apply(tmp_path, selected, journal)
    assert (tmp_path / "games" / "New.iso").read_bytes() == b"important ISO bytes"
    assert not (tmp_path / "games" / "Old.iso").exists()
    pilot.do_rollback(tmp_path, journal)
    assert (tmp_path / "games" / "Old.iso").read_bytes() == b"important ISO bytes"
    assert journal.is_file()

def test_never_overwrites(tmp_path):
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "Old.iso").write_bytes(b"original")
    (tmp_path / "games" / "New.iso").write_bytes(b"other")
    import pytest
    with pytest.raises(ValueError, match="Destination exists"):
        pilot.do_apply(tmp_path,
                       [row("Demo", "games/Old.iso", "games/New.iso")],
                       tmp_path / "pilot.json")
    assert (tmp_path / "games" / "New.iso").read_bytes() == b"other"
    assert not (tmp_path / "pilot.json").exists()

def test_case_only_roundtrip(tmp_path):
    (tmp_path / "games").mkdir()
    old = tmp_path / "games" / "7 SINS.iso"
    old.write_bytes(b"unchanged content")
    rows = [row("7 Sins", "games/7 SINS.iso", "games/7 Sins.iso")]
    journal = tmp_path / "case.json"
    assert pilot.plan(rows) == rows
    pilot.do_apply(tmp_path, rows, journal)
    assert not old.exists()
    assert (tmp_path / "games" / "7 Sins.iso").read_bytes() == b"unchanged content"
    ops = __import__("json").loads(journal.read_text())["operations"]
    assert ops[0]["case_only"] is True
    assert ops[0]["state"] == "applied"
    pilot.do_rollback(tmp_path, journal)
    assert old.read_bytes() == b"unchanged content"

def test_interrupted_case_only_temp_is_rollback_safe(tmp_path):
    import json
    (tmp_path / "games").mkdir()
    original = tmp_path / "games" / "7 SINS.iso"
    original.write_bytes(b"image")
    journal = tmp_path / "interrupted.json"
    rows = [row("7 Sins", "games/7 SINS.iso", "games/7 Sins.iso")]
    pilot.do_apply(tmp_path, rows, journal)
    data = json.loads(journal.read_text())
    op = data["operations"][0]
    target = tmp_path / op["new"]
    temp = tmp_path / op["temp"]
    target.rename(temp)
    op["state"] = "temporary"
    journal.write_text(json.dumps(data))
    pilot.do_rollback(tmp_path, journal)
    assert original.read_bytes() == b"image"
    assert not temp.exists()

def test_existing_case_variant_cannot_be_overwritten(tmp_path):
    import pytest
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "OLD.iso").write_bytes(b"original")
    (tmp_path / "games" / "Another.iso").write_bytes(b"different")
    with pytest.raises(ValueError):
        pilot.do_apply(tmp_path,
            [row("Demo", "games/OLD.iso", "games/Another.iso")],
            tmp_path / "test.json")

def test_resume_after_case_rename_completed_but_journal_stale(tmp_path):
    import json
    (tmp_path / "games").mkdir()
    old = tmp_path / "games" / "7 SINS.iso"
    old.write_bytes(b"case only payload")
    rows = [row("7 Sins", "games/7 SINS.iso", "games/7 Sins.iso")]
    journal = tmp_path / "interrupted.json"
    pilot.do_apply(tmp_path, rows, journal)
    data = json.loads(journal.read_text())
    data["operations"][0]["state"] = "temporary"
    journal.write_text(json.dumps(data))
    pilot.do_resume(tmp_path, journal)
    assert (tmp_path / "games" / "7 Sins.iso").read_bytes() == b"case only payload"
    assert json.loads(journal.read_text())["operations"][0]["state"] == "applied"

def test_resume_from_intermediate_case_name(tmp_path):
    import json
    (tmp_path / "games").mkdir()
    (tmp_path / "games" / "7 SINS.iso").write_bytes(b"payload")
    rows = [row("7 Sins", "games/7 SINS.iso", "games/7 Sins.iso")]
    journal = tmp_path / "intermediate.json"
    pilot.do_apply(tmp_path, rows, journal)
    data = json.loads(journal.read_text())
    op = data["operations"][0]
    (tmp_path / op["new"]).rename(tmp_path / op["temp"])
    op["state"] = "temporary"
    journal.write_text(json.dumps(data))
    pilot.do_resume(tmp_path, journal)
    assert (tmp_path / op["new"]).read_bytes() == b"payload"
    assert not (tmp_path / op["temp"]).exists()
