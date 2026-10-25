#!/usr/bin/env python3
"""Offline-first, platform-neutral network-play catalogue for RetroDB.

CLI: python3 server/online_catalogue.py import-ps2 SOURCE.csv OUTPUT.json
Source is an exported copy of the community PS2 online spreadsheet.
Never treat a missing listing as proof of no network support.
"""
import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://docs.google.com/spreadsheets/d/15pfhL36qmC-iKr8MNjNXNLwgacG4VOmkfvwVxV5vGzo/edit?gid=0#gid=0"
ONLINE_COLUMNS = [
    "Game", "File", "Disc ID", "Region", "Original online", "Original host",
    "LAN", "XLink Kai", "Community DNS reported", "DNS / service reference",
    "Community report", "Players", "Co-op", "DNAS / setup",
    "Hardware notes", "Source", "Last source update", "Connection methods", "Currently playable", "Source confidence", "XLink evidence",
    "Community XLink report", "XLink catalogue", "XLink conflict",
]
SERIAL_RE = re.compile(r"\b(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS|SCPS)[_.\s-]*([0-9]{3})[.\s_-]*([0-9]{2})\b", re.I)

def serial(value):
    text = str(value or "").replace(",", ".").upper()
    m = SERIAL_RE.search(text)
    return (m.group(1) + "-" + m.group(2) + m.group(3)) if m else ""

def flag(value):
    v = str(value or "").strip().upper()
    if v.startswith("YES"): return "YES"
    if v.startswith("NO"): return "NO"
    if v in ("", "-", "NOT TESTED", "N/A", "UNKNOWN"): return "UNKNOWN"
    return "REVIEW"

def build_record(row):
    # Community sheet columns A:AC (header on row 4); source indices fixed and documented.
    def get(i): return row[i].strip() if i < len(row) else ""
    # Community CSV exports may carry an extra leading/blank column.
    # Find the release ID anywhere in the row, then resolve the surrounding schema.
    ids = [(i, serial(v)) for i, v in enumerate(row) if serial(v)]
    if not ids: return None
    # Game ID is column I in the published sheet, possibly offset in CSV export.
    i, disc = min(ids, key=lambda item: abs(item[0] - 8))
    offset = i - 8
    def at(i): return get(i + offset) if i + offset >= 0 else ""
    return {
        "platform": "playstation-2", "disc_id": disc, "title": at(0),
        "region": at(7), "historical_online": "YES", # sheet is an online-games list
        "original_host": at(5), "dns_compatible": flag(at(2)),
        "dns_address_or_provider": at(4), "network_status": at(2),
        "xlink_kai": flag(at(14)), "lan": "UNKNOWN", # XLink != definitive LAN evidence
        "max_players": at(13), "co_op": flag(at(11)),
        "requirements": at(18), "community_notes": at(28),
        "console_compatibility": at(17), "last_source_update": at(3),
        "source_url": SOURCE_URL, "source_type": "community spreadsheet",
        "service_methods": ([{"kind":"custom_dns","reference":at(4),"evidence":at(2)}] if at(4) else []) +
            ([{"kind":"lan_tunnel","service":"XLink Kai","evidence":at(14)}] if flag(at(14)) == "YES" else []),
        "currently_playable": "UNVERIFIED",
    }

