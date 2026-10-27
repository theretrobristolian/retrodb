"""RetroDB v1 browser pages: read-only library, release details, and service overview."""
from __future__ import annotations

import json
import re
from pathlib import Path
from collections import Counter
from functools import lru_cache
from html import escape
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, or_
from sqlalchemy.orm import Session

from retrodb.database import get_session
from retrodb.models import LibraryItem, Platform
from retrodb.providers.gamedb import load as load_gamedb

router = APIRouter(include_in_schema=False)

CSS = """
:root{color-scheme:dark;font:16px system-ui,-apple-system,Segoe UI,sans-serif;background:#0b1020;color:#eaf0fc}
*{box-sizing:border-box}html{width:100%;max-width:100%;overflow-x:clip}body{margin:0;width:100%;max-width:100%;overflow-x:clip}a{color:inherit;text-decoration:none}a:hover{color:#9ebeff}
header{position:sticky;top:0;z-index:20;border-bottom:1px solid #263047;background:#11192c;padding:18px max(24px,calc((100vw - 1200px)/2))}
header .bar{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.brand{font-size:22px;font-weight:800;letter-spacing:-1px;color:#f6f8ff;white-space:nowrap}
.mobile-nav,.mobile-actions{display:none}nav{display:flex;flex-wrap:wrap;gap:5px;min-width:0;max-width:100%;color:#afc0da;font-size:13px;align-items:center}header nav a,header nav button{padding:9px 11px;border-radius:9px}header nav a:hover,header nav button:hover{background:#21314f;color:#fff}nav a,nav button{overflow-wrap:normal}main{max-width:1200px;margin:auto;padding:24px 24px 70px}
h1{font-size:34px;letter-spacing:-1.3px;margin:0 0 8px}h2{font-size:21px;margin:28px 0 16px}
p{line-height:1.6}.muted{color:#9daeca}.eyebrow{color:#7caeff;text-transform:uppercase;font-size:12px;font-weight:700;letter-spacing:1.7px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.card{display:block;min-width:0;max-width:100%;overflow-wrap:anywhere;background:#151f32;border:1px solid #293952;border-radius:15px;padding:22px;min-height:120px}
.card:hover{border-color:#527cc6}.card h2{margin:4px 0 9px}.metric{font-size:34px;font-weight:750}
.pill{background:#243651;color:#c4daff;padding:4px 9px;border-radius:30px;font-size:12px;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;color:#91a8c8;font-weight:600;background:#17233a}
th,td{padding:13px 12px;border-bottom:1px solid #27334a}tr:hover td{background:#18243a}
.panel.library-scroll{max-height:70vh;overflow:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior:contain}
.library-scroll thead th{position:sticky;top:0;z-index:2;box-shadow:0 1px #344760}
.library-scroll table{min-width:0;table-layout:fixed}
.library-scroll td[data-column="title"]{overflow-wrap:anywhere;word-break:normal;line-height:1.4}
.library-scroll th[data-column="title"]{width:47%}
.library-scroll th[data-column="disc"]{width:31%}
.library-scroll th[data-column="region"]{width:11%}
.library-scroll th[data-column="ra"]{width:11%}

.library-scroll td[data-column="disc"]{overflow-wrap:anywhere}
.library-scroll .pill.serial{white-space:normal;overflow-wrap:anywhere;line-height:1.3}
.region-icon{font-size:19px;line-height:1;white-space:nowrap}.ra-icon{display:inline-block;position:relative;font-size:19px;line-height:1;white-space:nowrap}
.ra-icon.yes{filter:sepia(1) saturate(3);color:#f5ca65}
.ra-icon.no{filter:grayscale(1);opacity:.35}
.ra-icon.no::after{content:"×";position:absolute;right:-4px;bottom:-7px;font-size:15px;font-weight:900;color:#e4e8f0;text-shadow:0 0 2px #10192d}
@media(max-width:760px){
 .library-scroll table{width:100%;min-width:0;font-size:12px}
 .library-scroll th,.library-scroll td{padding:9px 4px}
 .library-scroll th[data-column="title"]{width:44%}
 .library-scroll th[data-column="disc"]{width:30%}
 .library-scroll th[data-column="region"]{width:13%}
 .library-scroll th[data-column="ra"]{width:13%}

 .library-scroll .pill.serial{padding:3px 5px;font-size:11px}
 .library-scroll td[data-column="region"]{text-align:center}
 .library-scroll td[data-column="ra"],.library-scroll th[data-column="ra"]{text-align:center}
}
.library-scroll [hidden]{display:none}
.pill.serial{font-family:monospace;background:#263d61}
.achievement{color:#f5ca65;font-weight:700}
.column-picker{display:flex;align-items:center;gap:15px;flex-wrap:wrap;margin:15px 0;font-size:13px}
.column-picker label{white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.column-picker input[type=checkbox]{min-width:0;width:16px;height:16px;flex:none;margin:0;accent-color:#77a9ff}
@media(max-width:760px){.panel.library-scroll{max-height:65vh}}
.panel{background:#121c2e;border:1px solid #2a3851;border-radius:14px;overflow:hidden;margin-top:22px}
.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:23px 0}
input,select{color:#f0f5ff;background:#141d2f;border:1px solid #3a4d6b;padding:11px 13px;border-radius:10px;font-size:14px}
input{min-width:240px;flex:1}.btn{padding:11px 16px;border:1px solid #466ca4;background:#294671;border-radius:10px;color:white;cursor:pointer}
.btn:hover{background:#365c91}.label{font-size:13px;color:#aabbd2}.crumb{margin-bottom:18px;color:#9badc7}
.player-switch{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}
.switch-dialog{width:min(calc(100% - 28px),430px);max-height:85vh;padding:26px;background:#151f32;color:#eaf0fc;border:1px solid #425d85;border-radius:18px;box-shadow:0 15px 60px #0008}
.switch-dialog::backdrop{background:#020715bb}
.switch-dialog h2{margin:8px 0 15px}
.switch-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;margin-top:22px}
.switch-actions button{flex:1;min-width:110px}
.switch-actions button:disabled{opacity:.6;cursor:wait}
.game-title-row{display:grid;grid-template-columns:82px minmax(0,1fr);align-items:center;gap:16px;margin-bottom:18px;min-width:0;max-width:100%}.game-title-row:not(:has(.game-ra-icon)){grid-template-columns:minmax(0,1fr)}.game-title-row h1{margin-bottom:4px}.game-ra-icon{width:82px;height:82px;object-fit:contain;border-radius:14px;background:#101a2c}.game-art-grid{display:flex;align-items:center;justify-content:center;min-height:140px;max-width:100%;overflow:hidden}.game-art-card{text-align:center;min-width:0;overflow:hidden}.game-art-card h2{text-align:center;margin:0 0 16px}.game-art-grid figure{margin:0;flex:1 1 145px;max-width:270px}.game-cover{display:block;width:auto;max-width:100%;height:auto;max-height:280px;margin:0 auto;object-fit:contain;border-radius:10px;background:#0b1020}.game-art-grid figcaption{margin-top:9px;text-align:center}
.detail{columns:2;column-gap:18px;min-width:0;max-width:100%}.detail>section{break-inside:avoid;display:inline-block;width:100%;vertical-align:top;margin-bottom:18px}.detail .card{min-height:0;min-width:0;max-width:100%}.detail .card p{overflow-wrap:anywhere;word-break:normal}.detail-field{min-width:0;max-width:100%;overflow-wrap:anywhere;white-space:normal}.game-title-row>div{min-width:0;max-width:100%;overflow-wrap:anywhere}.game-title-row .muted{margin:8px 0 0}.game-title-row h1,.crumb{overflow-wrap:anywhere}
.feature-strip{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 20px}.feature-chip{display:inline-flex;align-items:center;gap:7px;background:#1c2c45;border:1px solid #395476;border-radius:9px;padding:9px 12px;font-size:13px;color:#d6e5ff}.feature-chip .feature-glyph{font-size:18px;color:#91c5ff}.info-pairs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px}.info-pairs .detail-field{margin:5px 0;padding:7px 0}.meta-source{font-size:12px;margin:8px 0 0}.technical-details summary{cursor:pointer;font-weight:600;color:#bfd2f1;padding:9px 0}.technical-details .detail-field{margin:9px 0}.detail .card{padding:20px}.detail .card h2{margin:0 0 14px}header nav form{margin:0}
@media(max-width:760px){
 .detail{columns:1}
 .game-title-row{grid-template-columns:64px minmax(0,1fr);gap:12px;align-items:center}
 .game-title-row:not(:has(.game-ra-icon)){grid-template-columns:minmax(0,1fr)}
 .game-title-row .game-ra-icon{width:64px;height:64px}
 .game-title-row h1{font-size:clamp(19px,5.5vw,27px);line-height:1.18;letter-spacing:-.5px}
 .game-title-row .muted{font-size:12px;line-height:1.35}
 .info-pairs{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
 .detail .card{padding:16px}
 .detail .card h2{margin-bottom:10px}
 .feature-strip{gap:6px;margin:9px 0 14px}
 .feature-chip{font-size:11px;padding:7px 9px}
 .game-art-card{padding:18px 16px}
 .game-art-card h2{margin-bottom:12px}
 .game-cover{max-height:230px;max-width:min(100%,230px)}
 main{padding:14px 14px calc(80px + env(safe-area-inset-bottom, 0px));min-width:0;max-width:100%;overflow-x:clip}
 h1{font-size:27px;letter-spacing:-.7px}
 h2{font-size:19px}
 th,td{padding:9px 6px}
 header{position:relative;padding:10px 14px;border-bottom:1px solid #263047}
 header .bar{display:flex;flex-direction:row;justify-content:space-between;align-items:center;gap:8px;min-width:0}
 header .brand{font-size:20px;letter-spacing:-.6px;white-space:nowrap}
 header nav{display:none}
 .mobile-actions{display:flex;align-items:center;gap:10px;font-size:12px;color:#afc0da}
 .mobile-actions form{margin:0}
 .mobile-actions button{font:inherit;color:#afc0da;background:transparent;border:0;padding:8px 3px;cursor:pointer}
 .mobile-nav{display:grid;position:fixed;z-index:40;bottom:0;left:0;right:0;width:100%;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;align-items:stretch;padding:7px 5px max(8px, calc(env(safe-area-inset-bottom, 0px) - 20px));border-top:1px solid #2a3851;background:#10192df5;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
 .mobile-nav a{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:4px;padding:8px 2px;border-radius:10px;color:#afc0da;min-width:0;font-size:10px;line-height:1.15;overflow-wrap:anywhere}
 .mobile-nav a .nav-icon{font-size:19px;line-height:1}
 .mobile-nav a[data-nav="/profile"] .nav-icon{font-size:26px;line-height:19px}
 .mobile-nav a[aria-current="page"]{background:#294671;color:#fff}
 .crumb{font-size:13px}
}
@media(max-width:360px){.mobile-nav a{font-size:9px}.mobile-nav a .nav-icon{font-size:17px}.mobile-nav a[data-nav="/profile"] .nav-icon{font-size:24px;line-height:17px}}

"""

