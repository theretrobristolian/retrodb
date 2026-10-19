import json
from pathlib import Path

import pytest

from retrodb.providers.gamedb import load, normalise_serial, parse_titles, sync


def test_normalises_ps2_disc_serials():
    assert normalise_serial("SCES_516.08") == "SCES-51608"
    assert normalise_serial("SLUS-21399") == "SLUS-21399"
    assert normalise_serial("random") == ""


def test_parses_game_titles_and_skips_bad_records():
    assert parse_titles({
        "SCES-51608": "Jak II: Renegade",
        "SLUS_213.99": "A title",
        "invalid": "Other",
    }) == {"SCES-51608": "Jak II: Renegade", "SLUS-21399": "A title"}


def test_rejects_bad_or_empty_catalogue():
    with pytest.raises(ValueError):
        parse_titles([])
    with pytest.raises(ValueError):
        parse_titles({"bad": "unsupported"})


def test_offline_cache_reused_without_download(tmp_path):
    path = tmp_path / "playstation-2.json"
    path.write_text(json.dumps({"SCES-51608": "Jak II: Renegade"}))
    assert load(tmp_path, "playstation-2")["SCES-51608"] == "Jak II: Renegade"
    assert sync(tmp_path, "playstation-2") == (1, "cached")
