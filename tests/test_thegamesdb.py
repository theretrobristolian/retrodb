"""TheGamesDB matching must not attach metadata from the wrong edition/platform."""
from retrodb.providers.thegamesdb import choose_match, normalise, boxart_url


def test_exact_platform_match_only():
    games = [
        {"id": 1, "game_title": "007 Legends", "platform": 11},
        {"id": 2, "game_title": "007 Legends", "platform": 12},
    ]
    assert choose_match("007 Legends [BLES01614]", games)["id"] == 2


def test_no_fuzzy_or_ambiguous_match():
    assert choose_match("Gran Turismo 5 XL Edition", [
        {"id": 1, "game_title": "Gran Turismo 5", "platform": 12}]) is None
    assert choose_match("007 Legends", [
        {"id": 1, "game_title": "007 Legends", "platform": 12},
        {"id": 2, "game_title": "007 Legends", "platform": 12}]) is None


def test_boxart_must_have_trusted_cdn_path():
    payload = {"include": {"boxart": {
        "base_url": {"original": "https://cdn.thegamesdb.net/images/original"},
        "data": {"2": [{"type": "boxart", "side": "front", "filename": "boxart/front/2-1.jpg"}]}
    }}}
    assert boxart_url(payload, 2) == "https://cdn.thegamesdb.net/images/original/boxart/front/2-1.jpg"
    payload["include"]["boxart"]["data"]["2"][0]["filename"] = "../../escape"
    assert boxart_url(payload, 2) is None