def is_guest(request: Request) -> bool:
    from retrodb.session_auth import COOKIE, user_from_cookie
    return user_from_cookie(request.cookies.get(COOKIE, "")) == "__retrodb_guest__"

def page(title: str, body: str, guest: bool = False) -> HTMLResponse:
    from retrodb.session_auth import csrf_token
    signout_csrf = csrf_token()
    private_nav = '' if guest else '<a href="/profile">My profile</a><a href="/management">Management</a><a href="/online-services">Online services</a>'
    logout_label = "Leave guest view" if guest else "Sign out"
    heading = escape(title)
    mobile_links = [
        ("/", "⌂", "Consoles"),
        ("/library", "▤", "Games"),
        ("/profile", "♙", "Profile"),
        ("/online-services", "◉", "Online"),
        ("/management", "⚙", "Manage"),
    ]
    if guest:
        mobile_links = [item for item in mobile_links if item[0] not in ("/profile", "/online-services", "/management")]
    mobile_nav = ''.join(
        f'<a href="{path}" data-nav="{path}"><span class="nav-icon" aria-hidden="true">{icon}</span><span>{label}</span></a>'
        for path, icon, label in mobile_links
    )
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{heading} · RetroDB</title>
<meta name="theme-color" content="#10192d">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="RetroDB">
<meta name="application-name" content="RetroDB">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.webmanifest">
<style>{CSS}</style></head><body><header><div class="bar"><a class="brand" href="/">◈ RetroDB</a><div class="mobile-actions"><a href="https://github.com/theretrobristolian/retrodb" target="_blank" rel="noopener">GitHub ↗</a><form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{signout_csrf}"><button type="submit">{logout_label}</button></form></div>
<nav><a href="/">Consoles</a><a href="/library">All games</a>{private_nav}
<a href="https://github.com/theretrobristolian/retrodb" target="_blank" rel="noopener">GitHub ↗</a><form method="post" action="/logout" style="display:inline"><input type="hidden" name="csrf_token" value="{signout_csrf}"><button type="submit" style="border:0;color:#afc0da;background:transparent;cursor:pointer">{logout_label}</button></form></nav></div></header>
<main>{body}</main><div class="mobile-nav" aria-label="Mobile navigation">{mobile_nav}</div><script>(function(){{const p=location.pathname;document.querySelectorAll(".mobile-nav a").forEach(a=>{{const h=a.getAttribute("href");if((h==="/"&&p==="/")||(h==="/library"&&(p.startsWith("/library")||p.startsWith("/game/")))||(h!=="/"&&h!=="/library"&&p.startsWith(h)))a.setAttribute("aria-current","page");}})}})();</script></body></html>""")

SERIAL_RE = re.compile(r"(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)[_. -]*([0-9]{3})[. -]*([0-9]{2})", re.I)

def disc_id(item: LibraryItem) -> str:
    match = SERIAL_RE.search(item.filename) or SERIAL_RE.search(item.relative_path)
    return f"{match.group(1).upper()}-{match.group(2)}{match.group(3)}" if match else ""

def disc_region(serial: str, platform_slug: str | None) -> tuple[str, str]:
    """Conservative PS1/PS2 disc-prefix region hints, not guaranteed disc origin."""
    if platform_slug not in ("playstation", "playstation-2") or not serial:
        return ("🌐", "Region unknown")
    prefix = serial.split("-", 1)[0].upper()
    if prefix in ("SLUS", "SCUS"):
        return ("🇺🇸", "North America (disc prefix)")
    if prefix in ("SLES", "SCES", "SCED"):
        return ("🇪🇺", "Europe / PAL (disc prefix)")
    if prefix in ("SLPS", "SLPM", "SCPS"):
        return ("🇯🇵", "Japan (disc prefix)")
    return ("🌐", "Region unknown")

GAMEDB_CACHE = Path("/var/cache/retrodb/providers/gamedb")

@lru_cache(maxsize=8)
def _gamedb_titles(slug: str, mtime_ns: int) -> dict[str, str]:
    try:
        return load_gamedb(GAMEDB_CACHE, slug)
    except (OSError, ValueError):
        return {}

def gamedb_title(item: LibraryItem, slug: str | None) -> str:
    if slug not in ("playstation", "playstation-2"):
        return ""
    serial = disc_id(item)
    if not serial:
        return ""
    cache = GAMEDB_CACHE / f"{slug}.json"
    try:
        titles = _gamedb_titles(slug, cache.stat().st_mtime_ns)
    except OSError:
        return ""
    return titles.get(serial, "")

# Only verified PS1 disc-to-volume identities. Extend as catalogues are reviewed;
# never assign disc order alphabetically or from unverified region variants.
PS1_DISC_NUMBERS = {
    "SLUS-00594": 1, "SLUS-00776": 2,  # Metal Gear Solid
    "SLUS-00544": 1, "SLUS-00556": 2,  # G-Police
    "SLUS-00710": 1, "SLUS-00731": 2,  # Abe's Exoddus
    "SLPS-01995": 1, "SLPS-01996": 2,  # Geppy-X (four discs)
    "SLPS-01997": 3, "SLPS-01998": 4,
    "SLUS-01201": 1, "SLUS-01377": 2,  # Alone in the Dark: The New Nightmare (USA)
    "SLES-02801": 1, "SLES-12801": 2,  # UK / English
    "SLES-02802": 1, "SLES-12802": 2,  # French
    "SLES-02803": 1, "SLES-12803": 2,  # German
    "SLES-02804": 1, "SLES-12804": 2,  # Spanish
    "SLES-02805": 1, "SLES-12805": 2,  # Italian
}
DISC_MARKER = re.compile(r"\\((?:Disc|Disk|CD)\\s*(\\d+)(?:\\s*(?:of|/)\\s*\\d+)?\\)", re.I)
REV_MARKER = re.compile(r"\\s*\\((?:Rev(?:ision)?\\s*\\d+(?:\\.\\d+)?|v\\d+(?:\\.\\d+)?)\\)", re.I)


def name(item: LibraryItem, slug: str | None = None) -> str:
    filename = PurePosixPath(item.filename).stem
    title = ((item.ra_game_title or "").strip()
             or gamedb_title(item, slug)
             or filename)
    if slug == "playstation" and disc_id(item) == "SLES-03120":
        title = "3, 2, 1, Smurf! My First Racing Game"
    title = re.sub(r"^(?:OLD_|NEW_)", "", title, flags=re.I)
    title = SERIAL_RE.sub("", title)
    title = re.sub(r"\\[\\s*\\]|\\{\\s*\\}|\\(\\s*\\)", " ", title)
    title = title.replace("_", " ")
    title = REV_MARKER.sub("", title)
    title = re.sub(r"\\s*\\((?:USA|Europe|Japan|World|En|Fr|De)\\)\\s*$", "", title, flags=re.I)
    title = re.sub(r"\\s{2,}", " ", title).strip(" -._")
    if slug == "playstation":
        serial = disc_id(item)
        # A visible filename disc number remains useful even when RA/GameDB
        # supplies a shared title for every disc of the same game.
        disc = (PS1_DISC_NUMBERS.get(serial)
                or (int(DISC_MARKER.search(filename).group(1)) if DISC_MARKER.search(filename) else None))
        if disc:
            title = DISC_MARKER.sub("", title).strip()
            title += f" (Disc {disc})"
    return title or filename

RA_CACHE = Path("/var/cache/retrodb/providers/retroachievements")


@lru_cache(maxsize=8)
def _ra_achievement_counts(slug: str, mtime_ns: int) -> dict[int, int]:
    try:
        rows = json.loads((RA_CACHE / f"{slug}.json").read_text(encoding="utf-8"))
        return {int(row["ID"]): int(row.get("NumAchievements", 0))
                for row in rows if isinstance(row, dict) and "ID" in row}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def ra_supported(item: LibraryItem) -> bool:
    """Gold means a matched disc AND a confirmed nonempty achievement set."""
    if not item.ra_game_id or (item.ra_match_status or "").lower() != "matched":
        return False
    slug = item_slug(item)
    if slug not in ("playstation", "playstation-2"):
        return False
    path = RA_CACHE / f"{slug}.json"
    try:
        counts = _ra_achievement_counts(slug, path.stat().st_mtime_ns)
    except OSError:
        return False  # Missing catalogue is not proof of achievements.
    return counts.get(int(item.ra_game_id), 0) > 0

def platform_counts(db: Session):
    stmt = (select(Platform, func.count(LibraryItem.id))
            .outerjoin(LibraryItem, (LibraryItem.platform_id == Platform.id) & (LibraryItem.is_missing.is_(False)))
            .group_by(Platform.id).order_by(Platform.name))
    return db.execute(stmt).all()

@router.get("/", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_session)):
    cards = []
    total = 0
    for platform, count in platform_counts(db):
        total += count
        cards.append(f"""<a class="card" href="/library/{quote(platform.slug)}"><div class="eyebrow">{escape(platform.manufacturer or 'Console')}</div>
