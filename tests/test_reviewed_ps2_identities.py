"""Review crosswalk persists decisions but refuses edition-ambiguous mappings."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.retroachievements_match import load_reviewed_ps2_identities


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
