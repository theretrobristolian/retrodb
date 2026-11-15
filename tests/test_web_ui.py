"""Read-only RetroDB v1 web routes smoke tests."""
from fastapi.testclient import TestClient
import pytest

@pytest.fixture(autouse=True)
def test_session_secret(monkeypatch):
    """Use a nonproduction signing key for isolated page-rendering tests."""
    monkeypatch.setenv("RETRODB_SESSION_SECRET", "retrodb-test-only-" + "x" * 60)

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
        for route, phrase in [("/", "Welcome to RetroDB"),("/library", "<h1>Library</h1>"),
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

def test_catalogue_title_serial_and_achievement_status(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from retrodb import web_ui
    from retrodb.web_ui import name, disc_id, ra_supported
    monkeypatch.setattr(web_ui, "RA_CACHE", tmp_path)
    web_ui._ra_achievement_counts.cache_clear()
    (tmp_path / "playstation-2.json").write_text(json.dumps([
        {"ID": 12345, "NumAchievements": 12}
    ]), encoding="utf-8")
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
    assert not ra_supported(raw)  # No platform or verified set supplied.
    assert ra_supported(raw, "playstation-2")
    (tmp_path / "playstation-2.json").write_text(json.dumps([
        {"ID": 12345, "NumAchievements": 0}
    ]), encoding="utf-8")
    web_ui._ra_achievement_counts.cache_clear()
    assert not ra_supported(raw, "playstation-2")  # Hash match alone is insufficient.

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
    from retrodb.web_ui import page, CSS
    html = page("Navigation", "<p>Test</p>").body.decode("utf-8")
    assert "class=\"mobile-nav\"" in html
    assert "header nav a,header nav button" in CSS
    assert 'action="/logout"' in html
    assert 'href="/profile"' in html
    assert 'href="/settings"' in html
    assert 'href="/online-services"' in html
    assert 'action="/logout"' in html

def test_game_detail_layout_wraps_long_paths():
    from retrodb.web_ui import CSS
    assert ".detail-field{min-width:0;max-width:100%;overflow-wrap:anywhere" in CSS
    assert ".detail .card p{overflow-wrap:anywhere" in CSS
    assert "overflow-x:clip" in CSS
    assert ".detail{columns:1}" in CSS

def test_mobile_bottom_navigation_and_compact_header():
    from retrodb.web_ui import page, CSS
    html = page("Game", "<p>Body</p>").body.decode("utf-8")
    assert 'class="mobile-nav"' in html
    assert 'class="mobile-actions"' in html
    assert 'data-nav="/profile"' in html
    assert 'data-nav="/settings"' in html
    assert "position:fixed;z-index:40;bottom:0" in CSS
    assert "env(safe-area-inset-bottom, 0px)" in CSS
    guest_html = page("Guest", "<p>Body</p>", guest=True).body.decode("utf-8")
    assert '<a href="/profile" data-nav="/profile"' not in guest_html
    assert '<a href="/settings" data-nav="/settings"' not in guest_html

def test_compact_game_ui_has_feature_and_technical_styles():
    from retrodb.web_ui import CSS
    assert ".feature-strip{" in CSS
    assert ".feature-chip{" in CSS
    assert ".technical-details summary{" in CSS
    assert ".detail{columns:2;" in CSS
    assert "header nav a:hover" in CSS

def test_disc_region_flags_are_conservative():
    from retrodb.web_ui import disc_region
    assert disc_region("SLUS-12345", "playstation-2")[0] == "🇺🇸"
    assert disc_region("SLES-12345", "playstation")[0] == "🇪🇺"
    assert disc_region("SLPM-12345", "playstation-2")[0] == "🇯🇵"
    assert disc_region("SCKA-12345", "playstation-2")[0] == "🌐"
    assert disc_region("SLUS-12345", "gamecube")[0] == "🌐"



def test_sega32x_filename_title_and_region():
    from types import SimpleNamespace
    from retrodb.web_ui import disc_region, name
    item = SimpleNamespace(filename="[32X] Virtua Racing Deluxe (J).zip",
                           ra_game_title="Virtua Racing Deluxe")
    assert name(item, "sega-32x") == "Virtua Racing Deluxe"
    assert disc_region(item.filename, "sega-32x")[0] == "🇯🇵"
    item.ra_game_title = None
    assert name(item, "sega-32x").startswith("Virtua Racing Deluxe")
    assert disc_region("[32X] Doom (Europe) [Patch].zip", "sega-32x")[0] == "🇪🇺"


def test_sega32x_clean_titles_types_and_multi_region():
    from types import SimpleNamespace
    from retrodb.web_ui import name, sega32x_type, disc_region, sega32x_ra_label
    prototype = SimpleNamespace(filename="[32X] Soulstar X (USA) (Proto).zip",
                                ra_game_title="~Prototype~ Soul Star X | Soulstar X")
    assert name(prototype, "sega-32x") == "Soulstar X"
    assert sega32x_type(prototype.filename, prototype.ra_game_title) == "Prototype"
    assert sega32x_type("[32X] Doom (Europe) [Patch Ressurrection v3.1].zip") == "Hack"
    assert sega32x_type("[32X] Virtua Racing Deluxe (U).zip") == "Retail"
    assert disc_region("[32X] Tempo (JU).zip", "sega-32x")[0] == "🇯🇵 🇺🇸"
    assert disc_region("[32X] Metal Head (Japan, USA).zip", "sega-32x")[1].startswith("Japan, USA")
    prototype.ra_game_id = None
    prototype.ra_match_status = "review"
    prototype.ra_hash_error = "local MD5 not registered; Suggested RA ID: 15989"
    assert "Unverified" not in sega32x_ra_label(prototype, False) or "not registered" in sega32x_ra_label(prototype, False)


def test_sega32x_soft_pass_status_and_verified_alternative_lookup():
    from types import SimpleNamespace
    from retrodb.web_ui import (sega32x_soft_pass, sega32x_alternative_paths,
                                sega32x_ra_label, sega32x_verified_alternative)
    item = SimpleNamespace(
        id=7, source_id=2, platform_id=10, filename="[32X] Virtua Racing Deluxe (U).zip",
        ra_game_id=None, ra_match_status="review",
        ra_hash_error=("This ZIP is not RA hash-matched; compatible same-game ZIP exists locally; "
                       "Compatible alternate ZIP: Virtua Racing Deluxe (Japan).zip; "
                       "Suggested RA ID: 11823"))
    assert sega32x_soft_pass(item)
    assert sega32x_alternative_paths(item) == ["Virtua Racing Deluxe (Japan).zip"]
    assert "alternative exists" in sega32x_ra_label(item, False)
    verified = SimpleNamespace(id=19, filename="Virtua Racing Deluxe (Japan).zip")
    class Lookup:
        query = None
        def scalar(self, query):
            self.query = query
            return verified
    db = Lookup()
    assert sega32x_verified_alternative(db, item) is verified
    sql = str(db.query.compile())
    assert "relative_path" in sql and "ra_game_id" in sql
    assert "source_id" in sql and "platform_id" in sql
    assert "is_missing" in sql and "ra_match_status" in sql
    assert "roms/sega/32x/Virtua Racing Deluxe (Japan).zip" in str(
        db.query.compile().params.values())


def test_sega32x_soft_pass_never_inferred_from_title_only():
    from types import SimpleNamespace
    from retrodb.web_ui import (sega32x_soft_pass, sega32x_verified_alternative,
                                sega32x_alternative_paths, sega32x_ra_label)
    item = SimpleNamespace(
        id=7, source_id=2, platform_id=10, ra_game_id=None,
        ra_match_status="review", ra_hash_error="Suggested RA ID: 11823")
    class NoQueries:
        def scalar(self, query):
            raise AssertionError("A title suggestion must not trigger alternative lookup")
    assert not sega32x_soft_pass(item)
    assert sega32x_alternative_paths(item) == []
    assert sega32x_verified_alternative(NoQueries(), item) is None
    assert "not registered" in sega32x_ra_label(item, False)
    item.ra_match_status = "matched"
    item.ra_game_id = 11823
    assert not sega32x_soft_pass(item)
    assert sega32x_ra_label(item, False) == "Verified ROM hash; no achievement set"
