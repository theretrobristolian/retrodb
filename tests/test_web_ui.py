"""Read-only RetroDB v1 web routes smoke tests."""
from fastapi.testclient import TestClient
from retrodb.main import app
from retrodb.database import get_session

class Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows

class Database:
    def execute(self, statement): return Result([])
    def scalar(self, statement): return 0
    def scalars(self, statement): return Result([])
    def get(self, model, key): return None

def stub():
    yield Database()

def test_pages_exist_without_mutation(monkeypatch):
    import retrodb.session_auth as auth
    monkeypatch.setattr(auth, "user_from_cookie", lambda _: "test-player")
    app.dependency_overrides[get_session] = stub
    try:
        client = TestClient(app)
        for route, phrase in [("/", "Choose a console"),("/library", "All games"),
                              ("/management", "Library management"),("/online-services", "XLink Kai")]:
            result = client.get(route)
            assert result.status_code == 200
            assert phrase in result.text
            assert "RetroDB" in result.text
        assert client.get("/game/999999").status_code == 404
        assert client.post("/management").status_code == 405
    finally:
        app.dependency_overrides.clear()

def test_online_details_never_claims_current_server_availability():
    from retrodb.web_ui import online_details
    shown = online_details({
        "historical_online":"YES", "original_host":"GameSpy",
        "dns_compatible":"YES", "dns_address_or_provider":"Community DNS",
        "xlink_kai":"YES", "requirements":"DNAS setup",
    })
    assert "GameSpy" in shown
    assert "UNVERIFIED" in shown
    assert "DNAS setup" in shown

def test_web_app_branding_assets():
    client = TestClient(app)
    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text
    for route in ("/apple-touch-icon.png", "/icons/icon-192.png", "/icons/icon-512.png"):
        image = client.get(route)
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(bytes.fromhex("89504e470d0a1a0a"))
    manifest = client.get("/manifest.webmanifest")
    assert manifest.json()["short_name"] == "RetroDB"
    assert manifest.json()["display"] == "standalone"

def test_https_session_login_persists_without_basic_auth(tmp_path, monkeypatch):
    import bcrypt
    import retrodb.session_auth as auth
    users = tmp_path / "users.htpasswd"
    users.write_text("player:" + bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode() + "\n")
    monkeypatch.setattr(auth, "USERS", users)
    monkeypatch.setenv("RETRODB_SESSION_SECRET", "secure-test-secret-" + "x"*60)
    app.dependency_overrides[get_session] = stub
    try:
        with TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False) as client:
            assert client.get("/").status_code == 303
            assert client.get("/login").status_code == 200
            import re
            token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
            response = client.post("/login", data={"username":"player","password":"correct-horse","next":"/","csrf_token":token},
                                   headers={"origin":"https://retrodb.it.gattaca.house"})
            assert response.status_code == 303
            assert "Secure" in response.headers["set-cookie"]
            assert "HttpOnly" in response.headers["set-cookie"]
            assert client.get("/").status_code == 200
            token = re.search(r'<form method="post" action="/logout"[^>]*><input type="hidden" name="csrf_token" value="([^"]+)"', client.get("/").text).group(1)
            logout = client.post("/logout", data={"csrf_token":token}, headers={"origin":"https://retrodb.it.gattaca.house"})
            assert logout.status_code == 303
            assert client.get("/").status_code == 303
    finally:
        app.dependency_overrides.clear()

def test_catalogue_title_serial_and_achievement_status():
    from types import SimpleNamespace
    from retrodb.web_ui import name, disc_id, ra_supported
    raw = SimpleNamespace(filename="Ratchet_&_Clank_(Europe)_SLES_509.16.iso",
                          relative_path="PS2/Ratchet_&_Clank_(Europe)_SLES_509.16.iso",
                          ra_game_title=None, ra_game_id=None, ra_match_status="unknown")
    assert "Ratchet" in name(raw)
    assert "SLES" not in name(raw)
    assert disc_id(raw) == "SLES-50916"
    assert not ra_supported(raw)
    raw.ra_game_title = "Ratchet & Clank"
    raw.ra_game_id = 12345
    raw.ra_match_status = "matched"
    assert name(raw) == "Ratchet & Clank"
    assert ra_supported(raw)

def test_catalogue_controls_render(monkeypatch):
    import retrodb.session_auth as auth
    monkeypatch.setattr(auth, "user_from_cookie", lambda _: "test-player")
    app.dependency_overrides[get_session] = stub
    try:
        client = TestClient(app)
        result = client.get("/library?sort=title&ra=all")
        assert result.status_code == 200
        assert 'data-toggle="disc"' in result.text
        assert "Disc ID" in result.text
        assert "Achievements" in result.text
        assert "library-scroll" in result.text
    finally:
        app.dependency_overrides.clear()

def test_gamedb_name_lookup_takes_precedence_over_abbreviated_filename(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from retrodb import web_ui
    from retrodb.providers.gamedb import cache_file
    monkeypatch.setattr(web_ui, "GAMEDB_CACHE", tmp_path)
    web_ui._gamedb_titles.cache_clear()
    (tmp_path / "playstation-2.json").write_text(json.dumps({
        "SLES-52541": "Grand Theft Auto: San Andreas",
        "SLES-54622": "Grand Theft Auto: Vice City Stories"
    }), encoding="utf-8")
    for serial, expected in (
        ("SLES-52541", "Grand Theft Auto: San Andreas"),
        ("SLES-54622", "Grand Theft Auto: Vice City Stories"),
    ):
        item = SimpleNamespace(filename="GTA VCS " + serial + ".iso",
                               relative_path="roms/sony/playstation2/GTA VCS " + serial + ".iso",
                               ra_game_title=None)
        assert web_ui.name(item, "playstation-2") == expected
    assert web_ui.name(item, "playstation") != expected


def test_mobile_catalogue_css_and_trophy_only_status():
    from retrodb.web_ui import CSS
    assert ".library-scroll table{min-width:0;table-layout:fixed}" in CSS
    assert "overflow-wrap:anywhere" in CSS
    assert ".ra-icon.no::after" in CSS

def test_mobile_navigation_wraps_without_horizontal_overflow():
    from retrodb.web_ui import page
    html = page("Navigation", "<p>Test</p>").body.decode("utf-8")
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in html
    assert "header nav form button" in html
    assert 'href="/profile"' in html
    assert 'href="/management"' in html
    assert 'href="/online-services"' in html
    assert 'action="/logout"' in html

def test_game_detail_layout_wraps_long_paths():
    from retrodb.web_ui import CSS
    assert ".detail-field{min-width:0;max-width:100%;overflow-wrap:anywhere" in CSS
    assert ".detail .card p{overflow-wrap:anywhere" in CSS
    assert "overflow-x:clip" in CSS
    assert "grid-template-columns:minmax(0,1fr)" in CSS
