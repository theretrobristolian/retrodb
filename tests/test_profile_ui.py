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

def test_switch_requires_admin_approved_profile_and_csrf(tmp_path, monkeypatch):
    import re
    mapping = tmp_path / "profile-links.json"
    mapping.write_text(json.dumps({"player": {
        "ra_username": "PoodingPower", "xerabora_profile": "PoodingPower"}}))
    monkeypatch.setattr(profile_ui, "LINKS", mapping)
    monkeypatch.setattr(session_auth, "secret", lambda: b"testing-only-not-production")
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "player")
    monkeypatch.setattr(profile_ui, "user_from_cookie", lambda _: "player")
    monkeypatch.setenv("RETRODB_RA_API_KEY", "")
    switched = []
    monkeypatch.setattr(profile_ui, "switch_xerabora",
                        lambda username: switched.append(username) or "Activated")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    assert client.post("/profile/switch", data={"confirm": "SWITCH"}).status_code == 403
    page = client.get("/profile")
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post("/profile/switch", data={"csrf_token": token, "confirm": "SWITCH"},
                           headers={"Origin": "null"})
    assert response.status_code == 303
    assert response.headers["location"] == "/profile?xerabora=switched"
    assert switched == ["player"]

def test_switch_without_admin_mapping_is_denied(tmp_path, monkeypatch):
    config = tmp_path / "profile-links.json"
    config.write_text(json.dumps({"player": {"ra_username": "PoodingPower"}}))
    monkeypatch.setattr(profile_ui, "LINKS", config)
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "player")
    monkeypatch.setattr(profile_ui, "user_from_cookie", lambda _: "player")
    response = TestClient(app).post("/profile/switch", data={"confirm": "SWITCH"})
    assert response.status_code == 403

def test_switch_already_active_redirects_to_correct_status(tmp_path, monkeypatch):
    import re
    config = tmp_path / "profile-links.json"
    config.write_text(json.dumps({"player": {"ra_username": "PoodingPower", "xerabora_profile": "PoodingPower"}}))
    monkeypatch.setattr(profile_ui, "LINKS", config)
    monkeypatch.setattr(session_auth, "secret", lambda: b"testing-only-not-production")
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "player")
    monkeypatch.setattr(profile_ui, "user_from_cookie", lambda _: "player")
    monkeypatch.setenv("RETRODB_RA_API_KEY", "")
    monkeypatch.setattr(profile_ui, "switch_xerabora", lambda u: "Already active; no restart needed")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    profile = client.get("/profile")
    assert 'id="player-switch-dialog"' in profile.text
    assert 'id="open-player-switch"' in profile.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', profile.text).group(1)
    result = client.post("/profile/switch", data={"csrf_token": token, "confirm": "SWITCH"})
    assert result.status_code == 303
    assert result.headers["location"] == "/profile?xerabora=already"
    assert "already selected" in client.get("/profile?xerabora=already").text
