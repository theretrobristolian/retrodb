"""Regression checks for Safari form submissions with suppressed referrers."""
import re
from fastapi.testclient import TestClient
from retrodb.main import app
from retrodb import session_auth as auth

def test_safari_login_without_origin_or_referer(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    monkeypatch.setattr(auth, "verify_password", lambda username, password: username == "test" and password == "good")
    monkeypatch.setattr(auth, "user_from_cookie", lambda cookie: "test" if cookie else None)
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    page = client.get("/login")
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = client.post("/login", data={"username":"test","password":"good","next":"/","csrf_token":token}, headers=headers)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "retrodb_session=" in response.headers["set-cookie"]

def test_login_rejects_missing_token_and_cross_site(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house")
    body = {"username":"test","password":"wrong","next":"/"}
    assert client.post("/login", data=body).status_code == 403
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
    body["csrf_token"] = token
    assert client.post("/login", data=body, headers={"sec-fetch-site":"cross-site"}).status_code == 403

def test_safari_null_origin_and_guest_form(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    headers = {"Origin": "null", "Sec-Fetch-Site": "cross-site"}
    response = client.post("/guest", data={"csrf_token": token}, headers=headers)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
