from pathlib import Path
from report_psp_audit import inventory, normalise


def test_psp_id_and_read_only_scan(tmp_path):
    root = tmp_path / "iso"
    root.mkdir()
    (root / "Grand Theft Auto Vice City Stories [ULUS10160].iso").write_bytes(b"data")
    (root / "Unknown Game.iso").write_bytes(b"data")
    (root / "OLD_Archive.iso").write_bytes(b"data")
    (root / "sidecar.png").write_bytes(b"data")
    assert normalise("ULUS10160") == "ULUS10160"
    rows = inventory(root, {"ULUS10160": "Grand Theft Auto: Vice City Stories"})
    assert len(rows) == 2
    assert rows[0]["ra_status"] == "NOT_CHECKED"
    assert any(r["disc_id"] == "ULUS10160" and r["status"] == "IDENTIFIED_FROM_FILENAME" for r in rows)
    assert any(r["status"] == "REVIEW_IDENTITY" for r in rows)
    assert (root / "OLD_Archive.iso").exists()
