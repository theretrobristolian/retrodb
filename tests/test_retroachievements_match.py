import json
import pytest
from retrodb.retroachievements_match import MatchError, extract_hash, load_hash_catalogue

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
