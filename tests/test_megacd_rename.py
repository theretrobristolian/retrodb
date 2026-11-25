import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import megacd_rename as m

def disc(tmp_path):
    folder = tmp_path / "Example (USA)"
    folder.mkdir()
    (folder / "a.bin").write_bytes(b"a" * 2352 * 75)
    (folder / "b.bin").write_bytes(b"b" * 2352 * 10)
    cue = folder / "old.cue"
    cue.write_text('FILE "a.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\nFILE "b.bin" BINARY\n TRACK 02 AUDIO\n INDEX 00 00:00:00\n INDEX 01 00:00:02\n')
    return cue

def test_merge_offsets_and_original_backup(tmp_path, monkeypatch):
    cue = disc(tmp_path)
    blocks, text = m.layout(cue, cue.parent.name)
    assert "INDEX 00 00:01:00" in text
    assert "INDEX 01 00:01:02" in text
    monkeypatch.setattr(m, "ra_hash", lambda *args: "a" * 32)
    m.apply(tmp_path, cue, blocks, text, None, tmp_path / "journal")
    assert (tmp_path / "OLD_Example (USA)" / "old.cue").exists()
    assert (cue.parent / "Example (USA).bin").read_bytes() == b"a" * 2352 * 75 + b"b" * 2352 * 10

def test_hash_mismatch_keeps_original(tmp_path, monkeypatch):
    cue = disc(tmp_path)
    blocks, text = m.layout(cue, cue.parent.name)
    hashes = iter(["a" * 32, "b" * 32])
    monkeypatch.setattr(m, "ra_hash", lambda *args: next(hashes))
    with pytest.raises(ValueError, match="verification failed"):
        m.apply(tmp_path, cue, blocks, text, None, tmp_path / "journal")
    assert cue.exists()
    assert not (tmp_path / "OLD_Example (USA)").exists()

def test_extra_file_refused(tmp_path):
    cue = disc(tmp_path)
    (cue.parent / "extra.zip").touch()
    with pytest.raises(ValueError, match="Extra files"):
        m.layout(cue, cue.parent.name)
