import json
import pytest
from retrodb.retroachievements_match import (
    CatalogueGame,
    MatchError,
    alternative_candidates,
    comparable_title,
    extract_hash,
    identify_local_release,
    friendly_local_title,
    load_serial_aliases,
    suggest_by_serial,
    load_hash_catalogue,
    normalise_title,
    preferred_release,
    regions_from_names,
    release_guidance,
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


def test_comparable_title_handles_articles_accents_and_versions():
    assert comparable_title("The Ōkami.iso") == "okami"
    assert comparable_title("Game V3.iso") == "game 3"


def test_ambiguous_rows_include_ranked_alternatives():
    games = (
        CatalogueGame(1, "Alpha Racer", ("a" * 32,)),
        CatalogueGame(2, "Alpha Racing", ("b" * 32,)),
    )
    result = alternative_candidates("Alpha Race.iso", games)
    assert "RA 1" in result
    assert "RA 2" in result


def test_preferred_release_uses_clean_usa_final_revision():
    details = [
        {"MD5": "1" * 32, "Name": "Game (Europe)", "Labels": ["redump"], "PatchUrl": None},
        {"MD5": "2" * 32, "Name": "Game (USA)", "Labels": ["redump"], "PatchUrl": None},
        {"MD5": "3" * 32, "Name": "Game (USA) (Rev 1)", "Labels": ["redump"], "PatchUrl": None},
    ]
    name, region, digest, labels, patch_url = preferred_release(details)
    assert name == "Game (USA) (Rev 1)"
    assert region == "USA"
    assert digest == "3" * 32
    assert labels == "redump"
    assert patch_url == ""


def test_preferred_release_returns_patch_url():
    details = [{
        "MD5": "3" * 32,
        "Name": "Game (USA) (Anti-Cheat)",
        "Labels": ["rapatches"],
        "PatchUrl": "https://retroachievements.org/patch.zip",
    }]
    *_, patch_url = preferred_release(details)
    assert patch_url == "https://retroachievements.org/patch.zip"


def test_regional_title_alias_matches_same_game():
    games = (CatalogueGame(1, "Harry Potter and the Sorcerer's Stone", ("a" * 32,)),)
    game, confidence, _ = suggest_game(
        "Harry Potter and the Philosopher's Stone [SLES_036.62].cue", games
    )
    assert game and game.game_id == 1
    assert confidence == "exact-title"


def test_patch_guidance_is_explicit():
    guidance = release_guidance(
        "Europe", "USA", "Crash Bash (USA) (Menu Glitch Fix)", "rapatches; redump"
    )
    assert guidance.startswith("Apply the RA-supported patch")


def test_serial_aliases_are_documented_and_normalised():
    aliases = load_serial_aliases()
    assert aliases["SCES-50410"] == "Ace Combat 04: Shattered Skies"
    assert aliases["SCES-51608"] == "Jak II"


def test_serial_alias_recognises_european_title_without_hash_claim():
    aliases = load_serial_aliases()
    games = (CatalogueGame(91, "Ace Combat 04: Shattered Skies", ("a" * 32,)),)
    game, method, score = suggest_by_serial("SCES-50410", games, aliases)
    assert game and game.game_id == 91
    assert method == "verified-serial-alias"
    assert score == 1.0


def test_serial_alias_never_guesses_missing_or_duplicate_games():
    aliases = load_serial_aliases()
    one = CatalogueGame(91, "Ace Combat 04: Shattered Skies", ("a" * 32,))
    game, method, _ = suggest_by_serial("SCES-50410", (one, one), aliases)
    assert game is None
    assert method == "serial-alias-no-unique-ra-title"
    game, method, _ = suggest_by_serial("SLUS-99999", (one,), aliases)
    assert game is None
    assert not method


def test_friendly_title_strips_ps2_serial_from_filename():
    assert friendly_local_title("dvd/SCES_516.08.Jak II Renegade.iso") == "Jak II Renegade"
    assert friendly_local_title("dvd/SCES_504.10.Ace Combat Distant Thunder.iso") == "Ace Combat Distant Thunder"

def test_zero_padded_title_numbers_are_equivalent_for_catalogue_identity():
    assert comparable_title("Ace Combat 04: Shattered Skies") == comparable_title(
        "Ace Combat 4: Shattered Skies"
    )
