"""Guest mode: catalogue GETs only, never management or profile operations."""
import re
from fastapi.testclient import TestClient
from retrodb import session_auth as auth
from retrodb.main import app
from retrodb.database import get_session

class EmptyResult:
    def all(self): return []
class EmptyDB:
    def execute(self, statement): return EmptyResult()
    def scalar(self, statement): return 0
    def scalars(self, statement): return EmptyResult()
    def get(self, model, key): return None

def test_guest_mode_is_catalogue_only(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-only-signing-secret")
    app.dependency_overrides[get_session] = lambda: EmptyDB()
    try:
        client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
        page = client.get("/login")
        assert page.status_code == 200
        assert "View as guest" in page.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = client.post("/guest", data={"csrf_token": csrf})
        assert response.status_code == 303
        assert "Secure" in response.headers["set-cookie"]
        home = client.get("/")
        assert home.status_code == 200
        assert "All games" in home.text
        assert 'href="/management"' not in home.text
        assert 'href="/online-services"' not in home.text
        assert client.get("/library").status_code == 200
        assert client.get("/management").status_code == 403
        assert client.get("/online-services").status_code == 403
        assert client.get("/api/v1/platforms").status_code == 403
        out = client.post("/logout")
        assert out.status_code == 303
        assert out.headers["location"] == "/login"
    finally:
        app.dependency_overrides.clear()

def test_guest_rejects_missing_csrf(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-only-signing-secret")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house")
    assert client.post("/guest", data={}).status_code == 403
