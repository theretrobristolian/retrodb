"""RetroDB HTTPS session login; compatible with existing bcrypt htpasswd users.

No privileged operations, no credentials in cookies, and no unprotected app API.
"""
import base64
import hashlib
import hmac
import html
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

import bcrypt
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

router = APIRouter(include_in_schema=False)
COOKIE = "retrodb_session"
LIFETIME = 30 * 86400
PUBLIC = ("/login", "/favicon.svg", "/favicon.ico", "/apple-touch-icon.png",
          "/manifest.webmanifest", "/icons/")
USERS = Path("/etc/retrodb/web-users-app.htpasswd")

def secret():
    key = os.getenv("RETRODB_SESSION_SECRET", "")
    if len(key) < 48:
        raise RuntimeError("RETRODB_SESSION_SECRET must be configured by deploy")
    return key.encode()

def signature(payload):
    return hmac.new(secret(), payload.encode(), hashlib.sha256).hexdigest()

def issue(username):
    body = base64.urlsafe_b64encode(f"{username}|{int(time.time()) + LIFETIME}".encode()).decode().rstrip("=")
    return body + "." + signature(body)

def user_from_cookie(token):
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(signature(body), sig):
            return None
        name, expiry = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode().split("|")
        if not name or int(expiry) <= time.time():
            return None
        # Removing a user from htpasswd also invalidates their session.
        if not any(line.split(":", 1)[0] == name for line in USERS.read_text().splitlines() if ":" in line):
            return None
        return name
    except (ValueError, UnicodeError, OSError):
        return None

def verify_password(username, password):
    if not username or len(username) > 64 or not password or len(password) > 1024:
        return False
    try:
        for line in USERS.read_text().splitlines():
            if ":" not in line: continue
            name, hashed = line.split(":", 1)
            if hmac.compare_digest(name, username) and hashed.startswith("$2"):
                return bcrypt.checkpw(password.encode(), hashed.encode())
    except (OSError, ValueError):
        return False
    return False

LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#10192d"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="RetroDB">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<title>Sign in · RetroDB</title>
<style>body{background:#0b1020;color:#eaf0fc;font:16px system-ui;display:grid;min-height:95vh;place-items:center;margin:0}
main{width:min(90%,390px);padding:30px;background:#151f32;border:1px solid #334364;border-radius:20px}
h1{margin:0 0 10px}p{color:#b6c5da}input,button{box-sizing:border-box;width:100%;margin:8px 0 14px;padding:14px;border-radius:10px;font:inherit}
input{background:#0b1020;border:1px solid #546780;color:white}button{background:#4f81d9;color:white;border:0;cursor:pointer}</style>
</head><body><main><h1>◈ RetroDB</h1><p>Sign in to your game library. Stay signed in on this device for up to 30 days.</p>
__ERROR__<form action="/login" method="post"><label>Username<input name="username" required autocomplete="username"></label>
<label>Password<input type="password" name="password" required autocomplete="current-password"></label>
<input type="hidden" name="next" value="__NEXT__"><button>Sign in</button></form>
<p>Only use on your trusted home network over HTTPS.</p></main></body></html>"""

@router.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/"):
    return HTMLResponse(LOGIN_HTML.replace("__ERROR__", "").replace("__NEXT__", html.escape(safe_next(next), quote=True)), headers={"Cache-Control":"no-store"})

def safe_next(value):
    if not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(c)<32 for c in value):
        return "/"
    return value

def valid_origin(request):
    origin = request.headers.get("origin")
    if origin:
        return origin == "https://retrodb.it.gattaca.house"
    referer = request.headers.get("referer", "")
    return referer.startswith("https://retrodb.it.gattaca.house/")

@router.post("/login")
async def login_action(request: Request):
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        return Response(status_code=415)
    # Origin protection for credential submission.
    if not valid_origin(request):
        return Response("Invalid request origin", status_code=403)
    data = await request.body()
    if len(data) > 4096: return Response(status_code=413)
    from urllib.parse import parse_qs
    values = parse_qs(data.decode("utf-8", "replace"), keep_blank_values=True)
    username = values.get("username", [""])[0]
    password = values.get("password", [""])[0]
    target = safe_next(values.get("next", ["/"])[0])
    if not verify_password(username, password):
        return HTMLResponse(LOGIN_HTML.replace("__ERROR__", '<p role="alert" style="color:#ff9b9b">Incorrect username or password.</p>').replace("__NEXT__", html.escape(target, quote=True)), status_code=401, headers={"Cache-Control":"no-store"})
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(COOKIE, issue(username), httponly=True, secure=True, samesite="lax",
                        max_age=LIFETIME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response

@router.post("/logout")
async def logout(request: Request):
    if request.headers.get("origin") != "https://retrodb.it.gattaca.house":
        return Response(status_code=403)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response

async def enforce_session(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC or path.startswith("/icons/"):
        return await call_next(request)
    if not user_from_cookie(request.cookies.get(COOKIE, "")):
        if path.startswith("/api/") or path in ("/health", "/live"):
            return Response("Authentication required", status_code=401)
        if request.method != "GET":
            return Response("Authentication required", status_code=401)
        next_path = path + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse("/login?next=" + quote(safe_next(next_path), safe=""), status_code=303)
    return await call_next(request)
