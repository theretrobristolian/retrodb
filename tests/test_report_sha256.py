"""Regression tests for the read-only, cached console SHA-256 export."""
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from report_sha256 import source_path, enrich


def _csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer=csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_ps1_sha256_is_bin_not_cue(tmp_path):
    game_dir=tmp_path / "roms" / "sony" / "playstation1" / "iso"
    game_dir.mkdir(parents=True)
    payload=b"ps1-disc-payload" * 50
    (game_dir / "Test.bin").write_bytes(payload)
    (game_dir / "Test.cue").write_text('FILE "Test.bin" BINARY\nTRACK 01 MODE2/2352\n')
    audit=tmp_path / "ra.csv"
    _csv(audit,[{"platform":"Sony PlayStation",
                "path":"roms/sony/playstation1/iso/Test.cue"}])
    cache={}
    cache_file=tmp_path / "hash-cache.json"
    assert enrich("ra",audit,tmp_path,cache,cache_file)==0
    first=_read(audit)[0]
    assert first["sha256"]==hashlib.sha256(payload).hexdigest()
    assert first["sha256_target"].endswith("Test.bin")
    assert first["sha256_status"]=="VERIFIED"
    assert enrich("ra",audit,tmp_path,cache,cache_file)==0
    assert _read(audit)[0]["sha256_status"]=="CACHED"


def test_ps2_and_psp_hash_iso(tmp_path):
    pairs=[
        ("ra",{"platform":"Sony PlayStation 2","path":"ps2.iso"},
         tmp_path/"ps2.iso"),
        ("psp",{"relative_path":"game.iso"},
         tmp_path/"roms/sony/playstationportable/iso/game.iso")
    ]
    for i,(kind,row,iso) in enumerate(pairs):
        iso.parent.mkdir(parents=True,exist_ok=True)
        content=(b"content"+bytes([i]))*100
        iso.write_bytes(content)
        audit=tmp_path/f"audit{i}.csv"
        _csv(audit,[row])
        assert enrich(kind,audit,tmp_path,{},tmp_path/f"cache{i}.json")==0
        assert _read(audit)[0]["sha256"]==hashlib.sha256(content).hexdigest()


def test_ps3_extracted_folder_not_hashed(tmp_path):
    iso=tmp_path/"roms/sony/playstation3/iso/Game.iso"
    iso.parent.mkdir(parents=True)
    iso.write_bytes(b"playstation3iso")
    csv_path=tmp_path/"ps3.csv"
    _csv(csv_path,[{"status":"VALID","existing_iso":"Game.iso"},
                   {"status":"EXTRACTED_VALID","existing_iso":"Game/"}])
    assert enrich("ps3",csv_path,tmp_path,{},tmp_path/"cache.json")==0
    rows=_read(csv_path)
    assert len(rows[0]["sha256"])==64
    assert rows[1]["sha256"]==""
    assert rows[1]["sha256_status"].startswith("NOT_APPLICABLE")


def test_cue_rejects_path_traversal(tmp_path):
    cue=tmp_path/"roms/sony/playstation1/iso/Bad.cue"
    cue.parent.mkdir(parents=True)
    cue.write_text('FILE "../outside.bin" BINARY\n')
    try:
        source_path("ra",{"platform":"Sony PlayStation",
                          "path":"roms/sony/playstation1/iso/Bad.cue"},tmp_path)
    except ValueError as exc:
        assert "Unsafe" in str(exc)
    else:
        raise AssertionError("Relative traversal in CUE must be rejected")



def test_fast_export_does_not_read_image_contents(tmp_path, monkeypatch):
    import report_sha256
    image = tmp_path / "ps2.iso"
    image.write_bytes(b"large-game-data")
    audit = tmp_path / "audit.csv"
    _csv(audit, [{"platform": "Sony PlayStation 2", "path": "ps2.iso"}])

    def must_not_hash(_path):
        raise AssertionError("Fast default audit must not SHA-256 image contents")

    monkeypatch.setattr(report_sha256, "sha256_file", must_not_hash)
    assert enrich("ra", audit, tmp_path, {}, tmp_path / "cache.json",
                  cached_only=True) == 0
    row = _read(audit)[0]
    assert not row["sha256"]
    assert row["sha256_status"].startswith("NOT_CALCULATED")


def test_fast_export_reuses_existing_sha256_cache(tmp_path, monkeypatch):
    import report_sha256
    image = tmp_path / "ps2.iso"
    image.write_bytes(b"verified-image")
    st = image.stat()
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    cache = {str(image): {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                          "sha256": digest}}
    audit = tmp_path / "audit.csv"
    _csv(audit, [{"platform": "Sony PlayStation 2", "path": "ps2.iso"}])

    def must_not_hash(_path):
        raise AssertionError("Cached audit should never read whole image")

    monkeypatch.setattr(report_sha256, "sha256_file", must_not_hash)
    assert enrich("ra", audit, tmp_path, cache, tmp_path / "cache.json",
                  cached_only=True) == 0
    row = _read(audit)[0]
    assert row["sha256"] == digest
    assert row["sha256_status"] == "CACHED"
