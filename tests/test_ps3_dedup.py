"""Synthetic ISO9660 comparisons: never assume a matching disc ID means identical bytes."""
from pathlib import Path
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
