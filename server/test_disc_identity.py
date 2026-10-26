"""Synthetic ISO9660 identity tests; no game files or NAS access."""
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.disc_identity import internal_disc_serial


def make_image(path, serial, sector, offset):
    blob = bytearray(sector * 30)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    root = bytearray(34)
    root[2:6] = (20).to_bytes(4, "little")
    root[10:14] = (2048).to_bytes(4, "little")
    pvd[156:190] = root
    blob[16 * sector + offset:16 * sector + offset + 2048] = pvd
    record = bytearray(34 + len(b"SYSTEM.CNF;1"))
    record[0] = len(record)
    record[2:6] = (21).to_bytes(4, "little")
    text = f"BOOT = cdrom:\\{serial.replace('-', '_', 1).replace('_', '_')};1\r\n".encode()
    record[10:14] = len(text).to_bytes(4, "little")
    record[32] = len(b"SYSTEM.CNF;1")
    record[33:] = b"SYSTEM.CNF;1"
    blob[20 * sector + offset:20 * sector + offset + len(record)] = record
    blob[21 * sector + offset:21 * sector + offset + len(text)] = text
    path.write_bytes(blob)


class DiscIdentityTests(unittest.TestCase):
    def test_ps2_iso_without_serial_filename(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "Unlabelled game.iso"
            make_image(file, "SLUS-01272", 2048, 0)
            self.assertEqual(internal_disc_serial(file, "playstation-2"), "SLUS-01272")

    def test_ps1_cue_without_serial_filename(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "Untitled.bin"
            make_image(file, "SCUS-94423", 2352, 24)
            cue = Path(d) / "Untitled.cue"
            cue.write_text('FILE "Untitled.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
            self.assertEqual(internal_disc_serial(cue, "playstation"), "SCUS-94423")

    def test_missing_boot_identity_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "Unknown.iso"
            file.write_bytes(b"unrecognised")
            self.assertEqual(internal_disc_serial(file, "playstation-2"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
