"""PS3 web catalogue naming and platform-count regressions."""
from pathlib import Path
from types import SimpleNamespace

from retrodb.web_ui import disc_id, disc_region, name, platform_counts


def ps3_item(filename):
    return SimpleNamespace(filename=filename,
                           relative_path="roms/sony/playstation3/iso/" + filename,
                           ra_game_title=None)


def test_ps3_serial_region_and_release_name():
    item = ps3_item("Gran Turismo 5 - XL Edition [BCUS98114].iso")
    assert disc_id(item) == "BCUS98114"
    assert name(item, "playstation-3") == "Gran Turismo 5 - XL Edition"
    assert disc_region("BCUS98114", "playstation-3")[0] == "🇺🇸"
    assert disc_region("BLES00917", "playstation-3")[0] == "🇪🇺"
    assert disc_region("BLJM61097", "playstation-3")[0] == "🇯🇵"


def test_ps1_console_counts_exclude_bin_tracks():
    class RecordingSession:
        def execute(self, stmt):
            self.stmt = stmt
            return SimpleNamespace(all=lambda: [])

    db = RecordingSession()
    platform_counts(db)
    sql = str(db.stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'cue'" in sql
    assert "'bin'" not in sql


def test_ps3_artwork_uses_only_matching_png_sidecar(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from retrodb import artwork
    from retrodb.models import LibraryItem, Platform

    monkeypatch.setattr(artwork, "PS3_MOUNT", tmp_path)
    relative = "roms/sony/playstation3/iso/F1 2010 [BLES00917].iso"
    iso = tmp_path / relative
    iso.parent.mkdir(parents=True)
    iso.write_bytes(b"test ISO")
    cover = iso.with_suffix(".png")
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"cover")

    class DB:
        def get(self, model, id):
            if model is LibraryItem:
                return SimpleNamespace(id=id, platform_id=3, is_missing=False,
                                       extension="iso", relative_path=relative)
            if model is Platform:
                return SimpleNamespace(id=3, slug="playstation-3")
            return None

    response = artwork.ps3_sidecar_art(7, db=DB())
    assert Path(response.path) == cover

    cover.unlink()
    try:
        artwork.ps3_sidecar_art(7, db=DB())
        assert False, "A missing sidecar must not be served"
    except HTTPException as exc:
        assert exc.status_code == 404