<h2>{escape(platform.name)}</h2><div class="metric">{count:,}</div><span class="muted">indexed files · Explore →</span></a>""")
    empty = '<p class="muted">No consoles are configured in PostgreSQL yet. Run RetroDB deployment and library inventory scan first.</p>' if not cards else ""
    management_card = "" if is_guest(request) else '<a class="card" href="/management"><h2>Library management →</h2><p class="muted">Status, inventory and safe maintenance guidance</p></a>'
    return page("Consoles", f"""<div class="eyebrow">Your personal game collection</div><h1>Choose a console</h1>
<p class="muted">Browse your own indexed collection, explore releases, and check collection health.</p>
<div class="grid">{''.join(cards)}</div>{empty}
<h2>Library overview</h2><div class="grid"><div class="card"><div class="label">Indexed game files</div>
<div class="metric">{total:,}</div></div>{management_card}</div>""", guest=is_guest(request))

def browse(request: Request, db: Session, slug: str | None, q: str, letter: str,
           page_number: int, ra_filter: str = "all", sort_by: str = "title", order: str = "asc"):
    platform = None
    if slug:
        platform = db.scalar(select(Platform).where(Platform.slug == slug))
        if platform is None:
            raise HTTPException(404, "Console not found")
    stmt = select(LibraryItem).where(LibraryItem.is_missing.is_(False))
    # A PS1 BIN is a track payload, not an additional game. Display its CUE
    # entry point instead; keep BIN records in storage for diagnostics.
    ps1_id = db.scalar(select(Platform.id).where(Platform.slug == "playstation"))
    if ps1_id is not None:
        stmt = stmt.where(or_(LibraryItem.platform_id != ps1_id,
                              func.lower(LibraryItem.extension) != "bin"))
    if platform:
        stmt = stmt.where(LibraryItem.platform_id == platform.id)
    # Sort on the same basic cleanup used to display filename fallbacks.
    # This avoids sorting missing-RA titles under their disc serial rather than title.
    filename_stem = func.regexp_replace(LibraryItem.filename, r"\.[^.]+$", "", "g")
    no_serial = func.regexp_replace(filename_stem,
                                    r"(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)[_. -]*[0-9]{3}[. -]*[0-9]{2}",
                                    "", "gi")
    fallback_title = func.btrim(func.replace(no_serial, "_", " "), " .-_")
    display_title = func.coalesce(func.nullif(LibraryItem.ra_game_title, ""), fallback_title)
    platform_names = {p.id: p.slug for p in db.scalars(select(Platform)).all()} if not platform else {}
    def item_slug(item):
        return platform.slug if platform else platform_names.get(item.platform_id)
    # GameDB cache lookup is local and deterministic. Resolve before paging so
    # alphabet filtering and sorting use exactly the title displayed to users.
    if sort_by == "title" or letter or q:
        candidate_items = db.scalars(stmt.order_by(LibraryItem.id.asc())).all()
        if q:
            term = q.casefold()
            candidate_items = [i for i in candidate_items if term in name(i, item_slug(i)).casefold()
                               or term in i.filename.casefold() or term in disc_id(i).casefold()]
        if letter:
            candidate_items = [i for i in candidate_items if name(i, item_slug(i)).casefold().startswith(letter.casefold())]
        matched_filter = lambda i: ra_supported(i)
        if ra_filter == "yes":
            candidate_items = [i for i in candidate_items if matched_filter(i)]
        elif ra_filter == "other":
            candidate_items = [i for i in candidate_items if not matched_filter(i)]
        if sort_by == "title":
            candidate_items.sort(key=lambda i: (name(i, item_slug(i)).casefold(), i.id), reverse=(order == "desc"))
        elif sort_by == "disc":
            candidate_items.sort(key=lambda i: (disc_id(i).casefold(), i.id), reverse=(order == "desc"))
        elif sort_by == "id":
            candidate_items.sort(key=lambda i: (i.ra_game_id is None, i.ra_game_id or 0, i.id), reverse=(order == "desc"))
        else:
            candidate_items.sort(key=lambda i: ((i.ra_match_status or "").casefold(), i.id), reverse=(order == "desc"))
        count = len(candidate_items)
        items = candidate_items[(page_number-1)*100:page_number*100]
    else:
        matched = (LibraryItem.ra_game_id.is_not(None) & (func.lower(LibraryItem.ra_match_status) == "matched"))
        if ra_filter == "yes":
            stmt = stmt.where(matched)
        elif ra_filter == "other":
            stmt = stmt.where(~matched)
        count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        sort_expr = {"id": LibraryItem.ra_game_id,
                     "ra": func.lower(func.coalesce(LibraryItem.ra_match_status, "")),
                     "disc": func.lower(LibraryItem.filename)}.get(sort_by, LibraryItem.filename)
        items = db.scalars(stmt.order_by((sort_expr.desc() if order == "desc" else sort_expr.asc()).nulls_last(),
                                         LibraryItem.id.asc()).limit(100).offset((page_number-1)*100)).all()
    base = "/library" + ("/" + quote(slug) if slug else "")
    from urllib.parse import urlencode
    def link(**changes):
        args = dict(q=q,letter=letter,ra=ra_filter,sort=sort_by,order=order,page=page_number)
        args.update(changes)
        return base + "?" + urlencode(args)
    alphabet = ' '.join(f'<a class="pill" href="{escape(link(letter=c,page=1), quote=True)}">{c}</a>' for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    rows = []
    for item in items:
        disc = disc_id(item)
        supported = ra_supported(item)
        region_flag, region_label = disc_region(disc, item_slug(item))
        badge = 'Verified RetroAchievements hash' if supported else ('No verified RetroAchievements match: ' + (item.ra_match_status or 'unknown'))
        rows.append(f"""<tr><td data-column="title"><a href="/game/{item.id}">{escape(name(item, item_slug(item)))}</a></td>
