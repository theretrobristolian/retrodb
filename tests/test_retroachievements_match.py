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
    game_db_ra_candidates,
    resolve_catalogue_identity,
    review_reason,
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

def test_gamedb_exact_ra_title_crosswalk():
    games = (CatalogueGame(10, "Ace Combat 04: Shattered Skies", ("a" * 32,)),)
    game, confidence, score, review = game_db_ra_candidates(
        "Ace Combat 4: Shattered Skies", games
    )
    assert game and game.game_id == 10
    assert confidence == "gamedb-exact-title"
    assert score == 1.0 and not review


def test_gamedb_does_not_cross_sequels():
    games = (CatalogueGame(20, "Cool Boarders 2", ("b" * 32,)),)
    game, _, _, _ = game_db_ra_candidates("Cool Boarders 3", games)
    assert game is None


def test_gamedb_never_promotes_demo_to_retail():
    games = (CatalogueGame(30, "~Demo~ Need for Speed Most Wanted", ("c" * 32,)),)
    game, _, _, _ = game_db_ra_candidates("Need for Speed Most Wanted", games)
    assert game is None


def test_gamedb_ambiguous_ra_matches_remain_for_review():
    games = (
        CatalogueGame(40, "Alpha Racing", ("d" * 32,)),
        CatalogueGame(41, "Alpha Racer", ("e" * 32,)),
    )
    game, method, _, review = game_db_ra_candidates("Alpha Race", games)
    assert game is None
    assert method == "gamedb-review"
    assert "RA 40" in review and "RA 41" in review


def test_gamedb_does_not_promote_duplicate_exact_titles():
    games = (
        CatalogueGame(50, "Game", ("f" * 32,)),
        CatalogueGame(51, "Game", ("0" * 32,)),
    )
    game, method, _, review = game_db_ra_candidates("Game", games)
    assert game is None
    assert method == "gamedb-ambiguous"
    assert "RA 50" in review

def test_nonstandard_ps2_serial_formats_are_identified():
    assert identify_local_release("SCPM_851.01.McDonalds Original Happy Disc.iso") == (
        "SCPM-85101", "Japan"
    )
    assert identify_local_release("USGR_000.36.Shoot Em Up Collection.iso") == (
        "USGR-00036", ""
    )


def test_curated_branding_and_regional_aliases():
    cases = (
        ("Guitar Hero: Rocks the 80s", "Guitar Hero Encore: Rocks the '80s"),
        ("Lara Croft Tomb Raider: Anniversary", "Tomb Raider: Anniversary"),
        ("Lara Croft Tomb Raider: Legend", "Tomb Raider: Legend"),
        ("Disney's The Haunted Mansion", "The Haunted Mansion"),
    )
    for local, ra in cases:
        assert comparable_title(local) == comparable_title(ra), (local, ra)


def test_aliases_do_not_collapse_unrelated_racing_games():
    assert comparable_title("Antz Extreme Racing") != comparable_title("XGIII Extreme G Racing")

def test_regional_identity_crosswalk_without_claiming_hash_compatibility():
    games = (CatalogueGame(101, "Bully", ("a" * 32,)),
             CatalogueGame(102, "Indigo Prophecy", ("b" * 32,)),
             CatalogueGame(103, "Ratchet: Deadlocked", ("c" * 32,)),
             CatalogueGame(104, "Ratchet & Clank: Up Your Arsenal", ("d" * 32,)))
    for local, expected in [
        ("Canis Canem Edit", 101),
        ("Fahrenheit", 102),
        ("Ratchet: Gladiator", 103),
        ("Ratchet & Clank 3", 104),
    ]:
        game, method, _, _ = resolve_catalogue_identity(local, games)
        assert game and game.game_id == expected
        assert method == "curated-regional-title"


def test_distinct_editions_are_not_equated_by_regional_crosswalk():
    games = (CatalogueGame(200, "Metal Gear Solid 2: Substance", ("a" * 32,)),
             CatalogueGame(201, "Need for Speed: Most Wanted Black Edition", ("b" * 32,)))
    for title in ["Metal Gear Solid 2: Sons of Liberty",
                  "Need for Speed: Most Wanted"]:
        game, _, _, _ = resolve_catalogue_identity(title, games)
        assert game is None

def test_reviewed_kof_and_blood_omen_title_variants():
    games = (
        CatalogueGame(101, "Legacy of Kain: Blood Omen 2", ("a" * 32,)),
        CatalogueGame(102, "KOF: Maximum Impact", ("b" * 32,)),
        CatalogueGame(103, "KOF: Maximum Impact 2", ("c" * 32,)),
        CatalogueGame(104, "Virtua Fighter 10th Anniversary", ("d" * 32,)),
    )
    for title, gid in [
        ("Blood Omen 2: The Legacy of Kain Series", 101),
        ("The King of Fighters: Maximum Impact", 102),
        ("The King of Fighters: Maximum Impact 2", 103),
        ("Virtua Fighter: 10th Anniversary Edition", 104),
    ]:
        game, method, _, _ = resolve_catalogue_identity(title, games)
        assert game is not None and game.game_id == gid
        assert method == "curated-regional-title"


def test_review_reasons_are_explicit_without_false_match():
    assert review_reason("MGS 2", "Metal Gear Solid 2: Substance [RA 2]") == (
        "different-edition: compare supported hash and release before replacing"
    )
    assert review_reason("EyeToy: Chat", "EyeToy: Play [RA 3]") == (
        "different-game: EyeToy titles are not interchangeable"
    )
    assert review_reason("Unknown", "") == (
        "no-RA-title-crosswalk: check RA catalogue and edition metadata"
    )
