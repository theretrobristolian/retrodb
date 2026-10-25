"""Network catalogue import and release-aware Excel report smoke tests."""
import csv
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

spec = importlib.util.spec_from_file_location("online_catalogue", Path(__file__).resolve().parents[1] / "server" / "online_catalogue.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_serial_variants_and_no_guessing():
    assert m.serial("SLES_525.70") == "SLES-52570"
    assert m.serial("SLUS_207.51") == "SLUS-20751"
    assert m.serial("Unidentified") == ""
    row = m.report_row({"platform":"Sony PlayStation 2", "path":"roms/unknown.iso",
                        "local_serial":"SLES_525.70"}, {})
    assert row[4] == "UNKNOWN"
    assert row[6] == "UNKNOWN"

def test_csv_import_and_region_specific_match():
    with TemporaryDirectory() as d:
        source, output = Path(d)/"community.csv", Path(d)/"online.json"
        header = ["Game Tittle"] + [""] * 7 + ["Game ID"] + [""] * 20
        record = ["Area 51 [PAL]", "", "YES", "17/09/2026", "Cristian", "GameSpy",
                  "First Person Shooters", "PAL (EU)", "SLES_525.70", "YES",
                  "YES", "NO", "NO", "16", "NO"] + [""]*14
        with source.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerows([["intro"], [], [], header, record])
        m.import_ps2(source, output)
        catalog = m.load(output)
        result = m.report_row({"platform":"Sony PlayStation 2", "path":"roms/Area 51.iso",
                               "local_serial":"SLES-52570"},catalog)
        assert result[4] == "YES"
        assert result[5] == "GameSpy"
        assert result[7] == "NO"
        unknown = m.report_row({"platform":"Sony PlayStation 2", "local_serial":"SLUS-20595",
                                "path":"roms/other.iso"},catalog)
        assert unknown[4] == "UNKNOWN"

def test_shifted_csv_and_zero_records_rejected():
    import pytest
    with TemporaryDirectory() as d:
        file, target = Path(d)/"sheet.csv", Path(d)/"online.json"
        header = ["", "Game Tittle"] + [""] * 7 + ["Game ID"] + [""] * 20
        row = ["", "Area 51 [PAL]", "", "YES", "2026", "custom DNS", "GameSpy",
               "FPS", "PAL", "SLES_525.70"] + [""] * 20
        with file.open("w", newline="", encoding="utf-8") as fh:
            w=csv.writer(fh)
            w.writerows([[], [], [], header, row])
        payload = m.import_ps2(file,target)
        assert payload["records"][0]["disc_id"] == "SLES-52570"
        file.write_text("Game Tittle,,,,,,,,Game ID\\nUnknown game,no disc id\\n")
        with pytest.raises(ValueError,match="Imported 0 disc IDs"):
            m.import_ps2(file,target)
        assert len(m.load(target)) == 1

def test_online_report_separates_historical_and_live_status():
    rec = m.build_record(["Example", "", "YES", "2026", "dns.example", "Publisher",
                          "Genre", "USA", "SLUS_123.45", "", "", "", "", "8", "YES"] + [""]*14)
    row = m.report_row({"platform":"Sony PlayStation 2", "local_serial":"SLUS-12345",
                        "path":"roms/example.iso"}, {("playstation-2","SLUS-12345"):rec})
    assert row[4] == "YES"
    assert row[8] == "YES"
    assert row[18] == "UNVERIFIED"
    assert "custom_dns" in row[17]

def test_xlink_sources_remain_independent_and_conflicts_are_visible():
    rec = m.build_record(["Example", "", "YES", "2026", "dns.example", "Publisher",
                          "Genre", "USA", "SLUS_123.45", "", "", "", "", "8", "NO"] + [""]*14)
    source_row = m.report_row({"platform":"Sony PlayStation 2", "local_serial":"SLUS-12345",
                               "path":"roms/example.iso", "gamedb_title":"Example"},
                              {("playstation-2","SLUS-12345"):rec})
    title = m.normalized_title("Example")
    result = m.enrich_with_xlink(source_row, {title:{
        "title":"Example", "source_url":"https://www.teamxlink.co.uk/wiki/PlayStation_2",
        "source_confidence":"bundled_partial_snapshot"}})
    assert len(result) == len(m.ONLINE_COLUMNS)
    assert result[7] == "YES (title-level)"
    assert result[21] == "NO"  # community report retained
    assert result[22] == "YES (title-level)"
    assert "REVIEW" in result[23]
    assert "partial snapshot" in result[19]
    assert result[6] == "YES (title-level)"
    assert result[17].split(",").count(" lan_tunnel") <= 1

def test_online_enrichment_no_source_does_not_claim_no_lan():
    row = m.report_row({"platform":"Sony PlayStation 2", "local_serial":"SLUS-12345",
                        "path":"roms/test.iso", "gamedb_title":"Unknown Game"}, {})
    enriched = m.enrich_with_xlink(row, {})
    assert enriched[6] == "UNKNOWN"
    assert enriched[21] == "UNKNOWN"
    assert enriched[22] == "UNKNOWN"
    assert enriched[23] == ""
    assert len(enriched) == len(m.ONLINE_COLUMNS)
