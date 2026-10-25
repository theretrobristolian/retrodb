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
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is None: self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip()); self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None: self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table); self.table = None

def import_xlink(destination, source=URL):
    req = urllib.request.Request(source, headers={"User-Agent":"RetroDB-compatible-import/0.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        html = response.read(5_000_000).decode("utf-8", "replace")
    parser = WikiTables()
    parser.feed(html)
    candidates = []
    for table in parser.tables:
        if not table: continue
        heading = " ".join(table[0]).lower()
        if "versus" in heading and "co-op" in heading and "players" in heading:
            candidates.append(table)
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one PS2 supported-games table; found {len(candidates)}")
    entries = []
    for row in candidates[0][1:]:
        if not row: continue
        title = re.sub(r"\\s+", " ", row[0]).strip()
        if title: entries.append({"title": title, "source_url": URL,
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
