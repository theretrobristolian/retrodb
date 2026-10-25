"""Artwork sources are keyed by verified disc serial and RA image paths."""
from retrodb import artwork

def test_psbbn_disc_serial_normalisation():
    assert artwork.serial_key("SLUS-20959.iso") == "SLUS_209.59"
    assert artwork.serial_key("SLES_500.09") == "SLES_500.09"
    assert artwork.serial_key("not-a-disc") is None

def test_only_official_ra_artwork_paths():
    assert artwork.ra_image("/Images/117775.png") == "https://media.retroachievements.org/Images/117775.png"
    assert artwork.ra_image("https://bad.example/image.png") is None
    assert artwork.ra_image("//bad.example/image.png") is None

def test_invalid_artwork_serial_not_downloaded():
    from fastapi.testclient import TestClient
    from retrodb.main import app
    from retrodb import session_auth
    from unittest.mock import patch
    with patch.object(session_auth, "user_from_cookie", return_value="__retrodb_guest__"):
        response = TestClient(app).get("/art/psbbn/invalid")
    assert response.status_code == 404
