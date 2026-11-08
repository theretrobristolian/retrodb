"""PS2 live OPL rename must recover disc IDs inside otherwise unlabelled ISOs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from ps2_live_rename import inventory
from report_opl_rename import propose


def build_iso_with_system_cnf(path, disc_id="SLUS_214.39"):
    """Create a minimal ISO9660 image with SYSTEM.CNF in its root directory."""
    sectors = 32
    iso = bytearray(sectors * 2048)
    pvd = 16 * 2048
    iso[pvd] = 1
    iso[pvd + 1:pvd + 6] = b"CD001"
    iso[pvd + 6] = 1

    def root_record(lba, size, name):
        record = bytearray(33 + len(name) + ((len(name) % 2) == 0))
        record[0] = len(record)
        record[2:6] = lba.to_bytes(4, "little")
        record[10:14] = size.to_bytes(4, "little")
        record[32] = len(name)
        record[33:33 + len(name)] = name
        return record

    iso[pvd + 156:pvd + 190] = root_record(20, 2048, b"\x00")[:34]
    entry = root_record(21, 100, b"SYSTEM.CNF;1")
    iso[20 * 2048:20 * 2048 + len(entry)] = entry
    config = f"BOOT2 = cdrom0:\\{disc_id};1\r\nVER = 1.00\r\n".encode()
    iso[21 * 2048:21 * 2048 + len(config)] = config
    # Directory declares a maximum of 100 bytes; the rest are padding.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(iso)


def test_serialless_iso_is_proposed_from_system_cnf(tmp_path):
    folder = tmp_path / "roms/sony/playstation2/dvd"
    build_iso_with_system_cnf(folder / "Destroy All Humans! 2 (USA).iso")
    rows = inventory(tmp_path, {"SLUS-21439": "Destroy All Humans! 2"})
    assert len(rows) == 1
    assert rows[0]["local_serial"] == "SLUS-21439"
    proposals = propose(rows, verify_root=tmp_path)
    assert proposals[0]["Status"] == "PROPOSED"
    assert proposals[0]["Proposed filename"] == "SLUS_214.39.Destroy All Humans 2.iso"


def test_unidentified_iso_remains_review(tmp_path):
    folder = tmp_path / "roms/sony/playstation2/dvd"
    folder.mkdir(parents=True)
    (folder / "Unknown (USA).iso").write_bytes(b"no iso9660 descriptor")
    rows = inventory(tmp_path, {"SLUS-21439": "Destroy All Humans! 2"})
    assert rows[0]["local_serial"] == ""
    assert propose(rows)[0]["Status"] == "REVIEW"
