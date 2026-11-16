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


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if amount < 1024 or unit == "PiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "Unavailable"


def duration(seconds: int | None) -> str:
    if seconds is None:
        return "Unavailable"
    days, hours = divmod(seconds // 3600, 24)
    minutes = (seconds % 3600) // 60
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


def percent_bar(label: str, used: int, total: int, percent: float) -> str:
    value = max(0.0, min(100.0, float(percent)))
    return (f'<div class="sys-meter"><div class="sys-meter-label"><strong>{escape(label)}</strong>'
            f'<span>{value:.1f}% · {escape(format_bytes(used))} / {escape(format_bytes(total))}</span></div>'
            f'<progress value="{value:.1f}" max="100" aria-label="{escape(label, quote=True)} usage"></progress></div>')


def confirmation_dialog(action: str, title: str, confirm: str, warning: str) -> str:
    return f"""<dialog id="{action}" class="switch-dialog" aria-labelledby="{action}-title">
<h2 id="{action}-title">Confirm {escape(title.lower())}</h2><p>{escape(warning)}</p>
<form method="post" action="/settings/server/action">
<input type="hidden" name="csrf_token" value="{escape(csrf_token(), quote=True)}">
<input type="hidden" name="action" value="{action}">
<input type="hidden" name="confirm" value="{confirm}">
<div class="switch-actions"><button class="btn" type="button" data-cancel-dialog>Cancel</button>
<button class="btn" type="submit">{escape(title)}</button></div></form></dialog>"""


def render_settings(request: Request):
    """Combined responsive Settings dashboard; no automatic polling."""
    from retrodb.web_ui import page
    from retrodb import system_info
    user = user_from_cookie(request.cookies.get(COOKIE, ""))
    if not user or user == "__retrodb_guest__":
        return Response("Sign-in required", status_code=403)
    admin = is_server_admin(user)
    # No unauthorised host/network inventory disclosure. Failed telemetry
    # should never stop the entire Settings page from rendering.
    try:
        snapshot = system_info.snapshot() if admin else None
    except (OSError, ValueError, RuntimeError, TypeError):
        snapshot = {}
    notice_codes = {
        "restart": "xeRAbora restart requested. Refresh to see the latest service status.",
        "reboot": "Server reboot requested. RetroDB may disconnect while the host restarts.",
        "error": "The action could not be queued; check the management helper journal.",
    }
    result = request.query_params.get("result")
    notice = (f'<p role="status" class="card">{escape(notice_codes[result])}</p>'
              if result in notice_codes else "")
    style = """<style>
.settings-sections{display:grid;gap:20px;margin-top:20px}
.sys-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.sys-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:12px;margin:18px 0}
.sys-fact{padding:12px;background:#19283e;border:1px solid #354764;border-radius:12px;min-width:0;overflow-wrap:anywhere}
.sys-fact-label{font-size:12px;color:#b3c3dc;margin-bottom:7px}
.sys-fact-value{font-size:15px;font-weight:600;color:#f3f7ff}
.sys-meters{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:16px;margin:16px 0 20px}
.sys-meter{min-width:0}.sys-meter-label{display:flex;flex-wrap:wrap;justify-content:space-between;gap:5px;margin-bottom:9px;font-size:13px}
.sys-meter-label span{color:#bacbe4}
.sys-meter progress{width:100%;height:13px;accent-color:#4ca5fa}
.sys-foot{border-top:1px solid #354764;margin-top:18px;padding-top:18px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.sys-service{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.sys-state{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:6px 10px;border:1px solid #45607c;border-radius:999px;background:#1b2a43}
.sys-state[data-state="active"]{color:#a6e8ae;border-color:#477d55}
.sys-state[data-state="failed"],.sys-state[data-state="inactive"]{color:#ffbdac;border-color:#965849}
</style>"""
    if admin:
        try:
            values = snapshot or {}
            def fact(label, value):
                return (f'<div class="sys-fact"><div class="sys-fact-label">{escape(label)}</div>'
                        f'<div class="sys-fact-value">{escape(str(value if value is not None else "Unavailable"))}</div></div>')
            fields = [
                ("Hostname", values.get("hostname")),
                ("IP address", values.get("ip")),
                ("Operating system", values.get("os")),
                ("Hardware", values.get("hardware_type")),
                ("Manufacturer / model", values.get("model")),
                ("Architecture", values.get("architecture")),
                ("Uptime", duration(values.get("uptime"))),
                ("CPU", str(values.get("cpu_cores") or "Unknown") + " logical cores"),
            ]
            facts = "".join(fact(label, value) for label, value in fields)
            meters = []
            cpu = values.get("cpu_percent")
            if cpu is not None:
                meters.append(f'<div class="sys-meter"><div class="sys-meter-label"><strong>CPU utilisation</strong>'
                              f'<span>{float(cpu):.1f}%</span></div>'
                              f'<progress value="{max(0.0,min(100.0,float(cpu))):.1f}" max="100" aria-label="CPU utilisation"></progress></div>')
            for label, key in (("Memory", "memory"), ("System disk (/)", "disk"), ("RetroNAS share", "retronas_disk")):
                usage = values.get(key)
                if usage is not None:
                    meters.append(percent_bar(label, *usage))
            if not meters:
                meters.append('<p class="muted">Utilisation readings unavailable.</p>')
            captured = escape(str(values.get("captured") or "Unknown"))
            system_html = f"""<section class="card" id="system-information">
<div class="sys-head"><div><div class="eyebrow">Host overview</div><h2>System information</h2></div>
<a class="btn" href="/settings?refresh=1#system-information" aria-label="Refresh system information">↻ Refresh</a></div>
<p class="muted">Snapshot captured {captured}; values update only when you refresh.</p>
<div class="sys-facts">{facts}</div>
<h3>Resource utilisation</h3><div class="sys-meters">{''.join(meters)}</div>
<div class="sys-foot"><div><strong>Server power</strong>
<p class="muted">Restarting Debian temporarily disconnects every hosted service.</p></div>
<button class="btn" type="button" data-open-dialog="reboot-server">Restart server</button></div>
{confirmation_dialog("reboot-server", "Restart server", "REBOOT", "Reboot the entire host? RetroDB, xeRAbora and every other service will be unavailable during startup.")}
</section>"""
            state = escape(str(values.get("xerabora") or "unknown"))
            services_html = f"""<section class="card" id="services">
<div class="sys-head"><div><div class="eyebrow">Hosted services</div><h2>Services</h2></div>
<a href="/settings?refresh=1#services" class="btn" aria-label="Refresh service status">↻ Refresh</a></div>
<div class="sys-service"><div><h3>xeRAbora</h3>
<span class="sys-state" data-state="{state}">{state.title()}</span>
<p class="muted">PS2 RetroAchievements service. A restart may interrupt connected sessions.</p></div>
<button class="btn" type="button" data-open-dialog="restart-xerabora">Restart xeRAbora</button></div>
{confirmation_dialog("restart-xerabora", "Restart xeRAbora", "RESTART", "Restart the xeRAbora service? Connected PS2 sessions may be interrupted.")}
</section>"""
        except (OSError, ValueError, TypeError):
            # Telemetry issues must not take away an approved admin's ability
            # to recover a hung service or reboot the host.
            system_html = ('<section class="card"><h2>System information</h2>'
                           '<p class="muted">Host information is unavailable. Refresh or check service logs.</p>'
                           '<button class="btn" type="button" data-open-dialog="reboot-server">Restart server</button>'
                           + confirmation_dialog("reboot-server", "Restart server", "REBOOT",
                                                 "Reboot the entire host and interrupt all hosted services?")
                           + '</section>')
            services_html = ('<section class="card"><h2>Services</h2>'
                             '<p class="muted">Service status is unavailable.</p>'
                             '<button class="btn" type="button" data-open-dialog="restart-xerabora">Restart xeRAbora</button>'
                             + confirmation_dialog("restart-xerabora", "Restart xeRAbora", "RESTART",
                                                   "Restart xeRAbora and interrupt connected sessions?")
                             + '</section>')
    else:
        system_html = ('<section class="card"><h2>System information</h2>'
                       '<p class="muted">Host details and power controls are available to approved administrators.</p></section>')
        services_html = ('<section class="card"><h2>Services</h2>'
                         '<p class="muted">Service status and restart controls require server management permission.</p></section>')
    library_html = """<section class="card" id="library-management"><div class="eyebrow">Collection</div>
<h2>Library management</h2><p class="muted">Inventory, audit results and planned maintenance tools are unchanged.</p>
<a class="btn" href="/settings/library">Open library management</a></section>"""
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
    body = ('<div class="crumb"><a href="/">Dashboard</a> / Settings</div>'
            '<h1>Settings</h1><p class="muted">System information, hosted services and library management.</p>'
            + notice + style + '<div class="settings-sections">' + system_html + services_html + library_html
            + '</div>' + script)
    response = page("Settings", body)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/settings/server", response_class=HTMLResponse)
def server_settings(request: Request):
    """Legacy deep link shows the same dashboard with the requested sections."""
    return render_settings(request)


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
    return RedirectResponse("/settings?" + urlencode({"result": result}), status_code=303,
                            headers={"Cache-Control": "no-store"})
