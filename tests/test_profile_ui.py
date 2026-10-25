"""Profile page security and RetroAchievements identity mapping tests."""
import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
from retrodb.main import app
from retrodb import session_auth, profile_ui

def test_guest_cannot_access_profile(monkeypatch):
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "__retrodb_guest__")
    client = TestClient(app)
    assert client.get("/profile").status_code == 403

def test_linked_player_profile_renders_avatar_and_points(tmp_path, monkeypatch):
    config = tmp_path / "profile-links.json"
    config.write_text(json.dumps({"player": "PoodingPower"}))
    monkeypatch.setattr(profile_ui, "LINKS", config)
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "player")
    monkeypatch.setattr(profile_ui, "_fetch_profile", lambda u,k: {
        "User": "PoodingPower", "UserPic": "/UserPic/PoodingPower.png",
        "TotalPoints": 1234, "TotalSoftcorePoints": 500, "Motto": "Happy gaming"})
    monkeypatch.setenv("RETRODB_RA_API_KEY", "test-key-not-real")
    response = TestClient(app).get("/profile")
    assert response.status_code == 200
    assert "PoodingPower" in response.text
    assert "1,234" in response.text
    assert "https://retroachievements.org/UserPic/PoodingPower.png" in response.text
    assert "My profile" in response.text

def test_profile_avatar_url_not_arbitrary_host():
    assert profile_ui.avatar_url("https://evil.invalid/a.png") is None
    assert profile_ui.avatar_url("//evil.invalid/a.png") is None
    assert profile_ui.avatar_url("/UserPic/../something") is None
    assert profile_ui.avatar_url("/UserPic/test.png") == "https://retroachievements.org/UserPic/test.png"

def test_unlinked_user_not_implicitly_linked(tmp_path, monkeypatch):
    config = tmp_path / "profile-links.json"
    config.write_text("{}")
    monkeypatch.setattr(profile_ui, "LINKS", config)
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "player")
    response = TestClient(app).get("/profile")
    assert response.status_code == 200
    assert "has not been linked" in response.text
