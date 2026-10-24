"""Review crosswalk persists decisions but refuses edition-ambiguous mappings."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.retroachievements_match import load_reviewed_ps2_identities, load_reviewed_ps2_no_listings, load_reviewed_ps2_alternatives


def test_reviewed_disc_ids_are_available():
    reviewed = load_reviewed_ps2_identities()
    assert reviewed["SCES-52530"] == 20494
    assert reviewed["SCES-53286"] == 19239
    assert reviewed["SLES-53501"] == 3143


def test_different_editions_stay_manual():
    reviewed = load_reviewed_ps2_identities()
    assert "SLES-50383" not in reviewed  # Sons of Liberty vs Substance
    assert "SLES-53557" not in reviewed  # Normal vs Black Edition
    assert "SLES-53138" not in reviewed  # Remixed vs original
    assert "SCES-50612" not in reviewed  # Superseded identity


def test_user_no_listing_decisions_are_preserved():
    unlisted = load_reviewed_ps2_no_listings()
    assert len(unlisted) == 33
    assert "SLES-52366" in unlisted
    assert "USGR-00036" in unlisted
    assert "SCES-52530" not in unlisted


def test_new_confirmed_regional_identifications():
    reviewed = load_reviewed_ps2_identities()
    assert reviewed["SLES-52118"] == 2679
    assert reviewed["SLES-53138"] == 19930
    unlisted = load_reviewed_ps2_no_listings()
    assert "SCES-52154" in unlisted
    assert "SCES-50612" in unlisted


def test_pal_tokyo_racer_and_nfs_alternative_are_distinct():
    reviewed = load_reviewed_ps2_identities()
    alternatives = load_reviewed_ps2_alternatives()
    assert reviewed["SLES-50115"] == 20774
    assert "SLES-53557" not in reviewed
    assert alternatives["SLES-53557"] == 7788


def test_final_six_triage_preserves_distinct_game_editions():
    unlisted = load_reviewed_ps2_no_listings()
    for serial in ("SCES-54496", "SLUS-21256", "SLES-53599", "SLES-53598", "SLES-52876"):
        assert serial in unlisted
    alternatives = load_reviewed_ps2_alternatives()
    reviewed = load_reviewed_ps2_identities()
    assert alternatives["SLES-50383"] == 2787
    assert "SLES-50383" not in reviewed
    assert "SCES-54496" not in reviewed
