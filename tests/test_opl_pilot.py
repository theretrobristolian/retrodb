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
    assert len(chosen) == 50
    assert chosen[0]["GameDB title"] == "Game 01"
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
