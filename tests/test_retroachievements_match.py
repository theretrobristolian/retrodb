import json
import pytest
from retrodb.retroachievements_match import (
    CatalogueGame,
    MatchError,
    extract_hash,
    identify_local_release,
    load_hash_catalogue,
    normalise_title,
    regions_from_names,
    suggest_game,
)

def test_extract_hash_uses_32_hex_value():
    assert extract_hash("Game.iso: AABBCCDDEEFF00112233445566778899") == "aabbccddeeff00112233445566778899"

def test_extract_hash_rejects_missing_hash():
    with pytest.raises(MatchError):
        extract_hash("Could not identify game")

def test_catalogue_indexes_hashes(tmp_path):
    path = tmp_path / "playstation.json"
    path.write_text(json.dumps([{"ID": 42, "Title": "Example", "ConsoleID": 12, "Hashes": ["aabbccddeeff00112233445566778899"]}]))
    console_id, index = load_hash_catalogue(path)
    assert console_id == 12
    assert index["aabbccddeeff00112233445566778899"] == (42, "Example")


def test_local_serial_identifies_ps_regions():
    assert identify_local_release("ps1/Tony Hawk [SLUS_010.66].cue") == ("SLUS-01066", "USA")
    assert identify_local_release("ps2/dvd/Game [SLES-12345].iso") == ("SLES-12345", "Europe")


def test_title_recommendation_is_conservative():
    games = (
        CatalogueGame(1, "Tony Hawk's Pro Skater 2", ("a" * 32,)),
        CatalogueGame(2, "Tony Hawk's Pro Skater 3", ("b" * 32,)),
    )
    game, confidence, score = suggest_game(
        "sony/playstation1/iso/Tony Hawk's Pro Skater 2 [SLUS_010.66].cue", games
    )
    assert game and game.game_id == 1
    assert confidence == "exact-title"
    assert score == 1.0


def test_region_and_title_helpers():
    assert normalise_title("Game (Europe) (Disc 1).iso") == "game"
    assert regions_from_names(["Game (USA).iso", "Game (Europe, Australia).iso"]) == "USA; Europe; Australia"


def test_title_recommendation_rejects_wrong_sequel():
    games = (
        CatalogueGame(1, "Cool Boarders", ("a" * 32,)),
        CatalogueGame(2, "Cool Boarders 2", ("b" * 32,)),
    )
    game, confidence, _ = suggest_game("Cool Boarders 3 [SCUS_942.51].cue", games)
    assert game is None
    assert confidence == ""


def test_title_recommendation_rejects_demo_for_retail_game():
    games = (CatalogueGame(1, "~Demo~ Need for Speed: Most Wanted", ("a" * 32,)),)
    game, _, _ = suggest_game("Need For Speed Most Wanted [SLES_535.57].iso", games)
    assert game is None


def test_title_recommendation_preserves_numeric_title_suffix():
    games = (CatalogueGame(1, "NBA Street Vol. 2", ("a" * 32,)),)
    game, _, _ = suggest_game("NBA Street V3 [SLUS_211.26].iso", games)
    assert game is None
