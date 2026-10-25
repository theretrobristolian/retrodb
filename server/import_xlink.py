#!/usr/bin/env python3
"""Import manually verified PS2 LAN titles from Team XLink's public wiki.
Title-level evidence only; source offers no disc serials or per-region guarantees.
"""
import json
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


def import_xlink(destination, source=URL):
    req = urllib.request.Request(source, headers={"User-Agent":"RetroDB-compatible-import/0.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        html = response.read(5_000_000).decode("utf-8", "replace")
    parser = WikiTables()
    parser.feed(html)
    entries = []
    for row in select_ps2_table(parser.tables):
        title = re.sub(r"\\s+", " ", row[0]).strip()
        if title:
            entries.append({"title": title, "source_url": URL,
                            "evidence": "Team XLink manually verified PS2 LAN list",
                            "match_scope": "title_only"})
    if len(entries) < 20:
        raise ValueError(f"Only {len(entries)} titles found; refusing to replace an existing catalogue")
    payload = {"schema_version":1, "platform":"playstation-2", "source":URL,
               "updated_at":datetime.now(timezone.utc).isoformat(), "records":entries}
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    tmp.replace(dest)
    print(f"[OK] Imported {len(entries)} Team XLink PS2 LAN titles (title-level evidence)")

if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit("Usage: python3 server/import_xlink.py DESTINATION.json")
    import_xlink(sys.argv[1])