<td data-column="disc">{'<span class="pill serial">'+escape(disc)+'</span>' if disc else '—'}</td>
<td data-column="region"><span class="region-icon" role="img" aria-label="{escape(region_label,quote=True)}" title="{escape(region_label,quote=True)}">{region_flag}</span></td>
<td data-column="ra"><span class="ra-icon {'yes' if supported else 'no'}" role="img" aria-label="{escape(badge,quote=True)}" title="{escape(badge,quote=True)}">🏆</span></td>
</tr>""")
    prev_link = f'<a class="btn" href="{escape(link(page=page_number-1),quote=True)}">← Previous</a>' if page_number > 1 else ''
    next_link = f'<a class="btn" href="{escape(link(page=page_number+1),quote=True)}">Next →</a>' if count > page_number*100 else ''
    heading = escape(platform.name if platform else "All games")
    return page(heading, f"""<div class="crumb"><a href="/">Consoles</a> / {heading}</div>
<h1>{heading}</h1><p class="muted">{count:,} indexed game entries · Up to 100 per page</p>
<form class="toolbar" action="{base}">
<input name="q" value="{escape(q,quote=True)}" placeholder="Search games or serials">
<input type="hidden" name="letter" value="{escape(letter,quote=True)}">
<label class="label">RA <select name="ra"><option value="all">All</option>
<option value="yes" {'selected' if ra_filter=='yes' else ''}>Verified</option>
<option value="other" {'selected' if ra_filter=='other' else ''}>Other / unknown</option></select></label>
<label class="label">Sort <select name="sort">
<option value="title" {'selected' if sort_by=='title' else ''}>Game name</option>
<option value="disc" {'selected' if sort_by=='disc' else ''}>Filename</option>
<option value="id" {'selected' if sort_by=='id' else ''}>RA ID</option>
<option value="ra" {'selected' if sort_by=='ra' else ''}>RA status</option></select></label>
<select name="order"><option value="asc">Ascending</option><option value="desc" {'selected' if order=='desc' else ''}>Descending</option></select>
<button class="btn" type="submit">Apply</button><a class="btn" href="{base}">Reset</a></form>
<div class="column-picker"><span class="label">Columns</span>
<label><input type="checkbox" data-toggle="disc" checked> Disc ID</label>
<label><input type="checkbox" data-toggle="region" checked> Region</label>
<label><input type="checkbox" data-toggle="ra" checked> Achievements</label>
</div>
<div class="toolbar"><a class="pill" href="{escape(link(letter='',page=1),quote=True)}">All</a>{alphabet}</div>
<div class="panel library-scroll"><table><thead><tr><th data-column="title">Game</th><th data-column="disc">Disc ID</th>
<th data-column="region">Region</th><th data-column="ra" title="RetroAchievements">RA</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="4">No games match the current filters.</td></tr>'}</tbody></table></div>
<p class="muted">Region flags are inferred from recognised PS1/PS2 disc prefixes; unknown prefixes show 🌐. Gold 🏆 means a verified RA disc hash and RA game ID; muted crossed trophy means no verified match in the current audit (not necessarily unsupported). Names without RA titles are cleaned filename fallbacks; exact Excel identity enrichment is not yet stored here.</p>
<div class="toolbar">{prev_link}{next_link}</div>
<script>
(function() {{
 const toggles=[...document.querySelectorAll('[data-toggle]')];
 let stored={{}};try{{stored=JSON.parse(localStorage.getItem('retrodb-columns')||'{{}}')}}catch(e){{}}
 function show(){{
  const settings={{}};
  toggles.forEach(box=>{{const id=box.dataset.toggle;settings[id]=box.checked;
   document.querySelectorAll('[data-column="'+id+'"]').forEach(cell=>cell.hidden=!box.checked);}});
  try{{localStorage.setItem('retrodb-columns',JSON.stringify(settings))}}catch(e){{}}
 }}
 toggles.forEach(box=>{{if(Object.prototype.hasOwnProperty.call(stored,box.dataset.toggle))box.checked=!!stored[box.dataset.toggle];box.addEventListener('change',show);}});
 show();
}})();
</script>""", guest=is_guest(request))

@router.get("/library", response_class=HTMLResponse)
def all_games(request: Request, db: Session = Depends(get_session), q: str = Query("", max_length=100),
              letter: str = Query("", pattern="^[A-Za-z]?$"),
              page_number: int = Query(1, alias="page", ge=1, le=10000),
              ra: str = Query("all", pattern="^(all|yes|other)$"),
              sort: str = Query("title", pattern="^(title|disc|id|ra)$"),
              order: str = Query("asc", pattern="^(asc|desc)$")):
    return browse(request, db, None, q, letter.upper(), page_number, ra, sort, order)

@router.get("/library/{slug}", response_class=HTMLResponse)
def console_games(slug: str, request: Request, db: Session = Depends(get_session), q: str = Query("", max_length=100),
                  letter: str = Query("", pattern="^[A-Za-z]?$"),
                  page_number: int = Query(1, alias="page", ge=1, le=10000),
                  ra: str = Query("all", pattern="^(all|yes|other)$"),
                  sort: str = Query("title", pattern="^(title|disc|id|ra)$"),
                  order: str = Query("asc", pattern="^(asc|desc)$")):
    return browse(request, db, slug, q, letter.upper(), page_number, ra, sort, order)

PS2_SERIAL = re.compile(r"(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)[_. -]*([0-9]{3})[. -]*([0-9]{2})", re.I)
DATA_DIR = Path("/var/cache/retrodb/web")

def online_record(item):
    serial_match = PS2_SERIAL.search(item.filename)
    if not serial_match:
        serial_match = PS2_SERIAL.search(item.relative_path)
    if not serial_match:
        return None
    disc = f"{serial_match.group(1).upper()}-{serial_match.group(2)}{serial_match.group(3)}"
    try:
        data = json.loads((DATA_DIR / "online-compatibility.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for record in data.get("records", []):
        if record.get("disc_id") == disc and record.get("platform") == "playstation-2":
            return record
    return None

def online_details(record):
    if not record:
        return '<p class="muted">No release-specific PS2 online record published. Unknown does not mean unsupported.</p>'
    lines = [
        ("Historical online", record.get("historical_online", "UNKNOWN")),
        ("Original provider", record.get("original_host", "Unknown")),
        ("Community DNS report", record.get("dns_compatible", "UNKNOWN")),
        ("Server / DNS reference", record.get("dns_address_or_provider", "")),
        ("XLink (community)", record.get("xlink_kai", "UNKNOWN")),
        ("Player count", record.get("max_players", "")),
        ("Configuration", record.get("requirements", "")),
        ("Current playability", "UNVERIFIED"),
    ]
    content = "".join(f"<p><span class='label'>{escape(k)}</span><br>{escape(str(v or 'Unknown'))}</p>" for k,v in lines)
    return content + '<p><a href="https://docs.google.com/spreadsheets/d/15pfhL36qmC-iKr8MNjNXNLwgacG4VOmkfvwVxV5vGzo/edit?gid=0" target="_blank" rel="noopener">Community compatibility source ↗</a></p>'

@router.get("/online-services", response_class=HTMLResponse)
def online_services(request: Request):
    return page("Online services", """<div class="eyebrow">Networking and RetroAchievements</div>
