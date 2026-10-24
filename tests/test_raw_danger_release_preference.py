"""RA 5616 should recommend the playable English European release."""
from retrodb.retroachievements_match import preferred_release


def test_raw_danger_prefers_europe_even_with_japanese_hash():
    details = [
        {"Name": "Zettai Zetsumei Toshi 2 - Itetsuita Kioku-tachi (Japan)",
         "MD5": "a" * 32, "Labels": ["redump"]},
        {"Name": "Raw Danger! (Europe)", "MD5": "b" * 32, "Labels": ["redump"]},
    ]
    name, region, digest, *_ = preferred_release(details, 5616)
    assert name == "Raw Danger! (Europe)"
    assert region == "Europe"
    assert digest == "b" * 32


def test_non_raw_danger_keeps_existing_preference():
    details = [
        {"Name": "Example (Japan)", "MD5": "a" * 32, "Labels": ["redump"]},
        {"Name": "Example (Europe)", "MD5": "b" * 32, "Labels": ["redump"]},
    ]
    assert preferred_release(details, 1234)[1] == "Japan"
