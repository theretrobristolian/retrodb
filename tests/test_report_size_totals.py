"""File-size and Excel filter subtotal regression checks."""
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from report_excel import (COLS, SIZE_COLUMNS, GIB, append_size_and_selection,
                          get_disc_size, xml_sheet)


def test_ps2_exact_bytes_and_best_case():
    raw = {"platform": "Sony PlayStation 2", "path": "roms/sony/playstation2/dvd/example.iso",
           "size_bytes": str(2 * GIB), "local_region": "Europe",
           "preferred_region": "USA", "recommended_ra_title": "Example"}
    row = [""] * len(COLS)
    row[13] = "COUNT"
    sized = append_size_and_selection(row, raw)
    assert sized[-4:] == [2 * GIB, 2.0, "YES", "NO"]
    raw.update(preferred_region="", recommended_ra_title="")
    assert append_size_and_selection(row, raw)[-2:] == ["NO", "YES"]
    row[13] = "EXCLUDE — duplicate"
    assert append_size_and_selection(row, raw)[-1] == "NO"


def test_ps1_cue_uses_bin_payload(tmp_path):
    roms = tmp_path / "roms" / "sony" / "playstation1" / "iso"
    roms.mkdir(parents=True)
    (roms / "Example.bin").write_bytes(b"payload")
    (roms / "Example.cue").write_text('FILE "Example.bin" BINARY\n  TRACK 01 MODE2/2352\n')
    raw = {"platform": "Sony PlayStation", "path": "roms/sony/playstation1/iso/Example.cue",
           "size_bytes": "89"}
    assert get_disc_size(raw, tmp_path) == 7
    raw["payload_size_bytes"] = "98765"
    assert get_disc_size(raw, tmp_path) == 98765


def test_sheet_footer_uses_filter_aware_numeric_subtotals():
    headers = COLS + SIZE_COLUMNS
    a = [""] * len(headers)
    b = [""] * len(headers)
    a[0] = "First"
    b[0] = "Second"
    a[headers.index("File size (bytes)")] = GIB
    a[headers.index("File size (GiB)")] = 1.0
    b[headers.index("File size (bytes)")] = 2 * GIB
    b[headers.index("File size (GiB)")] = 2.0
    root = ET.fromstring(xml_sheet([headers, a, b]))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert root.find("x:autoFilter", ns).get("ref").endswith("3")
    cells = {cell.get("r"): cell for cell in root.findall(".//x:c", ns)}
    bytes_col = headers.index("File size (bytes)") + 1
    gib_col = headers.index("File size (GiB)") + 1
    from report_excel import excel_column
    byte_ref = excel_column(bytes_col)
    gib_ref = excel_column(gib_col)
    assert cells[f"{byte_ref}2"].find("x:v", ns).text == str(GIB)
    assert cells[f"{gib_ref}3"].find("x:v", ns).text == "2.0"
    assert cells[f"{byte_ref}4"].find("x:f", ns).text == f"SUBTOTAL(109,{byte_ref}2:{byte_ref}3)"
    assert cells[f"{gib_ref}4"].find("x:f", ns).text == f"SUBTOTAL(109,{gib_ref}2:{gib_ref}3)"
    assert cells["B4"].find("x:f", ns).text == "SUBTOTAL(103,A2:A3)"
