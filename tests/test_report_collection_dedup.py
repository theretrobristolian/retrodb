"""Ensure report-only duplicate accounting never hides verified multi-disc releases."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "report_excel", Path(__file__).resolve().parents[1] / "server" / "report_excel.py"
)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def entry(name, game_id, state):
    row = [name, name + ".iso", "SLUS-12345", state, "NO", "reason",
           game_id, "", "", "", name, "", "standard", "COUNT"]
    return row


def test_noncompatible_duplicate_excluded_when_verified_release_present():
    pal = entry("007 PAL", "20816", "NO")
    ntsc = entry("007 USA", "20816", "YES")
    result = report.apply_collection_dedup([pal, ntsc])
    assert result[0][13].startswith("EXCLUDE")
    assert result[1][13] == "COUNT — verified"
    assert len([r for r in result if not r[13].startswith("EXCLUDE")]) == 1


def test_two_verified_discs_remain_counted():
    disc_one = entry("Devil May Cry 2 Disc 1", "7153", "YES")
    disc_two = entry("Devil May Cry 2 Disc 2", "7153", "YES")
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup([disc_one, disc_two]))


def test_unverified_pairs_and_unknown_ids_remain_counted():
    rows = [entry("PAL", "3062", "NO"), entry("USA", "3062", "NO"),
            entry("Game A", "", "UNKNOWN"), entry("Game B", "", "UNKNOWN")]
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup(rows))
