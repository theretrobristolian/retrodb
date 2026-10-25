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
*{box-sizing:border-box}body{margin:0}a{color:inherit;text-decoration:none}a:hover{color:#9ebeff}
header{position:sticky;top:0;z-index:20;border-bottom:1px solid #263047;background:#11192c;padding:18px max(24px,calc((100vw - 1200px)/2))}
header .bar{display:flex;gap:25px;align-items:center;flex-wrap:wrap}
.brand{font-size:24px;font-weight:800;letter-spacing:-1px;color:#f6f8ff}
nav{display:flex;gap:18px;color:#afc0da;font-size:14px}main{max-width:1200px;margin:auto;padding:38px 24px 70px}
h1{font-size:34px;letter-spacing:-1.3px;margin:0 0 8px}h2{font-size:21px;margin:28px 0 16px}
p{line-height:1.6}.muted{color:#9daeca}.eyebrow{color:#7caeff;text-transform:uppercase;font-size:12px;font-weight:700;letter-spacing:1.7px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.card{display:block;background:#151f32;border:1px solid #293952;border-radius:15px;padding:22px;min-height:120px}
.card:hover{border-color:#527cc6}.card h2{margin:4px 0 9px}.metric{font-size:34px;font-weight:750}
.pill{background:#243651;color:#c4daff;padding:4px 9px;border-radius:30px;font-size:12px;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;color:#91a8c8;font-weight:600;background:#17233a}
th,td{padding:13px 12px;border-bottom:1px solid #27334a}tr:hover td{background:#18243a}
.panel.library-scroll{max-height:70vh;overflow:auto;-webkit-overflow-scrolling:touch;touch-action:pan-x pan-y;overscroll-behavior:contain}
.library-scroll thead th{position:sticky;top:0;z-index:2;box-shadow:0 1px #344760}
.library-scroll table{min-width:0;table-layout:fixed}
.library-scroll td[data-column="title"]{overflow-wrap:anywhere;word-break:normal;line-height:1.4}
.library-scroll th[data-column="title"]{width:43%}
.library-scroll th[data-column="disc"]{width:25%}
.library-scroll th[data-column="id"]{width:13%}
.library-scroll th[data-column="ra"]{width:14%}
.library-scroll th[data-column="format"]{width:9%}
.library-scroll td[data-column="disc"]{overflow-wrap:anywhere}
.library-scroll .pill.serial{white-space:normal;overflow-wrap:anywhere;line-height:1.3}
.ra-icon{display:inline-block;position:relative;font-size:19px;line-height:1;white-space:nowrap}
.ra-icon.yes{filter:sepia(1) saturate(3);color:#f5ca65}
.ra-icon.no{filter:grayscale(1);opacity:.35}
.ra-icon.no::after{content:"×";position:absolute;right:-4px;bottom:-7px;font-size:15px;font-weight:900;color:#e4e8f0;text-shadow:0 0 2px #10192d}
@media(max-width:760px){
 .library-scroll table{width:100%;min-width:0;font-size:12px}
 .library-scroll th,.library-scroll td{padding:9px 4px}
 .library-scroll th[data-column="title"]{width:42%}
 .library-scroll th[data-column="disc"]{width:31%}
 .library-scroll th[data-column="id"]{width:13%}
 .library-scroll th[data-column="ra"]{width:14%}
 .library-scroll th[data-column="format"]{width:12%}
 .library-scroll .pill.serial{padding:3px 5px;font-size:11px}
 .library-scroll td[data-column="id"]{overflow-wrap:anywhere}
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
.detail{display:grid;grid-template-columns:1fr 1fr;gap:18px}.detail .card{min-height:0}
@media(max-width:760px){.detail{grid-template-columns:1fr}main{padding:24px 14px}th,td{padding:9px 6px}header{padding:16px}}
"""

def is_guest(request: Request) -> bool:
    from retrodb.session_auth import COOKIE, user_from_cookie
    return user_from_cookie(request.cookies.get(COOKIE, "")) == "__retrodb_guest__"

def page(title: str, body: str, guest: bool = False) -> HTMLResponse:
    from retrodb.session_auth import csrf_token
    signout_csrf = csrf_token()
    private_nav = '' if guest else '<a href="/management">Management</a><a href="/online-services">Online services</a>'
    logout_label = "Leave guest view" if guest else "Sign out"
    heading = escape(title)
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
<style>{CSS}</style></head><body><header><div class="bar"><a class="brand" href="/">◈ RetroDB</a>
<nav><a href="/">Consoles</a><a href="/library">All games</a>{private_nav}
<a href="https://github.com/theretrobristolian/retrodb" target="_blank" rel="noopener">GitHub ↗</a><form method="post" action="/logout" style="display:inline"><input type="hidden" name="csrf_token" value="{signout_csrf}"><button type="submit" style="border:0;color:#afc0da;background:transparent;cursor:pointer">{logout_label}</button></form></nav></div></header>
<main>{body}</main></body></html>""")

SERIAL_RE = re.compile(r"(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)[_. -]*([0-9]{3})[. -]*([0-9]{2})", re.I)

def disc_id(item: LibraryItem) -> str:
    match = SERIAL_RE.search(item.filename) or SERIAL_RE.search(item.relative_path)
    return f"{match.group(1).upper()}-{match.group(2)}{match.group(3)}" if match else ""

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

def name(item: LibraryItem, slug: str | None = None) -> str:
    if item.ra_game_title and item.ra_game_title.strip():
        return item.ra_game_title.strip()
    catalogue_title = gamedb_title(item, slug)
    if catalogue_title:
        return catalogue_title
    label = PurePosixPath(item.filename).stem
    label = re.sub(r"^(?:OLD_|NEW_)", "", label, flags=re.I)
    label = SERIAL_RE.sub("", label)
    label = label.replace("_", " ")
    label = re.sub(r"\s*\((?:USA|Europe|Japan|World|En|Fr|De|Rev[^)]*)\)\s*$", "", label, flags=re.I)
    return re.sub(r"\s{2,}", " ", label).strip(" -._") or PurePosixPath(item.filename).stem

def ra_supported(item: LibraryItem) -> bool:
    return bool(item.ra_game_id and (item.ra_match_status or "").lower() == "matched")

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
        badge = 'Verified RetroAchievements hash' if supported else ('No verified RetroAchievements match: ' + (item.ra_match_status or 'unknown'))
        rows.append(f"""<tr><td data-column="title"><a href="/game/{item.id}">{escape(name(item, item_slug(item)))}</a></td>
<td data-column="disc">{'<span class="pill serial">'+escape(disc)+'</span>' if disc else '—'}</td>
<td data-column="id">{item.ra_game_id or '—'}</td>
<td data-column="ra"><span class="ra-icon {'yes' if supported else 'no'}" role="img" aria-label="{escape(badge,quote=True)}" title="{escape(badge,quote=True)}">🏆</span></td>
<td data-column="format">{escape(item.extension.upper())}</td></tr>""")
    prev_link = f'<a class="btn" href="{escape(link(page=page_number-1),quote=True)}">← Previous</a>' if page_number > 1 else ''
    next_link = f'<a class="btn" href="{escape(link(page=page_number+1),quote=True)}">Next →</a>' if count > page_number*100 else ''
    heading = escape(platform.name if platform else "All games")
    return page(heading, f"""<div class="crumb"><a href="/">Consoles</a> / {heading}</div>
<h1>{heading}</h1><p class="muted">{count:,} indexed game files · Up to 100 per page</p>
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
<label><input type="checkbox" data-toggle="id" checked> RA ID</label>
<label><input type="checkbox" data-toggle="ra" checked> Achievements</label>
<label><input type="checkbox" data-toggle="format"> Format</label></div>
<div class="toolbar"><a class="pill" href="{escape(link(letter='',page=1),quote=True)}">All</a>{alphabet}</div>
<div class="panel library-scroll"><table><thead><tr><th data-column="title">Game</th><th data-column="disc">Disc ID</th>
<th data-column="id">RA ID</th><th data-column="ra" title="RetroAchievements">RA</th><th data-column="format">Format</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="5">No games match the current filters.</td></tr>'}</tbody></table></div>
<p class="muted">Gold 🏆 means a verified RA disc hash and RA game ID; muted crossed trophy means no verified match in the current audit (not necessarily unsupported). Names without RA titles are cleaned filename fallbacks; exact Excel identity enrichment is not yet stored here.</p>
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
        return f"<p><span class='label'>{escape(k)}</span><br>{escape(str(v or 'Not available'))}</p>"
    info = (detail("Console", platform.name if platform else None)
            + detail("Filename", item.filename) + detail("File format", item.extension.upper())
            + detail("Size (GiB)", f"{item.size_bytes / 1024**3:.2f}")
            + detail("RetroAchievements ID", item.ra_game_id)
            + detail("RA hash status", item.ra_match_status)
            + detail("Collection path", item.relative_path))
    return page(name(item, platform.slug if platform else None), f"""<div class="crumb"><a href="/">Consoles</a> /
<a href="/library/{quote(platform.slug) if platform else ''}">{escape(platform.name if platform else 'Library')}</a> / {label}</div>
<h1>{label}</h1><p class="muted">Library record and release information</p>
<div class="detail"><section class="card"><h2>Release and collection</h2>{info}</section>
<section class="card"><h2>Achievements</h2><p class="muted">Your indexed RetroAchievements data appears here.
Live profile progress and badge artwork are planned for the next version.</p>
{detail("RA game title", item.ra_game_title)}</section>
<section class="card"><h2>Online play</h2>{online_details(online_record(item))}</section>
<section class="card"><h2>Co-op and player counts</h2><p class="muted">Couch co-op, online co-op, split-screen and competitive multiplayer are distinct capabilities. Verified PS2 Co-Optimus records are not yet imported; no player limits are guessed.</p><p><a href="https://www.co-optimus.com/system/6/playstation-2.html" target="_blank" rel="noopener">Browse PS2 co-op listings ↗</a></p></section>\n<section class="card"><h2>Artwork, manual and controls</h2><p class="muted">Metadata, manuals, controller guidance
and cover-art indexing are planned. No external artwork is downloaded automatically.</p></section></div>""", guest=is_guest(request))

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