def import_ps2(source, destination):
    with open(source, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    # Detect the header instead of assuming a stable physical row position.
    headers = [i for i, row in enumerate(rows[:25]) if any("game tittle" in cell.casefold() or "game title" in cell.casefold() for cell in row) and any("game id" in cell.casefold() for cell in row)]
    if not headers:
        raise ValueError("Unrecognised CSV: expected Game Tittle and Game ID column headings")
    items = [v for row in rows[headers[0]+1:] if (v := build_record(row))]
    if not items:
        examples = [row[:12] for row in rows[headers[0]+1:headers[0]+4]]
        raise ValueError(f"Imported 0 disc IDs; refusing to replace catalogue. First data rows: {examples!r}")
    payload = {"schema_version":1, "source":SOURCE_URL,
               "imported_at":datetime.now(timezone.utc).isoformat(),
               "records":items}
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    print(f"[OK] Imported {len(items)} release-specific PS2 network records to {dest}")
    return payload

def load(path):
    if not Path(path).is_file(): return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {(r["platform"], r["disc_id"]): r for r in payload.get("records", [])}

def normalized_title(value):
    """Conservative title-only key; never conflate release IDs with titles."""
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = re.sub(r"\\([^)]*\\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())

def load_xlink(path):
    """Optional official XLink title catalogue with explicit title-level provenance."""
    if not Path(path).is_file():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {normalized_title(item["title"]): item for item in payload.get("records", [])
            if normalized_title(item.get("title"))}

def enrich_with_xlink(row, xlink):
    """Merge evidence without overwriting or discarding either source.

    Row indices 0-18 are the legacy workbook format. Appended columns document
    the separate observations; title matches are not release-level verification.
    """
    candidate = xlink.get(normalized_title(row[0]))
    community_xlink = row[7]  # retain source's raw YES / NO / UNKNOWN
    official = "YES (title-level)" if candidate else "UNKNOWN"
    conflict = ("REVIEW: community NO / XLink listed"
                if candidate and community_xlink == "NO" else "")
    confidence = ("Disc ID + XLink title" if row[4] == "YES" and candidate else
                  "Disc ID only" if row[4] == "YES" else
                  "XLink title only" if candidate else "No matching evidence")
    provenance = (candidate or {}).get("source_url", "")
    if candidate and (candidate or {}).get("source_confidence") == "bundled_partial_snapshot":
        confidence += " (partial snapshot)"
    # Native LAN evidence can be inferred for the title listed by XLink,
    # never for a specific release.
    if candidate:
        row[6] = "YES (title-level)"
        methods = [part.strip() for part in row[17].split(",") if part.strip()]
        if "lan_tunnel" not in methods:
            methods.append("lan_tunnel")
        row[17] = ", ".join(methods)
    # Effective summary XLink signal includes either source, while its
    # original reported value remains in the dedicated community column.
    row[7] = ("YES (title-level)" if candidate else community_xlink)
    row.extend([confidence, provenance, community_xlink, official, conflict])
    return row

def report_row(audit, catalogue):
    disc = serial(audit.get("local_serial") or audit.get("path") or "")
    platform = str(audit.get("platform",""))
    match = catalogue.get(("playstation-2", disc)) if platform == "Sony PlayStation 2" else None
    return [
        audit.get("ra_game_title") or audit.get("gamedb_title") or audit.get("local_friendly_title") or Path(audit.get("path","")).stem,
        Path(audit.get("path","")).name, disc, (match or {}).get("region") or audit.get("local_region",""),
        (match or {}).get("historical_online","UNKNOWN"), (match or {}).get("original_host",""),
        (match or {}).get("lan","UNKNOWN"), (match or {}).get("xlink_kai","UNKNOWN"),
        (match or {}).get("dns_compatible","UNKNOWN"),
        (match or {}).get("dns_address_or_provider",""),
        (match or {}).get("network_status","UNKNOWN"),
        (match or {}).get("max_players",""), (match or {}).get("co_op","UNKNOWN"),
        (match or {}).get("requirements",""), (match or {}).get("community_notes",""),
        (match or {}).get("source_url",""), (match or {}).get("last_source_update",""),
        ", ".join(method.get("kind","") for method in (match or {}).get("service_methods",[])),
        (match or {}).get("currently_playable","UNVERIFIED"),
    ]

if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("operation", choices=["import-ps2"])
    cli.add_argument("source")
    cli.add_argument("destination")
    args = cli.parse_args()
    import_ps2(args.source, args.destination)
