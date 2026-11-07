#!/usr/bin/env python3
"""Create a human-readable multi-console XLSX from RetroDB's RA audit CSV."""
import csv
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape
sys.path.insert(0, str(Path(__file__).resolve().parent))
from online_catalogue import ONLINE_COLUMNS, load as load_online, load_xlink, report_row as online_report_row, enrich_with_xlink

COLS = ['Game name','File name','Disc ID','RA compatible','Patchable','Reason / next action','RA game ID','Recommended release','Region','Patch URL','GameDB identity','RA candidates to review','Disc classification','Collection decision','RA set status','RA no-set game ID','Identity evidence','Resolution detail','Patch status','Patch type','Patch warning','Internal disc ID','Disc ID source','ID conflict']
SIZE_COLUMNS = ['File size (bytes)', 'File size (GiB)', 'Alternative region', 'Best-case keep']
SHA_COLUMNS = ['SHA-256 (image)', 'SHA-256 file', 'SHA-256 status']

def sha_fields(record):
    return [record.get('sha256', ''), record.get('sha256_target', ''), record.get('sha256_status', 'NOT_CHECKED')]

GIB = 1024 ** 3

def get_disc_size(row, root=Path('/mnt/retrodb-retronas')):
    """Use the indexed size for PS2; resolve PS1 CUE payloads to avoid a tiny CUE-only size."""
    try:
        known = int(row.get('size_bytes') or 0)
    except (TypeError, ValueError):
        known = 0
    if row.get('platform') != 'Sony PlayStation':
        return known if known > 0 else None
    # The backend audits as the retrodb service user and can read BIN metadata
    # even when the interactive exporter cannot access the mounted CUE files.
    try:
        payload = int(row.get('payload_size_bytes') or 0)
    except (TypeError, ValueError):
        payload = 0
    if payload > 0:
        return payload
    cue = root / str(row.get('path') or '')
    if cue.suffix.lower() != '.cue' or not cue.is_file() or cue.is_symlink():
        return None
    try:
        contents = cue.read_text(encoding='utf-8-sig', errors='replace')
        names = re.findall(r'^\\s*FILE\\s+(?:"([^"]+)"|(\\S+))\\s+\\w+', contents, re.I | re.M)
        candidates = set()
        for quoted, unquoted in names:
            name = quoted or unquoted
            if not name or '/' in name or '\\\\' in name or name in ('.','..'):
                return None
            image = cue.parent / name
            if image.is_symlink() or not image.is_file():
                return None
            candidates.add(image)
        return sum(f.stat().st_size for f in candidates) if candidates else None
    except OSError:
        return None

def alternative_region(row):
    """Only label a genuine region change; an alternative revision is distinct."""
    current = str(row.get('local_region') or '').casefold().strip()
    proposed = str(row.get('preferred_region') or '').casefold().strip()
    return 'YES' if current and proposed and current != proposed and row.get('recommended_ra_title') else 'NO'

def best_case_keep(result_row, alt_region):
    """Keep current RA-compatible images and those without a known region alternative."""
    return 'NO' if str(result_row[13]).startswith('EXCLUDE') or alt_region == 'YES' else 'YES'

def append_size_and_selection(result, source, root=Path('/mnt/retrodb-retronas')):
    size = get_disc_size(source, root)
    alt = alternative_region(source)
    return result + ([size, round(size / GIB, 6)] if size is not None else ['', '']) + [alt, best_case_keep(result, alt)]

VERIFIED = 'clean-base-verified-ready-to-patch'
def patch_sources(path):
    """Index precisely checksum-verified patchable collection sources by RA ID."""
    if not path or not Path(path).is_file(): return {}
    with open(path,encoding='utf-8') as handle: records=json.load(handle)
    return {
        (str(row.get('collection_source','')), str(row.get('ra_game_id',''))): row
        for row in records
        if row.get('state') == VERIFIED and row.get('candidate_path') == row.get('collection_source')
        and row.get('candidate_path') and row.get('ra_game_id')
    }

def patched_outputs(path):
    """Only report VERIFIED when the saved patched output still exists."""
    if not path or not Path(path).is_file():
        return set()
    try:
        with open(path, encoding='utf-8') as handle:
            records = json.load(handle)
        return {(str(row.get('ra_game_id', '')), str(row.get('title', '')))
                for row in records if row.get('status') == 'patched-and-verified'
                and row.get('ra_hash') and row.get('output')
                and Path(row['output']).is_file()}
    except (OSError, ValueError, TypeError):
        return set()


def patch_kind(r):
    label = (r.get('preferred_release_name') or '').casefold()
    if 'anti-cheat' in label or 'anti cheat' in label:
        return 'Anti-cheat'
    if 'debug patch' in label:
        return 'Debug restriction (verify instructions)'
    if 'region conversion' in label:
        return 'Region conversion (verify instructions)'
    return 'Other / review patch notes'


