"""Parser smoke tests for the Team XLink PS2 supported-games wiki."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("import_xlink", Path(__file__).resolve().parents[1] / "server" / "import_xlink.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_ps2_game_table_is_recognised():
    sample = """<table><tr><th>Platform</th><th>PlayStation 2</th></tr></table>
    <table><tr><th>Title</th><th>Versus Mode</th><th>Co-op Mode</th><th>PAL/NTSC Crossplay</th><th>Total players</th></tr>
    <tr><td>25 To Life</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>TimeSplitters 2</td><td></td><td></td><td>✓</td><td></td></tr></table>"""
    parser = m.WikiTables()
    parser.feed(sample)
    matching = [table for table in parser.tables if table and table[0] and table[0][0].strip().lower() == "title"
                and "versus mode" in " ".join(table[0]).lower() and "co-op mode" in " ".join(table[0]).lower()]
    assert len(matching) == 1
    assert [row[0] for row in matching[0][1:]] == ["25 To Life", "TimeSplitters 2"]

def test_select_ps2_game_table_without_depending_on_header_text():
    titles = ["25 To Life", "Armored Core: Last Raven", "ATV Offroad Fury 2",
              "Gran Turismo 4", "Star Wars: Battlefront", "TimeSplitters 2"]
    titles += [f"LAN game {i}" for i in range(20)]
    table = [["Game name", "Versus", "Coop"]] + [[t, "", ""] for t in titles]
    picked = m.select_ps2_table([[["Platform", "PlayStation 2"]], table])
    assert len(picked) == len(titles)
    assert picked[0][0] == "25 To Life"
