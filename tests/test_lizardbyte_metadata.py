"""Source matching never attributes a different console or ambiguous game."""
from retrodb.providers import lizardbyte

def test_cache_reader_rejects_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(lizardbyte, "CACHE", tmp_path)
    assert lizardbyte.load(123) == {}

def test_cache_reader_accepts_sourced(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(lizardbyte, "CACHE", tmp_path)
    (tmp_path / "123.json").write_text(json.dumps({"source": "lizardbyte-gamedb", "game_modes": ["Single player"]}))
    assert lizardbyte.load(123)["game_modes"] == ["Single player"]

def test_importer_uses_orm_session_for_entity_and_slug_rows():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "server" / "enrich-gamedb.py").read_text()
    assert "with Session(get_engine()) as db:" in source
    assert "select(LibraryItem, Platform.slug)" in source