<h1>Online services</h1><p class="muted">Quick launch links for your local services. Service health and secure profile switching are planned; links are not live health checks.</p>
<div class="grid"><div class="card"><h2>xeRAbora</h2><p class="muted">Achievement relay and local web dashboard.</p>
<a href="http://retrodb.it.gattaca.house:18280/" target="_blank" rel="noopener">Open xeRAbora ↗</a>
<p class="label">Current player selection remains in the xeRAbora console; web switching requires authentication and a dedicated privileged helper.</p></div>
<div class="card"><h2>XLink Kai</h2><p class="muted">System-link LAN tunnelling via RetroNAS.</p>
<a href="http://xlinkkai:34522/" target="_blank" rel="noopener">Open XLink Kai ↗</a></div>
<div class="card"><h2>RetroAchievements</h2><a href="https://retroachievements.org/" target="_blank" rel="noopener">Website ↗</a></div>
<div class="card"><h2>RetroDB source</h2><a href="https://github.com/theretrobristolian/retrodb" target="_blank" rel="noopener">GitHub repository ↗</a></div></div>""", guest=is_guest(request))

@router.get("/game/{item_id}", response_class=HTMLResponse)
def game_details(item_id: int, request: Request, db: Session = Depends(get_session)):
    item = db.get(LibraryItem, item_id)
    if item is None:
        raise HTTPException(404, "Game not found")
    platform = db.get(Platform, item.platform_id)
    label = escape(name(item, platform.slug if platform else None))
    def detail(k, v):
        if v is None or v == "":
            return ""
        return f"<p class='detail-field'><span class='label'>{escape(k)}</span><br>{escape(str(v))}</p>"
    technical = (detail("Filename", item.filename) +
                 detail("File format", item.extension.upper()) +
                 detail("Size (GiB)", f"{item.size_bytes / 1024**3:.2f}") +
                 detail("Collection path", item.relative_path))
    from retrodb.artwork import game_metadata, art_location, serial_key
    meta = game_metadata(item.ra_game_id)
    serial = serial_key(item.filename) or serial_key(item.relative_path)
    icon_url = art_location(item.ra_game_id, "icon", meta.get("ImageIcon"))
    box_url = art_location(item.ra_game_id, "box", meta.get("ImageBoxArt"))
    psbbn_url = "/art/psbbn/" + serial if serial else None
    header_icon = (f'<img class="game-ra-icon" src="{escape(icon_url, quote=True)}" '
                   'alt="RetroAchievements game icon" loading="lazy">' if icon_url else '')
    # Choose only one cover, with RA preferred and PSBBN on load failure.
    # The fallback is never displayed alongside the preferred artwork.
    if box_url:
        fallback_attr = (f' data-fallback="{escape(psbbn_url, quote=True)}"'
                         if psbbn_url else "")
        artwork = (f'<img class="game-cover" src="{escape(box_url, quote=True)}"'
                   f'{fallback_attr} alt="Game cover" loading="lazy" '
                   'onerror="if(this.dataset.fallback){this.src=this.dataset.fallback;'
                   'delete this.dataset.fallback;}else{this.hidden=true;'
                   'this.nextElementSibling.hidden=false;}">'
                   '<p class="muted" hidden>Cover art unavailable for this release.</p>')
    elif psbbn_url:
        artwork = (f'<img class="game-cover" src="{escape(psbbn_url, quote=True)}"'
                   ' alt="Game cover" loading="lazy" '
                   'onerror="this.hidden=true;this.nextElementSibling.hidden=false">'
                   '<p class="muted" hidden>Cover art unavailable for this release.</p>')
    else:
        artwork = '<p class="muted">Cover art unavailable for this release.</p>'
    from retrodb.providers.lizardbyte import load as game_db_extra
    extra = game_db_extra(item.id)
    ratings = extra.get("age_ratings", [])
    modes = extra.get("game_modes", [])
    release_years = extra.get("release_dates", [])
    release = (detail("Released", meta.get("Released")) +
               detail("Publisher", meta.get("Publisher")) +
               detail("Developer", meta.get("Developer")) +
               detail("Genre", meta.get("Genre")))
    online = online_record(item)
    flags = []
    def badge(symbol, text):
        flags.append(f'<span class="feature-chip"><span class="feature-glyph" aria-hidden="true">{symbol}</span>{escape(text)}</span>')
    if ra_supported(item):
        badge("🏆", "RetroAchievements verified")
    elif item.ra_game_id and platform and platform.slug in ("playstation", "playstation-2"):
        # Only label redundant copies when BOTH records share a confirmed RA ID.
        # Never infer coverage from matching titles or disc serials.
        verified_copy = db.scalar(
            select(LibraryItem).where(
                LibraryItem.platform_id == item.platform_id,
                LibraryItem.id != item.id,
                LibraryItem.is_missing.is_(False),
                LibraryItem.ra_game_id == item.ra_game_id,
                func.lower(LibraryItem.ra_match_status) == "matched",
            ).order_by(LibraryItem.id).limit(1)
        )
        if verified_copy is not None:
            flags.append(
                '<a class="feature-chip" href="/game/' + str(verified_copy.id) +
                '" title="This image is not verified, but another copy of this RA game is. No additional RA copy is needed.">'
                '<span class="feature-glyph" aria-hidden="true">▣</span>'
                'RA covered by another copy</a>'
            )
    if online:
        if str(online.get("historical_online", "")).upper() in ("YES", "TRUE", "SUPPORTED"):
            badge("◎", "Original online play")
        if str(online.get("xlink_kai", "")).upper() in ("YES", "TRUE", "SUPPORTED"):
            badge("⇄", "XLink Kai listed")
        players = str(online.get("max_players") or "").strip()
        if players and players.lower() not in ("unknown", "n/a", "none"):
            badge("♟", "Online players: " + players)
    for mode in modes:
        if mode in ("Single player", "Multiplayer", "Co-operative"):
            badge("♟", mode)
    for age in ratings:
        badge("▣", str(age.get("system", "")) + " " + str(age.get("rating", "")))
    capabilities = ('<div class="feature-strip" aria-label="Known game features">' +
                    "".join(flags) + '</div>') if flags else ""
    extra_info = ""
    if release_years:
        years = sorted({int(v["year"]) for v in release_years if isinstance(v.get("year"), int)})
        if years:
            extra_info += detail("Platform release year", ", ".join(map(str, years)))
    if not meta.get("Genre") and extra.get("genres"):
        extra_info += detail("Genres", ", ".join(extra["genres"][:4]))
    meta_panel = ('<div class="info-pairs">' + release + '</div>') if release else '<p class="muted">No release metadata available yet.</p>'
    online_panel = online_details(online) if online else ""
    game_panel = (f'<section class="card"><h2>Game information</h2>{meta_panel}'
                  f'{extra_info}<p class="muted meta-source">Sources: RetroAchievements' + (' + GameDB/IGDB' if extra else '') + '</p></section>')
    collection_panel = (f'<section class="card"><h2>Your copy</h2>'
                        f'{detail("Console", platform.name if platform else None)}'
                        f'{detail("Disc ID", serial)}'
                        f'<details class="technical-details"><summary>File and collection details</summary>{technical}</details></section>')
    online_section = (f'<section class="card"><h2>Online compatibility</h2>{online_panel}</section>' if online else "")
    ra_link = (f'<a href="https://retroachievements.org/game/{int(item.ra_game_id)}"'
               ' target="_blank" rel="noopener noreferrer">View achievements on RetroAchievements ↗</a>'
               if item.ra_game_id else "")
    body = f"""<div class="crumb"><a href="/">Consoles</a> /
