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
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://docs.google.com/spreadsheets/d/15pfhL36qmC-iKr8MNjNXNLwgacG4VOmkfvwVxV5vGzo/edit?gid=0#gid=0"
ONLINE_COLUMNS = [
    "Game", "File", "Disc ID", "Region", "Original online", "Original host",
    "LAN", "XLink Kai", "Private server / DNS", "DNS or service",
    "Network status", "Players", "Co-op", "DNAS / setup",
    "Hardware notes", "Evidence", "Last source update",
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
    disc = serial(get(8))
    if not disc: return None
    return {
        "platform": "playstation-2", "disc_id": disc, "title": get(0),
        "region": get(7), "historical_online": "YES", # sheet is an online-games list
        "original_host": get(5), "dns_compatible": flag(get(2)),
        "dns_address_or_provider": get(4), "network_status": get(2),
        "xlink_kai": flag(get(14)), "lan": "UNKNOWN", # XLink != definitive LAN evidence
        "max_players": get(13), "co_op": flag(get(11)),
        "requirements": get(18), "community_notes": get(28),
        "console_compatibility": get(17), "last_source_update": get(3),
        "source_url": SOURCE_URL, "source_type": "community spreadsheet",
        "service_methods": [{"kind":"custom_dns","value":get(4),"status":flag(get(2))}]
            if get(4) else [],
    }

def import_ps2(source, destination):
    with open(source, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    # Fail closed when given an unrelated or altered sheet.
    if len(rows) < 5 or "Game" not in rows[3][0]:
        raise ValueError("Expected PS2 online community CSV, with game header on row 4")
    items = [v for row in rows[4:] if (v := build_record(row))]
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
    ]

if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("operation", choices=["import-ps2"])
    cli.add_argument("source")
    cli.add_argument("destination")
    args = cli.parse_args()
    import_ps2(args.source, args.destination)