def row_for(r, verified_sources=frozenset(), root='/mnt/retrodb-retronas', verified_outputs=frozenset()):
    yes = r['status'] == 'matched' and r.get('ra_set_status', 'HAS_SET') == 'HAS_SET'
    title = r.get('ra_game_title') or r.get('recommended_ra_title') or r.get('gamedb_title') or r.get('local_friendly_title') or Path(r['path']).stem
    # Preserve independently evidenced disc numbering in the displayed title.
    # The RA catalogue often uses one title for every disc of a game.
    file_stem = Path(r['path']).stem
    disc_label = re.search(r"\b(?:disc|disk|cd)\s*[-_ ]*(\d+)\b", file_stem, re.I)
    if disc_label and not re.search(r"\b(?:disc|disk|cd)\s*[-_ ]*\d+\b", title, re.I):
        title += " (Disc " + str(int(disc_label.group(1))) + ")"
    source = str(Path(root) / r['path'])
    verified_variant = verified_sources.get((source, str(r.get('recommended_ra_game_id', '')))) if isinstance(verified_sources, dict) else None
    patch = (verified_variant or {}).get('patch_url') or r['preferred_patch_url']
    release = (verified_variant or {}).get('required_release') or r['preferred_release_name']
    suggested = bool(r['recommended_ra_title'])
    patchable = bool(not yes and suggested and verified_variant and patch)
    verified_output = (str(r.get('recommended_ra_game_id', '')), r.get('recommended_ra_title', '')) in verified_outputs
    mismatch = (bool(r.get('local_region')) and bool(r.get('preferred_region'))
                and r['local_region'].casefold() != r['preferred_region'].casefold())
    warning = ('LOCAL REGION MISMATCH: ' + r['local_region'] + ' disc; patch targets '
               + r['preferred_region'] + '. No region conversion is implied.' if mismatch and patch else '')
    patch_state = ('VERIFIED' if verified_output else 'READY' if patchable else
                   'AVAILABLE' if patch else 'NONE')
    patch_status = 'YES' if patchable else 'NO'
    if (r.get("platform") == "Sony PlayStation"
            and r.get("status") == "unmatched"
            and r.get("local_serial") in {"SCUS-94480", "SLUS-90021"}):
        status, reason = ("OTHER SOFTWARE",
                          "Promotional/demo software; do not infer retail-game "
                          "achievement compatibility from the title.")
    elif (r.get('platform') == 'Sony PlayStation' and
            '240ptest' in Path(r['path']).stem.casefold().replace(' ', '').replace('-', '').replace('_', '')):
        status, reason = 'OTHER SOFTWARE', 'Homebrew video calibration utility; achievements are not expected and no RA action is required'
    elif yes: status, reason = 'YES', 'Verified RA hash; ready to play'
    elif patchable: status, reason = 'NO', 'READY: exact local source checksum verified; apply patch to a separate copy, then verify output RA hash'
    elif (r.get('platform') == 'Sony PlayStation'
          and r.get('local_serial') == 'SCES-01000'
          and 'kula world' in Path(r['path']).stem.casefold()):
        status = 'NO'
        reason = ('Kula World (Europe) is not matched to the RA set; '
                  'use Roll Away (USA), SLUS-00724, supported hash '
                  'ec12ea42d913aa5a9d4f2b42ad5d28ec. '
                  'RA: https://retroachievements.org/game/14865')
    elif r['status'] == 'failed': status, reason = 'ERROR', r['error'] or 'Disc hashing failed'
    elif suggested:
        status = 'NO'
        if r.get('recommendation_confidence') == 'supported-alternative-edition':
            reason = 'Different edition required for RA: use the recommended supported release; current ISO is not verified'
        elif r.get('recommendation_confidence') == 'verified-serial-alias':
            reason = 'Game identified via verified disc serial; current ISO hash not RA supported'
        elif patch: reason = 'AVAILABLE ONLY: official patch exists, but required clean source is not checksum-verified; do not apply to this ISO'
        elif r['local_region'] and r['preferred_region'] and r['local_region'] != r['preferred_region']:
            reason = 'Different region recommended: ' + r['preferred_region']
        else: reason = 'Different ISO release or revision recommended'
        if r['release_guidance']: reason += ' — ' + r['release_guidance']
    elif (r.get('platform') == 'Sony PlayStation'
          and r.get('local_serial') == 'SLES-00097'
          and r.get('status') == 'unmatched'):
        status = 'NO SET'
        reason = ('Exhumed (Europe) is PowerSlave on RetroAchievements (game 15920). '
                  'No PS1 achievements exist yet; PowerSlave (USA) is an optional '
                  'US-region replacement, NOT an RA-compatible upgrade. '
                  'https://retroachievements.org/game/15920')
    elif r.get('ra_set_status') == 'NOT_LISTED':
        status, reason = 'NO SET', 'User-reviewed: no RetroAchievements game listing found (recheck if catalogue changes)'
    elif r.get('ra_set_status') == 'NO_SET':
        status, reason = 'NO SET', 'RetroAchievements lists this game but has no achievement set'
    elif r.get('disc_classification') == 'special-disc-review':
        status, reason = 'UNKNOWN', 'Promotional/demo or hack compilation: do not assume retail RA compatibility'
    elif r['alternative_candidates']: status, reason = 'UNKNOWN', 'Potential RA titles found; review candidates manually (not verified)'
    elif r.get('gamedb_title'): status, reason = 'UNKNOWN', 'GameDB identified disc; RA identity still needs evidence, not an assumed unsupported release'
    else: status, reason = 'UNKNOWN', 'No confident match; possibly unsupported'
    if warning and not yes:
        reason += ' — ' + warning
    if (r.get('platform') == 'Sony PlayStation'
            and r.get('local_serial') == 'SCES-01000'
            and 'kula world' in Path(r['path']).stem.casefold()):
        title = 'Kula World'
        release = 'Roll Away (USA) [SLUS-00724]'
    if (r.get('platform') == 'Sony PlayStation'
            and r.get('local_serial') == 'SLES-00097'
            and r.get('status') == 'unmatched'):
        title = 'Exhumed / PowerSlave'
        release = 'PowerSlave (USA) — optional; no PS1 achievement set'
    if r.get('platform') == 'Sony PlayStation' and r.get('local_serial') == 'SLES-00097' and r.get('status') == 'unmatched':
        r = {**r, 'no_set_ra_game_id': 15920, 'ra_set_status': 'NO_SET', 'identity_resolution': 'reviewed-disc-id-no-set'}
    # Reviewed PS1 identities must survive older raw CSV exports and sparse
    # RA catalogue snapshots. Do not imply that an unmatched hash is verified.
    reviewed = {
        "SLES-02017": (18622, "4x4 World Trophy / Test Drive: Off-Road 3"),
        "SCES-00245": (8746, "Motor Toon Grand Prix 2"),
        "SLES-00314": (13442, "Monster Trucks / Thunder Truck Rally"),
        "SLES-04129": (19456, "Dance Europe / Dance:UK"),
        "SLES-11881": (20367, "Capcom Generations (Disc 2) (Chronicles of Arthur)"),
        "SLES-21881": (20367, "Capcom Generations (Disc 3) (The First Generation)"),
        "SLES-31881": (20367, "Capcom Generations (Disc 4) (Blazing Guns)"),
    }
    serial = r.get("local_serial", "")
    if r.get("platform") == "Sony PlayStation" and r.get("status") == "unmatched":
        if serial in reviewed:
            ra_id, title = reviewed[serial]
            status = "NO SET"
            reason = ("Reviewed RA identity; no PS1 achievement set. "
                      "https://retroachievements.org/game/" + str(ra_id))
            r = {**r, "no_set_ra_game_id": ra_id, "ra_set_status": "NO_SET",
                 "identity_resolution": "reviewed-disc-id-no-set"}
        elif serial in {"SLUS-01470", "SLUS-01084", "SLUS-01162", "SLES-01178"}:
            status = "NO SET"
            reason = ("No confirmed RetroAchievements game listing for this PS1 release; "
                      "recheck if catalogue changes")
            r = {**r, "ra_set_status": "NOT_LISTED",
                 "identity_resolution": "manual-no-ra-listing"}
    # Gran Turismo 2 Arcade and Simulation are distinct playable discs even
    # when the RA catalogue shares one game ID. Never recommend one as the
    # substitute for the other.
    if (r.get("platform") == "Sony PlayStation"
            and r.get("local_serial") == "SCUS-94455"
            and r.get("status") == "unmatched"):
        title = "Gran Turismo 2 (Arcade Mode)"
        release = "Gran Turismo 2 (USA) (Arcade Mode) (Rev 1)"
        reason = ("Current Arcade Mode disc has not matched an accepted RA "
                  "hash. Supported Arcade Rev 1 hash: "
                  "fb87d46db9130276f28f804ec0dcd6a1. "
                  "Simulation Rev 2 and patched Combined Disc are separate "
                  "supported variants, not interchangeable replacements.")
    # Reviewed crosswalk fallback also supports previously exported raw audits.
    if r.get("platform") == "Sony PlayStation" and r.get("status") == "unmatched":
        if r.get("local_serial") == "SLES-00054":
            title = "X-Com: Enemy Unknown / X-COM: UFO Defense"
            status = "NO"
            release = "X-COM: UFO Defense — accepted RA hash required"
            reason = ("Reviewed PAL identity for RA game 13493; current image is "
                      "not hash verified. https://retroachievements.org/game/13493")
            r = {**r, "recommended_ra_game_id": 13493,
                 "recommended_ra_title": "X-COM: UFO Defense",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-disc-id"}
        elif r.get("local_serial") == "SLES-03962":
            title = "Pro Racer (Rev 1)"
            status = "NO"
            reason = ("European Pro Racer is Racing (PS1), RA game 17187. "
                      "This copy has not matched an accepted RetroAchievements "
                      "hash. https://retroachievements.org/game/17187")
            r = {**r, "recommended_ra_game_id": 17187,
                 "recommended_ra_title": "Racing",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-regional-title"}
        elif r.get("local_serial") == "SLES-03388":
            title = "Power Diggerz"
            status = "NO"
            reason = ("Power Diggerz is the European release of Power Shovel "
                      "(RA 18046); the current disc hash is not RA verified. "
                      "https://retroachievements.org/game/18046")
            r = {**r, "recommended_ra_game_id": 18046,
                 "recommended_ra_title": "Power Shovel",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-disc-id"}
        elif r.get("local_serial") == "SLUS-01230":
            # The similarly named 1999 original has RA game ID 17195.
            # Championship Motocross 2001 is a distinct sequel.
            title = "Championship Motocross 2001 featuring Ricky Carmichael"
            status = "UNKNOWN"
            reason = ("Championship Motocross 2001 is distinct from the 1999 "
                      "Championship Motocross (RA 17195). Do not cross-map "
                      "the sequel without its own RetroAchievements identity.")
            r = {**r, "ra_set_status": "UNRESOLVED",
                 "identity_resolution": "review-sequel-distinct-from-original"}
        elif r.get("local_serial") == "SLES-01694":
            title = "Max Power Racing"
            status = "NO"
            reason = ("Max Power Racing is the UK release of C3 Racing: Car "
                      "Constructors Championship (RA 17911). This disc is "
                      "not verified by an accepted RA hash. "
                      "https://retroachievements.org/game/17911")
            r = {**r, "recommended_ra_game_id": 17911,
                 "recommended_ra_title": "C3 Racing: Car Constructors Championship",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-disc-id"}
        elif r.get("local_serial") == "SLES-03889":
            title = "Capcom vs. SNK: Millennium Fight 2000 Pro"
            status = "NO"
            release = "Capcom vs. SNK Pro (USA)"
            reason = ("European PS1 release identified as RA game 13918; "
                      "its hash is not supported. The accepted release is "
                      "Capcom vs. SNK Pro (USA), RA hash "
                      "cac39e00b80a31f3fe1498a7df72cd57. "
                      "https://retroachievements.org/game/13918")
            r = {**r, "recommended_ra_game_id": 13918,
                 "recommended_ra_title": "Capcom vs. SNK Pro",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-disc-id"}
        elif r.get("local_serial") == "SLPS-02430":
            title = "Chrono Trigger"
            status = "NO"
            release = "Final Fantasy Chronicles - Chrono Trigger (USA) (Rev 1)"
            reason = ("Japanese PS1 Chrono Trigger is the same title as RA game 11243, "
                      "but this disc hash is not supported. Use the USA Rev 1 "
                      "release (accepted hash c6ba0838de81ae2fc7f797141143105e). "
                      "https://retroachievements.org/game/11243")
            r = {**r, "recommended_ra_game_id": 11243,
                 "recommended_ra_title": "Final Fantasy Chronicles: Chrono Trigger",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "reviewed-disc-id"}
        elif r.get("local_serial") == "SLUS-00865":
            title = "WipEout 3"
            status = "NO"
            release = "WipEout 3: Special Edition (Europe) [SCES-02845]"
            reason = ("Standard US WipEout 3 is a distinct edition; RA 13912 "
                      "supports Special Edition, not this US disc. "
                      "https://retroachievements.org/game/13912")
            r = {**r, "recommended_ra_game_id": 13912,
                 "recommended_ra_title": "WipEout 3: Special Edition",
                 "ra_set_status": "HAS_SET",
                 "identity_resolution": "supported-alternative-edition"}
    # Explicitly triaged PS1 titles: names and conventional disc IDs are
    # established, but no RA game crosswalk is confirmed in our catalogue.
    # Treat as non-actionable, not a broken disc or a proven absent RA set.
    unlisted_ps1 = {
        "SLES-04060",  # All Star Watersports
        "SLUS-01230",  # Championship Motocross 2001, NOT 1999 title
        "SLES-02220",  # Extreme 500
        "SLUS-00225",  # Impact Racing
        "SLUS-01247",  # WarJetz, NOT Thunder Tanks
        "SLUS-00704",  # X Games Pro Boarder
    }
    if (r.get("platform") == "Sony PlayStation"
            and r.get("status") == "unmatched"
            and r.get("local_serial") in unlisted_ps1
            and not r.get("ra_game_id") and not r.get("recommended_ra_game_id")
            and not r.get("no_set_ra_game_id")
            and r.get("gamedb_title")):
        status = "NO SET"
        reason = ("No confirmed RetroAchievements listing for this title in the "
                  "current catalogue. GameDB disc ID and filename recognised; "
                  "no action required. This does not prove RA will never add a set.")
        r = {**r, "ra_set_status": "NOT_LISTED",
             "identity_resolution": "triaged-no-confirmed-ra-crosswalk",
             "alternative_candidates": ""}
    return [title, Path(r['path']).name, r['local_serial'], status, patch_status, reason,
            (14865 if r.get('platform') == 'Sony PlayStation' and r.get('local_serial') == 'SCES-01000' and 'kula world' in Path(r['path']).stem.casefold() else (r.get('ra_game_id') or r.get('recommended_ra_game_id') or r.get('no_set_ra_game_id', ''))), release,
            r['local_region'], patch, r.get('gamedb_title', ''), r.get('alternative_candidates', ''), r.get('disc_classification', 'standard'), 'COUNT', r.get('ra_set_status', 'UNRESOLVED'), r.get('no_set_ra_game_id', ''), r.get('identity_resolution', ''), r.get('identity_review_reason', ''), patch_state, patch_kind(r) if patch else '', warning, r.get('internal_disc_serial', ''), r.get('disc_id_source', 'unidentified'), r.get('disc_id_conflict', 'NO')]
def _disc_variant(row):
    """Identify distinct content within an RA game without conflating regions.

    An RA ID may cover multiple discs or independent modes. Missing labels are
    deliberately ambiguous whenever the collection has labelled variants.
    """
    import re
    text = " ".join(str(row[i] or "") for i in (0, 1, 10))
    mode = re.search(r"\b(arcade|simulation)(?:\s+mode)?\b", text, re.I)
    disc = re.search(r"\b(?:disc|disk|cd)\s*[-_ ]*(\d+)\b", text, re.I)
    if mode:
        return "mode:" + mode.group(1).lower()
    if disc:
        return "disc:" + str(int(disc.group(1)))
    return ""


def apply_collection_dedup(entries):
    """Soft-hide incompatible alternative releases covered by a verified image.

    Same-serial copies are equivalent; different-region serials can also
    represent the same game, but only if disc/mode identity is unambiguous.
    The NO hash status remains visible; no file changes occur.
    """
    groups = {}
    for row in entries:
        game_id = str(row[6] or "").strip()
        if game_id:
            groups.setdefault(game_id, []).append(row)
    for group in groups.values():
        verified = [r for r in group if r[3] == "YES"]
        if not verified:
            continue
        variants = {_disc_variant(r) for r in group if _disc_variant(r)}
        verified_serials = {str(r[2] or "").upper() for r in verified}
        for row in group:
            if row[3] == "YES":
                row[13] = "COUNT — verified"
                continue
            if row[3] != "NO" or (len(row) > 23 and str(row[23] or "").upper() == "YES"):
                continue
            serial = str(row[2] or "").upper()
            internal = str(row[21] or "").upper() if len(row) > 21 else ""
            if not serial or (internal and internal != serial):
                continue
            variant = _disc_variant(row)
            # Ace Combat 3's US release is a separate, shortened edition.
            # Only suppress its Japanese recommendation if BOTH Japanese
            # discs have independently passed the RA hash audit. A single
            # Japanese disc cannot cover this two-disc recommendation.
            complete_ace3_japan = (
                str(row[6]).strip() == "11308"
                and serial == "SLUS-00972"
                and {
                    ("SLPS-02020", "disc:1"),
                    ("SLPS-02021", "disc:2"),
                }.issubset({
                    (str(v[2] or "").upper(), _disc_variant(v))
                    for v in verified
                })
            )
            if complete_ace3_japan:
                covered = True
            elif serial in verified_serials:
                covered = True
            elif variant:
                covered = any(_disc_variant(v) == variant for v in verified)
            else:
                # A bare title only represents one game when no distinct
                # disc/mode identities are known and the verified collection
                # has only one serial.
                covered = not variants and len(verified_serials) == 1
            if covered:
                row[13] = "EXCLUDE — verified alternative on share"
                row[5] = ("Unmatched region/revision; verified RA-compatible "
                          "equivalent already present in this collection")
    return entries


ACTION_COLS = [
    'Platform', 'Game name', 'File name', 'Disc ID', 'Status', 'Action',
    'Recommended release', 'Recommended region', 'RA game ID',
    'Existing RA-compatible copy', 'Reason / evidence', 'RA candidates',
    'Local RA hash', 'Accepted RA hashes', 'File path',
]


def action_rows(entries, platform):
    """Actionable entries only; retain evidence and avoid redundant work."""
    rows = []
    verified_by_id = {}
    for r in entries:
        if r[3] == 'YES' and str(r[6]).strip():
            verified_by_id.setdefault(str(r[6]).strip(), []).append(r[1])
    for r in entries:
        if r[3] in ('YES', 'NO SET', 'OTHER SOFTWARE') or str(r[13]).startswith('EXCLUDE'):
            continue
        if r[3] == 'ERROR':
            action = 'Fix disc hash error'
        elif r[4] == 'YES':
            action = 'Apply verified patch; check new RA hash'
        elif r[3] == 'UNKNOWN' and str(r[6]).strip() not in verified_by_id:
            action = 'Investigate RA identity or listing'
        else:
            # A mismatched region/revision is compatibility information, not
            # an action to obtain or delete an image. Keep it on the platform
            # sheet, even where a verified copy of the game also exists.
            continue
        matched_copy = ' | '.join(verified_by_id.get(str(r[6]).strip(), []))
        rows.append([
            platform, r[0], r[1], r[2], r[3], action,
            r[7], r[8], r[6], matched_copy, r[5], r[11],
            '', '', '',  # populated from the original audit rows below
        ])
    return rows


def action_rows_from_audit(raw_entries, platform, displayed):
    """Join readable Excel decisions to underlying hashes and full paths."""
    by_filename = {}
    for raw in raw_entries:
        if raw.get('platform') == platform:
            by_filename.setdefault((raw.get('local_serial'), Path(raw.get('path', '')).name), []).append(raw)
    actions = action_rows(displayed, platform)
    for row in actions:
        candidates = by_filename.get((row[3], row[2]), [])
        if len(candidates) == 1:
            raw = candidates[0]
            row[12] = raw.get('local_ra_hash', '')
            row[13] = raw.get('accepted_ra_hashes', '')
            row[14] = raw.get('path', '')
    return actions


def excel_column(index):
    result = ''
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result

def xml_sheet(rows):
    """Write an Excel filterable table, real numeric sizes, and a filter-aware footer."""
    headers = rows[0]
    has_sizes = 'File size (bytes)' in headers and 'File size (GiB)' in headers
    bytes_col = headers.index('File size (bytes)') if has_sizes else -1
    gib_col = headers.index('File size (GiB)') if has_sizes else -1
    last_data = len(rows)
    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
           '<cols>']
    widths = ([28,16,18,18,18,20,18,18,18,18,20,22,24,19,24,20,18,18,18]
              if len(headers) == 19 else
              [38,54,18,17,16,75,17,44,16,55,44,70,24,38,20,20,28,64,18,32,65])
    widths = (widths + [20] * max(0, len(headers) - len(widths)))[:len(headers)]
    if has_sizes:
        widths[bytes_col] = 21
        widths[gib_col] = 21
    for i, width in enumerate(widths, 1):
        xml.append('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i,i,width))
    xml.append('</cols><sheetData>')
    for n, row in enumerate(rows, 1):
        xml.append('<row r="%d">' % n)
        for i, val in enumerate(row):
            style = 1 if n == 1 else (2 if n%2 == 0 else 0)
            if n > 1 and has_sizes and i == gib_col:
                style = 7
            if n > 1 and i == 3 and headers[:4] == COLS[:4]:
                style = {'YES':3,'NO':4,'UNKNOWN':5,'ERROR':6,'NO SET':5}.get(val,style)
            if n > 1 and len(row) == 16 and i == 4 and val == 'YES':
                style = 3
            cell = '%s%d' % (excel_column(i+1),n)
            if n > 1 and has_sizes and i in (bytes_col,gib_col) and type(val) in (int,float):
                xml.append('<c r="%s" s="%d"><v>%s</v></c>' % (cell,style,val))
            else:
                xml.append('<c r="%s" s="%d" t="inlineStr"><is><t>%s</t></is></c>' %
                           (cell,style,escape(str(val if val is not None else ''))))
        xml.append('</row>')
    if has_sizes:
        footer = last_data + 1
        bcol, gcol = excel_column(bytes_col+1), excel_column(gib_col+1)
        xml.append('<row r="%d">' % footer)
        xml.append('<c r="A%d" s="1" t="inlineStr"><is><t>Visible total (filtered)</t></is></c>' % footer)
        xml.append('<c r="B%d"><f>SUBTOTAL(103,A2:A%d)</f><v>0</v></c>' % (footer,last_data))
        xml.append('<c r="%s%d"><f>SUBTOTAL(109,%s2:%s%d)</f><v>0</v></c>' %
                   (bcol,footer,bcol,bcol,last_data))
        xml.append('<c r="%s%d" s="7"><f>SUBTOTAL(109,%s2:%s%d)/1073741824</f><v>0</v></c>' %
                   (gcol,footer,bcol,bcol,last_data))
        xml.append('</row>')
    xml.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' %
               (excel_column(len(headers)),last_data))
    return ''.join(xml)

def load_ps1_audit(path):
    if not path or not Path(path).is_file():
        return []
    with open(path, newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def ps1_action_row(r):
    status = r.get('status', '')
    issue = r.get('issues', '')
    action = ('Repair broken CUE / references' if status == 'BROKEN' else
              'Review disc identity and source files' if status == 'REVIEW' else
              'Review BIN/CUE naming warning' if status == 'WARNING' else
              'Review paired BIN/CUE rename')
    source = r.get('relative_cue') or r.get('relative_bin', '')
    return ['Sony PlayStation', Path(source).stem, Path(source).name,
            r.get('internal_serial') or r.get('filename_serial', ''), status, action,
            '', '', '', '', issue, '', '', '',
            source]


def main(source,destination,preparation=None,ps1_audit=None,ps3_audit=None,psp_audit=None):
    with open(source,newline='',encoding='utf-8-sig') as handle: entries=list(csv.DictReader(handle))
    backups = [r for r in entries if Path(r.get('path', '')).name.casefold().startswith('old_')]
    entries = [r for r in entries if not Path(r.get('path', '')).name.casefold().startswith('old_')]
    if backups: print(f'[INFO] Excluded {len(backups)} OLD_ backup images from compatibility workbook.')
    assert entries and 'preferred_patch_url' in entries[0], 'Invalid RetroDB audit CSV'
    sources = patch_sources(preparation)
    outputs = patched_outputs(str(Path(preparation).with_name('patch-apply.json')) if preparation else None)
    sheets=[]
    online_catalogue = load_online(str(Path.home() / '.cache/retrodb/online-compatibility.json'))
    xlink_catalogue = load_xlink(str(Path.home() / '.cache/retrodb/xlink-ps2.json'))
    ps2_online = [enrich_with_xlink(online_report_row(r, online_catalogue), xlink_catalogue) for r in entries if r.get('platform') == 'Sony PlayStation 2']
    ps2_online.sort(key=lambda row: (str(row[0]).casefold(), str(row[2])))
    all_actions=[]
    summary=[['Console','Disc images','Effective images','Excluded duplicates','RA-ready %','Eligible RA-ready %','RA eligible images','RA compatible','Patchable','Alternative ISO','No achievement set','Unresolved','GameDB identified unresolved','RA candidates to review','Hash errors','Patchable %','No-set %','Unresolved %','RA identified %']]
    for platform,name in [('Sony PlayStation','PlayStation 1'),('Sony PlayStation 2','PlayStation 2')]:
        paired_rows=sorted(((row_for(r, sources, verified_outputs=outputs), r)
                            for r in entries if r['platform']==platform),
                           key=lambda pair:(pair[0][0].casefold(),pair[0][1].casefold()))
        entries_console=[row for row, _ in paired_rows]
        row_sources={id(row): source for row, source in paired_rows}
        apply_collection_dedup(entries_console)
        for r in entries_console:
            if r[3] == 'OTHER SOFTWARE':
                r[13] = 'EXCLUDE — other software'
        active=[r for r in entries_console if not r[13].startswith('EXCLUDE')]
        excluded=len(entries_console)-len(active)
        counts=Counter(r[3] for r in active)
        patched=sum(r[4]=='YES' for r in active)
        identified_unknown=sum(r[3]=='UNKNOWN' and bool(r[10]) for r in active)
        review_count=sum(r[3]=='UNKNOWN' and bool(r[11]) for r in active)
        effective=len(active)
        percent=f'{100*counts["YES"]/effective:.2f}%' if effective else '0.00%'
        eligible=effective-counts['NO SET']
        eligible_percent=f'{100*counts["YES"]/eligible:.2f}%' if eligible else 'N/A'
        summary.append([name,len(entries_console),effective,excluded,percent,eligible_percent,eligible,counts['YES'],patched,counts['NO']-patched,counts['NO SET'],counts['UNKNOWN'],identified_unknown,review_count,counts['ERROR'],
                        f'{100*patched/effective:.2f}%' if effective else '0.00%',
                        f'{100*counts["NO SET"]/effective:.2f}%' if effective else '0.00%',
                        f'{100*counts["UNKNOWN"]/effective:.2f}%' if effective else '0.00%',
                        f'{100*(counts["YES"]+counts["NO"]+counts["NO SET"])/effective:.2f}%' if effective else '0.00%'])
        # Pair each row to its original exact library path, including duplicate filenames.
        # Append only after de-duplication; existing report logic uses fixed indices.
        entries_console = [append_size_and_selection(row, row_sources[id(row)]) +
                           sha_fields(row_sources[id(row)]) for row in entries_console]
        sheets.append((name,[COLS + SIZE_COLUMNS + SHA_COLUMNS]+entries_console))
        all_actions.extend(action_rows_from_audit(entries, platform, active))
    ps1_rows = load_ps1_audit(ps1_audit)
    if ps1_rows:
        ps1_cols = ['Status', 'CUE path', 'BIN path', 'Filename disc ID',
                    'Internal disc ID', 'Selected disc ID', 'Homebrew',
                    'CUE file references', 'Referenced file count',
                    'Proposed CUE', 'Proposed BIN', 'RA verification', 'Issues']
        ps1_keys = ['status', 'relative_cue', 'relative_bin', 'filename_serial',
                    'internal_serial', 'selected_serial', 'homebrew',
                    'file_references', 'file_count', 'proposed_cue', 'proposed_bin',
                    'ra_compatibility', 'issues']
        # CUE is the RA entry point. Join using the original relative path,
        # never a proposed destination or a guessed title.
        ra_by_path = {}
        for entry in entries:
            if entry.get('platform') != 'Sony PlayStation':
                continue
            path = (entry.get('path') or '').replace('\\\\', '/')
            key = path.casefold()
            if key and (key.endswith('.cue') or key.endswith('.chd')):
                ra_by_path[key] = entry
        ps1_extra = ['RA compatible', 'RA game ID', 'RA game title', 'RA hash', 'RA match status']
        ps1_rows_out = []
        for r in ps1_rows:
            cue = r.get('relative_cue', '').replace('\\\\', '/')
            matches = [entry for key, entry in ra_by_path.items()
                       if cue and (key.endswith('/' + cue.casefold())
                                   or key == cue.casefold())]
            match = matches[0] if len(matches) == 1 else {}
            raw_status = str(match.get('status', '')).lower()
            ra_status = ('YES' if raw_status == 'matched' else
                         'NO' if raw_status == 'unmatched' else
                         'ERROR' if raw_status in ('error', 'failed') else
                         'NOT_CHECKED' if not match else
                         raw_status.upper())
            columns = [ra_status, match.get('ra_game_id', ''),
                       match.get('ra_game_title', ''),
                       match.get('local_ra_hash', ''), match.get('status', '')]
            ps1_rows_out.append([r.get(k, '') for k in ps1_keys] + columns)
        sheets.append(('PS1 File Audit', [ps1_cols + ps1_extra] + ps1_rows_out))
        # Rename suggestions belong on the file audit, not the urgent Action sheet.
        # Deduplicate orphan BIN + broken CUE cases when both refer to same disc.
        for r in ps1_rows:
            if r.get('status') not in ('BROKEN', 'REVIEW', 'WARNING'):
                continue
            all_actions.append(ps1_action_row(r))
        print(f'[INFO] PS1 file audit: {len(ps1_rows)} disc/file records integrated.')
    if ps3_audit and Path(ps3_audit).is_file():
        with open(ps3_audit, newline='', encoding='utf-8-sig') as handle:
            ps3_records = list(csv.DictReader(handle))
        columns = ['Type', 'Status', 'Disc ID', 'GameDB title', 'Existing file / folder',
                   'Proposed name', 'Associated sidecars', 'Reason / next action',
                   'RA compatibility']
        ps3_rows = []
        for record in ps3_records:
            location = record.get('existing_iso', '')
            kind = 'Extracted folder' if record.get('status', '').startswith('EXTRACTED_') else 'ISO'
            ps3_rows.append([kind, record.get('status', ''),
                record.get('disc_id', '') or 'UNKNOWN',
                record.get('catalogue_title', ''),
                location, record.get('proposed_iso', ''),
                record.get('sidecars', ''), record.get('reason', ''),
                'NOT CHECKED — naming inventory only'] + sha_fields(record))
        sheets.append(('PlayStation 3', [columns + SHA_COLUMNS] + ps3_rows))
        print(f'[INFO] PS3 inventory: {len(ps3_rows)} ISO/folder records integrated.')
    if psp_audit and Path(psp_audit).is_file():
        with open(psp_audit, newline='', encoding='utf-8-sig') as handle:
            psp_records = list(csv.DictReader(handle))
        # Keep the same first 24 headings/order as PS1 and PS2.
        # Unavailable patch fields are blank or N/A, never implied to be supported.
        def psp_region(disc):
            prefix = str(disc).upper()[:4]
            if prefix in ('ULUS', 'UCUS', 'NPUH', 'NPUG'): return 'USA'
            if prefix in ('ULES', 'UCES', 'NPEH', 'NPEG'): return 'Europe'
            if prefix in ('ULJS', 'ULJM', 'UCJS', 'UCJM', 'NPJH', 'NPJQ'): return 'Japan'
            return 'Unknown'
        psp_rows = []
        psp_counts = Counter()
        for r in psp_records:
            status = r.get('ra_status', 'NOT_CHECKED')
            psp_counts[status] += 1
            supported = status == 'SUPPORTED'
            compatible = ('YES' if supported else 'NO SET' if status == 'NO_SET'
                          else 'ERROR' if status == 'HASH_ERROR' else 'UNKNOWN')
            game_id = r.get('ra_game_id', '')
            suggested_id = r.get('suggested_ra_game_id', '')
            suggested_release = r.get('suggested_release', '')
            suggested_region = r.get('suggested_region', '')
            suggestion_evidence = r.get('suggestion_evidence', '')
            game_name = r.get('title', '')
            filename = r.get('filename', '')
            disc = r.get('disc_id', '')
            row = [
                game_name, filename, disc, compatible, 'NO',
                (suggestion_evidence if status == 'UNMATCHED' and suggested_id else
                 r.get('reason', '') or ('Verified RetroAchievements hash' if supported
                    else 'RetroAchievements title has no achievement set' if status == 'NO_SET'
                    else 'Disc hash not registered on RetroAchievements' if status == 'UNMATCHED'
                    else 'Not checked')),
                game_id if supported else '', suggested_release, psp_region(disc), '',
                game_name if r.get('identity_source') == 'PARAM.SFO/GameDB' else '',
                (suggested_release if status == 'UNMATCHED' else ''),
                'standard', 'COUNT — verified' if supported else 'COUNT — no set' if status == 'NO_SET' else 'REVIEW — hash unregistered',
                'HAS_SET' if supported else
                'NO_SET' if status == 'NO_SET' else 'UNKNOWN',
                game_id if status == 'NO_SET' else '',
                r.get('identity_source', ''), (suggestion_evidence or r.get('reason', '')), 'NONE',
                '', '', r.get('internal_disc_id', ''),
                'PARAM.SFO' if r.get('internal_disc_id') else 'Filename',
                'YES' if r.get('filename_disc_id') and r.get('internal_disc_id')
                    and r['filename_disc_id'] != r['internal_disc_id'] else 'NO',
                r.get('status', ''), r.get('ra_hash', ''),
                r.get('ra_game_title', ''), r.get('internal_title', ''),
                r.get('filename_disc_id', ''), r.get('relative_path', ''),
                suggested_id, suggested_region, suggestion_evidence,
                r.get('suggested_ra_hash', '')
            ]
            try:
                psp_size = int(r.get('size_bytes') or 0)
            except (TypeError, ValueError):
                psp_size = 0
            alt = 'YES' if suggested_region and suggested_region.casefold() != psp_region(disc).casefold() else 'NO'
            row.extend([psp_size if psp_size > 0 else '',
                        round(psp_size / GIB, 6) if psp_size > 0 else '',
                        alt, 'NO' if alt == 'YES' else 'YES'])
            psp_rows.append(row + sha_fields(r))
        psp_rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold()))
        psp_extra = ['Identity verification', 'RA disc hash', 'RA game title',
                     'Internal PSP title', 'Filename disc ID', 'Relative path',
                     'Suggested RA game ID', 'Suggested region', 'Suggestion evidence',
                     'Suggested RA hash']
        sheets.append(('PlayStation Portable', [COLS + psp_extra + SIZE_COLUMNS + SHA_COLUMNS] + psp_rows))
        effective=len(psp_records)
        compatible=psp_counts['SUPPORTED']
        no_set=psp_counts['NO_SET']
        unresolved=psp_counts['UNMATCHED'] + psp_counts['NOT_CHECKED']
        hash_errors=psp_counts['HASH_ERROR']
        eligible=effective-no_set
        summary.append(['PlayStation Portable',effective,effective,0,
                        f'{100*compatible/effective:.2f}%' if effective else '0.00%',
                        f'{100*compatible/eligible:.2f}%' if eligible else 'N/A',
                        eligible,compatible,0,0,no_set,unresolved,0,0,hash_errors,
                        '0.00%',
                        f'{100*no_set/effective:.2f}%' if effective else '0.00%',
                        f'{100*unresolved/effective:.2f}%' if effective else '0.00%',
                        f'{100*(compatible+no_set)/effective:.2f}%' if effective else '0.00%'])
        print(f'[INFO] PSP ISO inventory: {len(psp_records)} files integrated (PSP RA hash verification included).')
    priority = {'Fix disc hash error': 0, 'Apply verified patch; check new RA hash': 1,
                'Obtain supported region / edition / revision': 2, 'Investigate RA identity or listing': 3}
    all_actions.sort(key=lambda row: (priority.get(row[5], 9), row[0], row[1].casefold()))
    print(f'[INFO] Action Required (all platforms): {len(all_actions)} games need attention.')
    sheets.insert(0, ('Action Required', [ACTION_COLS] + all_actions))
    sheets.append(('PS2 Online', [ONLINE_COLUMNS] + ps2_online))
    known = [row for row in ps2_online if row[4] == 'YES']
    online_summary = [
        ['Metric', 'Count', 'Meaning'],
        ['PS2 local disc images', len(ps2_online), 'Every PS2 image from the audit'],
        ['Historical online documented', len(known), 'Exact regional disc ID found in imported community data'],
        ['XLink Kai reported supported', sum(str(row[7]).startswith('YES') for row in ps2_online), 'Community or official XLink title-level evidence; region not verified'],
        ['Community XLink YES', sum(row[21] == 'YES' for row in ps2_online), 'Source-specific release record; not independently tested'],
        ['XLink catalogue title matches', sum(row[22] == 'YES (title-level)' for row in ps2_online), 'Includes partial source snapshot; regional versions not individually tested'],
        ['Conflicting XLink evidence', sum(bool(row[23]) for row in ps2_online), 'Community source says NO while XLink title catalogue lists the game'],
        ['Community DNS reported yes', sum(row[8] == 'YES' for row in known), 'Not proof that the server is currently online'],
        ['Native LAN unknown', sum(row[6] == 'UNKNOWN' for row in ps2_online), 'Native LAN requires separate source evidence'],
        ['No historical-online source record', len(ps2_online)-len(known), 'UNKNOWN does not mean NO online support'],
        ['XLink title matches without disc-ID online evidence', sum(row[7] == 'YES (title-level)' and row[4] != 'YES' for row in ps2_online), 'LAN play documented at title level; edition must be checked'],
    ]
    online_summary += [['', '', ''], ['Game', 'Disc ID', 'Connection details (community reported)']]
    online_summary += [[row[0], row[2], f'Original: {row[5] or "unknown"}; XLink: {row[7]}; DNS: {row[8]}; {row[9]}'] for row in known]
    sheets.append(('Online Summary', online_summary))
    print(f'[INFO] PS2 online: {len(ps2_online)} local discs; {sum(row[4] == "YES" for row in ps2_online)} with release-specific source evidence.')
    sheets.insert(0,('Summary',summary))
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+''.join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'%i for i in range(1,len(sheets)+1))+'</Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>'%(name,i,i) for i,(name,_) in enumerate(sheets,1))+'</sheets><calcPr calcId="0" calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'%(i,i) for i in range(1,len(sheets)+1))+'<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml','<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/></font><font><b/><color rgb="FFFFFFFF"/></font></fonts><fills count="7"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'+''.join('<fill><patternFill patternType="solid"><fgColor rgb="%s"/></patternFill></fill>'%c for c in ('FF17365D','FFF1F5F9','FFDDF4E4','FFFFE5CC','FFFDF1C8'))+'</fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="8">'+''.join('<xf numFmtId="0" fontId="%d" fillId="%d" borderId="0" xfId="0"/>'%(1 if i==1 else 0, {0:0,1:2,2:3,3:4,4:5,5:6,6:6}[i]) for i in range(7))+'<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>')
        for i,(_,rows) in enumerate(sheets,1): z.writestr('xl/worksheets/sheet%d.xml'%i,xml_sheet(rows))
    print('[OK] Excel audit exported:',destination)
    print(f'[INFO] Action Required: {len(all_actions)} unresolved, unverified or hash-error entries across all platforms.')
    for row in summary[1:]: print('    %s: %s/%s RA-compatible (%s); %s redundant copies excluded from reporting, %s patchable, %s alternative ISOs, %s unknown' % (row[0],row[7],row[2],row[4],row[3],row[8],row[9],row[11]))
if __name__=='__main__':
    if len(sys.argv) not in (3,4,5,6,7): sys.exit('Usage: python3 server/report_excel.py input.csv output.xlsx [patch-prepare.json] [ps1-audit.csv] [ps3-audit.csv] [psp-audit.csv]')
    main(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>=4 and sys.argv[3] != '-' else None, sys.argv[4] if len(sys.argv)>=5 and sys.argv[4] != '-' else None, sys.argv[5] if len(sys.argv)>=6 and sys.argv[5] != '-' else None, sys.argv[6] if len(sys.argv)>=7 and sys.argv[6] != '-' else None)
