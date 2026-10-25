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
    assert client.post("/login", data=body, headers={"sec-fetch-site":"cross-site"}).status_code == 401
    body["csrf_token"] = "invalid"
    assert client.post("/login", data=body).status_code == 403

def test_safari_null_origin_and_guest_form(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    headers = {"Origin": "null", "Sec-Fetch-Site": "cross-site"}
    response = client.post("/guest", data={"csrf_token": token}, headers=headers)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

def test_safari_guest_logout_with_null_origin(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
    entered = client.post("/guest", data={"csrf_token": token}, headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"})
    assert entered.status_code == 303
    home = client.get("/")
    assert home.status_code == 200
    assert "Leave guest view" in home.text
    signout_token = re.search(r'<form method="post" action="/logout"[^>]*><input type="hidden" name="csrf_token" value="([^"]+)"', home.text).group(1)
    logged_out = client.post("/logout", data={"csrf_token": signout_token},
                             headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"})
    assert logged_out.status_code == 303
    assert logged_out.headers["location"] == "/login"
    assert 'retrodb_session=' in logged_out.headers["set-cookie"]
    assert 'Max-Age=0' in logged_out.headers["set-cookie"]
    assert client.get("/").status_code == 303

def test_logout_rejects_unsigned_post_even_with_guest_cookie(monkeypatch):
    monkeypatch.setattr(auth, "secret", lambda: b"test-secret-only-not-for-production")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
    assert client.post("/guest", data={"csrf_token": token}).status_code == 303
    bad = client.post("/logout", data={"csrf_token": "invalid"})
    assert bad.status_code == 403
    assert "text/html" in bad.headers["content-type"]
