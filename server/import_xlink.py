#!/usr/bin/env python3
"""Import manually verified PS2 LAN titles from Team XLink's public wiki.
Title-level evidence only; source offers no disc serials or per-region guarantees.
"""
import json
import urllib.parse
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

URL = "https://www.teamxlink.co.uk/wiki/PlayStation_2"

class WikiTables(HTMLParser):
    """Extract HTML tables while preserving rows through nested markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []
        self.row = None
        self.cell = None
        self.cell_tag = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append([])
        elif tag == "tr" and self.stack:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []
            self.cell_tag = tag
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == self.cell_tag and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
            self.cell_tag = None
        elif tag == "tr" and self.row is not None:
            if self.stack:
                self.stack[-1].append(self.row)
            self.row = None
        elif tag == "table" and self.stack:
            table = self.stack.pop()
            if table:
                self.tables.append(table)

def select_ps2_table(tables):
    # The page has a profile/infobox as well as its game list. The latter
    # is identified by actual PS2 LAN games, not brittle template headings.
    anchors = {"timesplitters 2", "star wars: battlefront", "gran turismo 4",
               "atv offroad fury 2", "armored core: last raven"}
    candidates = []
    for table in tables:
        first_cells = [row[0].casefold().strip() for row in table if row]
        score = len(set(first_cells) & anchors)
        if score >= 2 and len(table) >= 20:
            candidates.append((score, table))
    if len(candidates) != 1:
        examples = [dict(rows=len(t), first=t[:2]) for t in tables[:6]]
        raise ValueError("Could not uniquely locate PS2 game table "
                         f"({len(candidates)} candidates, {len(tables)} tables). "
                         f"Extracted table samples: {examples!r}")
    rows = candidates[0][1]
    return [row for row in rows if row and row[0].casefold().strip() not in ("title", "game")]


def parse_wikitext(text):
    """Parse the PS2 supported-games wiki table from MediaWiki source text."""
    section = re.search(r"(?im)^={2,6}\\s*Supported Games\\s*={2,6}\\s*$", text)
    if not section:
        raise ValueError("MediaWiki page has no Supported Games section")
    rest = text[section.end():]
    next_heading = re.search(r"(?m)^={2,6}[^=].*={2,6}\\s*$", rest)
    if next_heading:
        rest = rest[:next_heading.start()]
    titles = []
    for raw in rest.splitlines():
        line = raw.strip()
        if not line.startswith("|") or line.startswith("|-") or line.startswith("|+"):
            continue
        first = line[1:].split("||", 1)[0].strip()
        # A MediaWiki row can carry cell attributes before its visible content.
        if "|" in first:
            first = first.rsplit("|", 1)[-1].strip()
        first = re.sub(r"\\[\\[([^]|]+)\\|([^]]+)\\]\\]", r"\\2", first)
        first = re.sub(r"\\[\\[([^]]+)\\]\\]", r"\\1", first)
        first = re.sub(r"<[^>]+>", "", first)
        first = re.sub(r"'{2,}", "", first).strip()
        if first and first.casefold() not in ("title", "game"):
            titles.append(first)
    return titles

def fetch_url(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "RetroDB-online-compatibility/0.2 (personal cataloguer)",
        "Accept": "text/html, application/json, text/plain",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        body = response.read(5_000_000).decode("utf-8", "replace")
        return body, f"HTTP {response.status}, type={response.headers.get('Content-Type','unknown')}, bytes={len(body.encode('utf-8'))}"

def import_xlink(destination, source=URL):
    diagnostics = []
    titles = []
    try:
        html, details = fetch_url(source)
        parser = WikiTables()
        parser.feed(html)
        diagnostics.append(f"HTML: {details}, tables={len(parser.tables)}")
        if parser.tables:
            try:
                titles = [row[0].strip() for row in select_ps2_table(parser.tables) if row and row[0].strip()]
            except ValueError as exc:
                diagnostics.append(f"HTML selection: {exc}")
    except (OSError, ValueError) as exc:
        diagnostics.append(f"HTML request: {exc}")

    if len(titles) < 20:
        # Query the underlying wiki source instead of relying on page HTML.
        base = "https://www.teamxlink.co.uk/wiki/"
        urls = [
            base + "api.php?" + urllib.parse.urlencode({
                "action":"parse","page":"PlayStation_2","prop":"wikitext","format":"json"}),
            base + "index.php?title=PlayStation_2&action=raw",
        ]
        for url in urls:
            try:
                body, details = fetch_url(url)
                if "api.php?" in url:
                    payload = json.loads(body)
                    text = payload["parse"]["wikitext"]["*"]
                else:
                    text = body
                found = parse_wikitext(text)
                diagnostics.append(f"Wiki source: {details}, titles={len(found)}")
                if len(found) >= 20:
                    titles = found
                    break
            except (OSError, ValueError, KeyError, TypeError) as exc:
                diagnostics.append(f"Wiki source request: {exc}")

    titles = list(dict.fromkeys(t for t in titles if t and t.casefold() not in ("title","game")))
    fallback = False
    if len(titles) < 20:
        snapshot = Path(__file__).resolve().parent / "data/xlink-ps2-snapshot.json"
        if snapshot.is_file():
            saved = json.loads(snapshot.read_text(encoding="utf-8"))
            if saved.get("source_kind") == "bundled_partial_snapshot" and len(saved.get("titles", [])) >= 20:
                titles = saved["titles"]
                fallback = True
                print(f"[WARN] Direct XLink site returned unusable content. Using bundled PARTIAL snapshot ({len(titles)} of {saved.get('declared_source_count', '?')} documented titles; snapshot date {saved.get('as_of', 'unknown')}).")
                print("[INFO] Source diagnostics: " + " | ".join(diagnostics))
    if not 20 <= len(titles) <= 200:
        raise ValueError(
            f"Found {len(titles)} PS2 titles; refusing to replace existing data. "
            + " | ".join(diagnostics)
        )
    entries = [{"title": title, "source_url": URL,
                "evidence": "Team XLink manually verified PS2 LAN list",
                "match_scope": "title_only",
                "source_confidence": "bundled_partial_snapshot" if fallback else "direct_site"} for title in titles]
    payload = {"schema_version":1, "platform":"playstation-2", "source":URL,
               "updated_at":datetime.now(timezone.utc).isoformat(), "records":entries,
               "source_kind":"bundled_partial_snapshot" if fallback else "direct_site"}
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False)+"\\n", encoding="utf-8")
    tmp.replace(dest)
    print(f"[OK] Imported {len(entries)} Team XLink PS2 LAN titles (title-level evidence; {'PARTIAL SNAPSHOT' if fallback else 'live source'})")

if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit("Usage: python3 server/import_xlink.py DESTINATION.json")
    import_xlink(sys.argv[1])
