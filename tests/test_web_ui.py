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

def test_pages_exist_without_mutation():
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
