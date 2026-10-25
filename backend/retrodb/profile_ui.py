"""Read-only RetroAchievements profile for an explicitly linked RetroDB user.

Links are administrator-owned; public RA lookup does not prove account ownership.
No RA passwords or API keys are accepted from browsers.
"""
from __future__ import annotations

import json
import os
import re
import socket
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from retrodb.session_auth import COOKIE, user_from_cookie, csrf_token

router = APIRouter(include_in_schema=False)
LINKS = Path("/etc/retrodb/profile-links.json")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROFILE_API = "https://retroachievements.org/API/API_GetUserProfile.php"

def linked_user(local_user: str) -> str | None:
    try:
        links = json.loads(LINKS.read_text(encoding="utf-8"))
        if not isinstance(links, dict):
            return None
        value = links.get(local_user)
        if isinstance(value, dict):
            value = value.get("ra_username")
        return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else None
    except (OSError, ValueError, TypeError):
        return None

@lru_cache(maxsize=96)
def _fetch_profile(username: str, key: str) -> dict:
    # Cache in-process at most one worker lifetime, rather than leaking secrets
    # to disk. A restart refreshes values.
    with httpx.Client(timeout=6, follow_redirects=False) as client:
        response = client.get(PROFILE_API, params={"u": username, "y": key},
                              headers={"User-Agent": "RetroDB/0.1"})
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict) or not result.get("User"):
        raise ValueError("User profile unavailable")
    return result

def avatar_url(pic: object) -> str | None:
    # Only official RA origin and a restricted image pathname; no URL injection.
    if not isinstance(pic, str) or not pic.startswith("/UserPic/"):
        return None
    if not re.fullmatch(r"/UserPic/[A-Za-z0-9_.-]{1,128}", pic):
        return None
    return "https://retroachievements.org" + pic

def linked_xerabora(local_user: str) -> str | None:
    try:
        data = json.loads(LINKS.read_text(encoding="utf-8"))
        row = data.get(local_user) if isinstance(data, dict) else None
        target = row.get("xerabora_profile") if isinstance(row, dict) else None
        return target if isinstance(target, str) and IDENTIFIER.fullmatch(target) else None
    except (OSError, ValueError, TypeError):
        return None

