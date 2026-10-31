"""Synthetic ISO9660 comparisons: never assume a matching disc ID means identical bytes."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from ps3_dedup import compare, audit, iso_index


def entry(name, block, size, directory=False):
    raw = name.encode("ascii") if isinstance(name, str) else name
    n = 33 + len(raw)
    if n % 2:
        n += 1
    result = bytearray(n)
    result[0] = n
    result[2:6] = block.to_bytes(4, "little")
    result[10:14] = size.to_bytes(4, "little")
    result[25] = 2 if directory else 0
    result[32] = len(raw)
    result[33:33+len(raw)] = raw
    return result


def make_iso(path, data):
    buf = bytearray(24 * 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    root = entry(b"\x00", 20, 2048, True)
    pvd[156:156+len(root)] = root
    buf[16*2048:17*2048] = pvd
    record = entry("FILE.BIN;1", 21, len(data))
    buf[20*2048:20*2048+len(record)] = record
    buf[21*2048:21*2048+len(data)] = data
    path.write_bytes(buf)


def test_identical_and_different_files(tmp_path):
    folder = tmp_path / "games" / "Example [BLES12345] - extracted"
    folder.mkdir(parents=True)
    file = folder / "FILE.BIN"
    file.write_bytes(b"abc")
    image = tmp_path / "iso" / "Example [BLES12345].iso"
    image.parent.mkdir()
    make_iso(image, b"abc")
    assert "file.bin" in iso_index(image)
    rows = audit(image.parent, folder.parent)
    assert rows[0]["status"] == "BYTE_IDENTICAL"
    file.write_bytes(b"abd")
    assert compare(folder, image)[0] == "DIFFERENT"


def test_encrypted_or_unreadable_iso_is_inconclusive(tmp_path):
    folder = tmp_path / "games" / "Example [BLES12345] - extracted"
    folder.mkdir(parents=True)
    (folder / "FILE.BIN").write_bytes(b"abc")
    image = tmp_path / "iso" / "Example [BLES12345].iso"
    image.parent.mkdir()
    image.write_bytes(b"unreadable")
    assert audit(image.parent, folder.parent)[0]["status"] == "INCONCLUSIVE"


def test_different_disc_id_is_not_declared_duplicate(tmp_path):
    folder = tmp_path / "games" / "Example [BLES12345] - extracted"
    folder.mkdir(parents=True)
    image = tmp_path / "iso" / "Example [BLUS12345].iso"
    image.parent.mkdir()
    image.write_bytes(b"no matter")
    assert audit(image.parent, folder.parent)[0]["status"] == "NO_EXACT_ISO"

def test_multi_extent_file_is_compared(tmp_path):
    folder = tmp_path / "games" / "Example [BLES12345] - extracted"
    folder.mkdir(parents=True)
    (folder / "FILE.BIN").write_bytes(b"abcdef")
    image = tmp_path / "iso" / "Example [BLES12345].iso"
    image.parent.mkdir()
    buf = bytearray(24 * 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    root = entry(bytes([0]), 20, 2048, True)
    pvd[156:156+len(root)] = root
    buf[16*2048:17*2048] = pvd
    first = entry("FILE.BIN;1", 21, 3)
    first[25] = 0x80
    second = entry("FILE.BIN;1", 22, 3)
    buf[20*2048:20*2048+len(first)] = first
    buf[20*2048+len(first):20*2048+len(first)+len(second)] = second
    buf[21*2048:21*2048+3] = b"abc"
    buf[22*2048:22*2048+3] = b"def"
    image.write_bytes(buf)
    assert len(iso_index(image)["file.bin"]) == 2
    assert compare(folder, image)[0] == "BYTE_IDENTICAL"


def test_full_difference_details(tmp_path):
    from ps3_dedup import compare_details
    folder = tmp_path / "games" / "Example [BLES12345] - extracted"
    folder.mkdir(parents=True)
    (folder / "FILE.BIN").write_bytes(b"bad")
    (folder / "EXTRA.DAT").write_bytes(b"extra")
    image = tmp_path / "iso" / "Example [BLES12345].iso"
    image.parent.mkdir()
    make_iso(image, b"abc")
    summary, files = compare_details(folder, image)
    assert summary[0] == "DIFFERENT"
    assert {record["status"] for record in files} == {"HASH_DIFFERENT", "EXTRACTED_ONLY"}
    assert all(record["extracted_sha256"] for record in files)
    assert files[0]["path"] == "extra.dat"

def test_cleanup_only_approved_ids_and_only_firmware_difference(tmp_path):
    from ps3_dedup import removable_candidates
    root = tmp_path / "iso"
    games = tmp_path / "games"
    root.mkdir()
    games.mkdir()
    # Synthetic minimal ISO with two files and a nested firmware directory.
    for disc in ("BLES00680", "BLES12345"):
        folder = games / f"Red Dead Redemption [{disc}] - extracted"
        folder.mkdir()
        (folder / "FILE.BIN").write_bytes(b"abc")
        iso = root / f"Red Dead Redemption [{disc}].iso"
        buf = bytearray(30 * 2048)
        pvd = bytearray(2048)
        pvd[0] = 1
        pvd[1:6] = b"CD001"
        rd = entry(bytes([0]), 20, 2048, True)
        pvd[156:156+len(rd)] = rd
        buf[16*2048:17*2048] = pvd
        regular = entry("FILE.BIN;1", 21, 3)
        firmware_dir = entry("PS3_UPDATE", 22, 2048, True)
        buf[20*2048:20*2048+len(regular)] = regular
        buf[20*2048+len(regular):20*2048+len(regular)+len(firmware_dir)] = firmware_dir
        firmware = entry("PS3UPDAT.PUP;1", 23, 3)
        buf[22*2048:22*2048+len(firmware)] = firmware
        buf[21*2048:21*2048+3] = b"abc"
        buf[23*2048:23*2048+3] = b"pup"
        iso.write_bytes(buf)
    choices = removable_candidates(root, games)
    assert len(choices) == 1
    assert "BLES00680" in choices[0][0].name