<a href="/library/{quote(platform.slug) if platform else ''}">{escape(platform.name if platform else 'Library')}</a> / {label}</div>
<div class="game-title-row">{header_icon}<div><h1>{label}</h1>
<p class="muted">{escape(platform.name if platform else 'Game library')}{' · ' + escape(serial) if serial else ''}</p></div></div>
{capabilities}
<div class="detail"><section class="card game-art-card"><h2>Cover art</h2><div class="game-art-grid">{artwork}</div></section>
{game_panel}{collection_panel}
{f'<section class="card"><h2>Achievements</h2>{ra_link}</section>' if ra_link else ''}
{online_section}</div>"""
    return page(name(item, platform.slug if platform else None), body, guest=is_guest(request))

@router.get("/management", response_class=HTMLResponse)
def management(db: Session = Depends(get_session)):
    indexed = db.scalar(select(func.count(LibraryItem.id)).where(LibraryItem.is_missing.is_(False))) or 0
    missing = db.scalar(select(func.count(LibraryItem.id)).where(LibraryItem.is_missing.is_(True))) or 0
    rows = "".join(f"<tr><td>{escape(p.name)}</td><td>{c:,}</td></tr>" for p,c in platform_counts(db))
    return page("Management", f"""<div class="eyebrow">Administration · Read-only preview</div>