def switch_xerabora(account: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(45)
        conn.connect("/run/retrodb-xerabora-switch.sock")
        conn.sendall(json.dumps({"account": account}).encode("utf-8"))
        result = json.loads(conn.recv(4096).decode("utf-8"))
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("xeRAbora profile switch failed. Check helper logs.")
    return str(result.get("message", "Profile activated."))

@router.post("/profile/switch", response_class=HTMLResponse)
async def activate_xerabora(request: Request):
    user = user_from_cookie(request.cookies.get(COOKIE, ""))
    if not user or user == "__retrodb_guest__":
        return HTMLResponse("Authentication required", status_code=403)
    if not linked_xerabora(user):
        return HTMLResponse("No approved xeRAbora profile is linked to this account.", status_code=403)
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        return HTMLResponse("Invalid request", status_code=415)
    data = await request.body()
    if len(data) > 1024:
        return HTMLResponse("Invalid request", status_code=413)
    from urllib.parse import parse_qs
    from retrodb.session_auth import valid_csrf
    values = parse_qs(data.decode("utf-8", "replace"), keep_blank_values=True)
    if not valid_csrf(values.get("csrf_token", [""])[0]) or values.get("confirm", [""])[0] != "SWITCH":
        return HTMLResponse("Switch confirmation expired or not provided. Reload your profile and try again.",
                            status_code=403, headers={"Cache-Control": "no-store"})
    from retrodb.web_ui import page
    try:
        outcome = switch_xerabora(user)
    except (OSError, ValueError, RuntimeError, socket.timeout):
        return page("xeRAbora", '<h1>Switch not available</h1><p>The restricted switch helper is not running or the approved player could not be activated.</p><p>Check <code>journalctl -u retrodb-xerabora-switch.service</code> on the server.</p><a class="btn" href="/profile">Back to profile</a>')
    # Redirect-after-POST prevents reload/back from re-submitting a service restart.
    state = "already" if outcome.startswith("Already active") else "switched"
    return RedirectResponse("/profile?" + urlencode({"xerabora": state}), status_code=303,
                            headers={"Cache-Control": "no-store"})

@router.get("/profile", response_class=HTMLResponse)
def my_profile(request: Request):
    # Permission check is duplicated here; middleware remains the primary gate.
    user = user_from_cookie(request.cookies.get(COOKIE, ""))
    if not user or user == "__retrodb_guest__":
        return HTMLResponse("Authentication required", status_code=403)
    # Local import prevents circularity with web_ui's layout helper.
    from retrodb.web_ui import page
    state = request.query_params.get("xerabora", "")
    status_html = (
        '<div class="card" role="status" style="border-color:#638f65;margin-bottom:18px"><h2>✓ Profile switched</h2><p>xeRAbora has restarted with your selected player. Restart the PS2 / relaunch OPL-RA and check your MemCard Pro 2 card image.</p></div>'
        if state == "switched" else
        '<div class="card" role="status" style="margin-bottom:18px"><h2>✓ Your profile is already selected</h2><p>No service restart was necessary.</p></div>'
        if state == "already" else ""
    )
    ra_name = linked_user(user)
    if not ra_name:
        body = (f'<h1>My profile</h1><p>Signed in to RetroDB as <strong>{escape(user)}</strong>.</p>'
                '<div class="card"><h2>Connect RetroAchievements</h2>'
                '<p class="muted">Your RetroAchievements account has not been linked yet. '
                'An administrator can associate your local RetroDB account with your RA username. '
                'No RA password is needed.</p></div>')
        return page("My profile", status_html + body)
    key = os.environ.get("RETRODB_RA_API_KEY", "").strip()
    data = {}
    warning = ""
    if key:
        try:
            data = _fetch_profile(ra_name, key)
        except (httpx.HTTPError, ValueError):
            warning = "<p class='muted'>Live RetroAchievements information is temporarily unavailable.</p>"
    else:
        warning = "<p class='muted'>Configure the server-side RetroAchievements Web API key to show live profile statistics.</p>"
    display = str(data.get("User") or ra_name)
    # RA can change usernames; only use returned URL-safe username in links.
    if not IDENTIFIER.fullmatch(display):
        display = ra_name
    avatar = avatar_url(data.get("UserPic"))
    picture = (f'<img alt="RetroAchievements profile picture" src="{escape(avatar,quote=True)}" '
               'width="96" height="96" style="border-radius:16px;object-fit:cover">'
               if avatar else '')
    points = data.get("TotalPoints", "—")
    softcore = data.get("TotalSoftcorePoints", "—")
    motto = str(data.get("Motto") or "")
    def number(value):
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "—"
    body = (status_html + f'<div class="crumb"><a href="/">Consoles</a> / My profile</div><h1>My profile</h1>'
            f'<div class="card" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">'
            f'{picture}<div><div class="eyebrow">RetroAchievements</div><h2>{escape(display)}</h2>'
            f'<p class="muted">{escape(motto[:250])}</p>'
            f'<a class="btn" href="https://retroachievements.org/user/{quote(display)}" '
            'target="_blank" rel="noopener noreferrer">View RA profile ↗</a></div></div>'
            f'<div class="grid" style="margin-top:18px"><div class="card"><div class="label">Hardcore points</div>'
            f'<div class="metric">{number(points)}</div></div>'
            f'<div class="card"><div class="label">Softcore points</div>'
            f'<div class="metric">{number(softcore)}</div></div></div>'
            f'{warning}<div class="card" style="margin-top:18px"><h2>xeRAbora</h2>'
            '<p>The xeRAbora server uses a shared active PS2 player. Switching can interrupt an active game.</p>'
            + (f'<div class="player-switch"><div><div class="eyebrow">Linked player</div>'
               f'<h3 style="margin:6px 0">{escape(linked_xerabora(user) or "")}</h3>'
               '<p class="muted">Select this player for your connected PS2.</p></div>'
               '<button class="btn" type="button" id="open-player-switch">Use this player</button></div>'
               '<dialog id="player-switch-dialog" class="switch-dialog" aria-labelledby="switch-dialog-title">'
               '<form method="post" action="/profile/switch" id="player-switch-form">'
               f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'
               '<input type="hidden" name="confirm" value="SWITCH">'
               '<div class="eyebrow">Confirm player change</div>'
               '<h2 id="switch-dialog-title">Switch PS2 player?</h2>'
               f'<p>Activate <strong>{escape(linked_xerabora(user) or "")}</strong> on the xeRAbora server.</p>'
               '<p class="muted">This may disconnect an active game. Afterwards restart the PS2 or relaunch OPL-RA, and select the right memory card.</p>'
               '<div class="switch-actions"><button type="button" class="btn" id="cancel-player-switch" style="background:transparent">Cancel</button>'
               '<button class="btn" type="submit" id="confirm-player-switch">Switch player</button></div>'
               '</form></dialog>'
               '<script>(function(){'
               'const dialog=document.getElementById("player-switch-dialog");'
               'const open=document.getElementById("open-player-switch");'
               'const cancel=document.getElementById("cancel-player-switch");'
               'const form=document.getElementById("player-switch-form");'
               'const submit=document.getElementById("confirm-player-switch");'
               'if(!dialog||!open||!form)return;'
               'open.addEventListener("click",()=>{if(dialog.showModal)dialog.showModal();else dialog.setAttribute("open","");});'
               'cancel.addEventListener("click",()=>{if(dialog.close)dialog.close();else dialog.removeAttribute("open");});'
               'form.addEventListener("submit",()=>{submit.disabled=true;submit.textContent="Switching player…";open.disabled=true;});'
               '})();</script>'
               if linked_xerabora(user) else
               '<p class="muted">An administrator must approve a xeRAbora player mapping before web switching is available.</p>') + '</div>')
    return page("My profile", body)
