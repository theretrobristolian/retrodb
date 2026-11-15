"""Authenticated, admin-approved server controls for the RetroDB Settings page.

The web process cannot call systemctl directly. A restricted, root-owned UNIX
socket helper performs only explicitly allowlisted operations.
"""
from __future__ import annotations

import json
import socket
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from retrodb.session_auth import COOKIE, csrf_token, user_from_cookie, valid_csrf

router = APIRouter(include_in_schema=False)
ADMINS = Path("/etc/retrodb/server-admins.json")
HELPER_SOCKET = "/run/retrodb-xerabora-switch.sock"
ACTIONS = {
    "restart-xerabora": ("RESTART", "Restart xeRAbora"),
    "reboot-server": ("REBOOT", "Restart server"),
}


def is_server_admin(user: str | None) -> bool:
    if not user or user == "__retrodb_guest__":
        return False
    try:
        data = json.loads(ADMINS.read_text(encoding="utf-8"))
        return (isinstance(data, dict)
                and isinstance(data.get("admins"), list)
                and user in data["admins"])
    except (OSError, ValueError, TypeError):
        return False


def perform_action(user: str, action: str) -> None:
    """Forward only an allowed action; the root helper rechecks the allowlist."""
    if action not in ACTIONS:
        raise ValueError("Unknown server action")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(8)
        conn.connect(HELPER_SOCKET)
        conn.sendall(json.dumps({"admin": user, "operation": action}).encode("utf-8"))
        response = json.loads(conn.recv(4096).decode("utf-8"))
    if not isinstance(response, dict) or not response.get("ok"):
        raise RuntimeError("Server command rejected; check helper service journal")


@router.get("/settings/server", response_class=HTMLResponse)
def server_settings(request: Request):
    from retrodb.web_ui import page
    user = user_from_cookie(request.cookies.get(COOKIE, ""))
    if not user or user == "__retrodb_guest__":
        return Response("Administrator sign-in required", status_code=403)
    if not is_server_admin(user):
        return page("Server management", """<div class="crumb"><a href="/settings">Settings</a> / Server management</div>
<h1>Server management</h1><p class="muted">Server controls are limited to explicitly approved administrators.</p>""")
    result = request.query_params.get("result")
    notices = {
        "restart": "xeRAbora restart completed.",
        "reboot": "Server restart requested. This page may disconnect while the system reboots.",
        "error": "The action failed or the management helper is unavailable. Check the helper journal.",
    }
    notice = (f'<p role="status" class="card">{escape(notices[result])}</p>'
              if result in notices else "")
    actions = [
        ("restart-xerabora", "Restart xeRAbora", "Restarts the xeRAbora systemd service. Connected PS2 sessions may disconnect.",
         "RESTART", "Restart xeRAbora now? Connected games may be interrupted."),
        ("reboot-server", "Restart server", "Reboots the entire Debian host, including RetroDB and its services.",
         "REBOOT", "Restart the entire server? All hosted services will be temporarily unavailable."),
    ]
    panels = []
    for action, title, description, confirm, warning in actions:
        panels.append(f"""<section class="card">
<h2>{escape(title)}</h2><p>{escape(description)}</p>
<button class="btn" type="button" data-open-dialog="{action}">{escape(title)}</button>
<dialog id="{action}" class="switch-dialog" aria-labelledby="{action}-title">
<h2 id="{action}-title">Confirm {escape(title.lower())}</h2><p>{escape(warning)}</p>
<form method="post" action="/settings/server/action">
<input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
<input type="hidden" name="action" value="{action}">
<input type="hidden" name="confirm" value="{confirm}">
<div class="switch-actions"><button class="btn" type="button" data-cancel-dialog>Cancel</button>
<button class="btn" type="submit">{escape(title)}</button></div></form></dialog></section>""")
    script = """<script>(function(){
document.querySelectorAll("[data-open-dialog]").forEach(button=>{
 button.addEventListener("click",()=>{
  const dialog=document.getElementById(button.dataset.openDialog);
  if(dialog&&dialog.showModal)dialog.showModal();
 });
});
document.querySelectorAll("[data-cancel-dialog]").forEach(button=>{
 button.addEventListener("click",()=>button.closest("dialog").close());
});
document.querySelectorAll('dialog form').forEach(form=>{
 form.addEventListener("submit",()=>{form.querySelector('button[type="submit"]').disabled=true;});
});
})();</script>"""
    return page("Server management",
                '<div class="crumb"><a href="/settings">Settings</a> / Server management</div>'
                '<h1>Server management</h1><p class="muted">Privileged controls. Confirm each operation before it is sent.</p>'
                + notice + '<div class="grid">' + "".join(panels) + '</div>' + script)


@router.post("/settings/server/action")
async def server_action(request: Request):
    user = user_from_cookie(request.cookies.get(COOKIE, ""))
    if not is_server_admin(user):
        return Response("Not authorised", status_code=403)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        return Response("Form required", status_code=415)
    raw = await request.body()
    if len(raw) > 2048:
        return Response("Form too large", status_code=413)
    fields = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    action = fields.get("action", [""])[0]
    expected = ACTIONS.get(action)
    if (not expected or fields.get("confirm", [""])[0] != expected[0]
            or not valid_csrf(fields.get("csrf_token", [""])[0])):
        return Response("Confirmation missing or expired", status_code=403)
    try:
        perform_action(user, action)
        result = "restart" if action == "restart-xerabora" else "reboot"
    except (OSError, ValueError, RuntimeError, socket.timeout):
        result = "error"
    return RedirectResponse("/settings/server?" + urlencode({"result": result}), status_code=303,
                            headers={"Cache-Control": "no-store"})