<h1>Library management</h1><p class="muted">v1 exposes status without executing shell commands or modifying RetroNAS files.
Web-triggered jobs will require authenticated, permission-scoped background workers.</p>
<div class="grid"><div class="card"><div class="label">Indexed files</div><div class="metric">{indexed:,}</div></div>
<div class="card"><div class="label">Marked missing</div><div class="metric">{missing:,}</div></div>
<div class="card"><div class="label">RetroDB API</div><h2>Connected</h2><a href="/health">Database health →</a></div></div>
<h2>Library sources</h2><div class="panel"><table><thead><tr><th>Console</th><th>Indexed files</th></tr></thead>
<tbody>{rows or '<tr><td colspan="2">No indexed games yet</td></tr>'}</tbody></table></div>
<h2>Maintenance actions (coming next)</h2><div class="grid">
<div class="card"><h2>↻ Rescan library</h2><p class="muted">Queue a safe read-only RetroNAS inventory scan, then show progress and logs.</p><span class="pill">Not yet enabled</span></div>
<div class="card"><h2>↻ Refresh compatibility</h2><p class="muted">Refresh RetroAchievements, community DNS and XLink source evidence.</p><span class="pill">Not yet enabled</span></div>
<div class="card"><h2>↑ Update RetroDB</h2><p class="muted">Review and explicitly approve application updates; never auto-update xeRAbora binaries.</p><span class="pill">Not yet enabled</span></div></div>
<h2>Project resources</h2><p><a href="https://github.com/theretrobristolian/retrodb" target="_blank" rel="noopener">RetroDB on GitHub ↗</a></p>""")
