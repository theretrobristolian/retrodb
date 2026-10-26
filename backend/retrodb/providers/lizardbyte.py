"""Read-only view of curated, cached LizardByte GameDB enrichment.

Cache is populated explicitly by server/enrich-gamedb.py; no requests on page loads.
"""
from __future__ import annotations
import json
from pathlib import Path

CACHE = Path("/var/cache/retrodb/providers/lizardbyte")

def load(item_id: int) -> dict:
    try:
        path = CACHE / f"{int(item_id)}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("source") == "lizardbyte-gamedb" else {}
    except (OSError, ValueError, TypeError):
        return {}
