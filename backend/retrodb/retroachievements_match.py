"""Hash local disc images and produce an actionable RetroAchievements report."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import csv
import json
from pathlib import Path
import re
import shlex
import subprocess
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from retrodb.models import LibraryItem, Platform
from retrodb.disc_identity import internal_disc_serial
from retrodb.providers.gamedb import load as load_gamedb
from retrodb.providers.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
)

HASH_PATTERN = re.compile(r"\b([0-9a-fA-F]{32})\b")
SERIAL_PATTERN = re.compile(
    r"\b(SCUS|SLUS|SCES|SLES|SCPS|SLPS|SLPM|SCCS|SCKA|SCPM|USGR)[_. -]?(\d{3})[_. -]?(\d{2})\b",
    re.IGNORECASE,
)
HASH_TARGET_EXTENSIONS = {"playstation": {"cue"}, "playstation-2": {"iso"}}
REGION_BY_PREFIX = {
    "SCUS": "USA", "SLUS": "USA",
    "SCES": "Europe", "SLES": "Europe",
    "SCPS": "Japan", "SLPS": "Japan", "SLPM": "Japan",
    "SCCS": "China", "SCKA": "Korea",
    "SCPM": "Japan",
}
REGION_WORDS = (
    "USA", "Europe", "Japan", "World", "Australia", "Asia", "Korea", "China",
    "Germany", "France", "Italy", "Spain", "United Kingdom",
)


class MatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogueGame:
    game_id: int
    title: str
    hashes: tuple[str, ...]


@dataclass(frozen=True)
class MatchSummary:
    platform: str
    candidates: int
    matched: int
    unmatched: int
    failed: int
    cached: int
    recommended: int


def extract_hash(output: str) -> str:
    matches = HASH_PATTERN.findall(output)
    if not matches:
        raise MatchError("Hasher returned no RetroAchievements hash.")
    return matches[-1].casefold()


def load_catalogue(
    cache_path: Path,
) -> tuple[int, dict[str, tuple[int, str]], tuple[CatalogueGame, ...]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MatchError(f"Cannot read cached catalogue: {cache_path}") from exc
    if not isinstance(payload, list) or not payload:
        raise MatchError(f"Cached catalogue is empty: {cache_path}")

    index: dict[str, tuple[int, str]] = {}
    games: list[CatalogueGame] = []
    console_id = 0
    for game in payload:
        if not isinstance(game, dict):
            continue
        try:
            game_id = int(game["ID"])
            title = str(game["Title"]).strip()
            console_id = console_id or int(game["ConsoleID"])
        except (KeyError, TypeError, ValueError):
            continue
        hashes = tuple(
            value.casefold()
            for value in game.get("Hashes", [])
            if isinstance(value, str) and HASH_PATTERN.fullmatch(value)
        )
        games.append(CatalogueGame(game_id, title, hashes))
        for value in hashes:
            index[value] = (game_id, title)
    if not console_id or not index:
        raise MatchError(f"Cached catalogue contains no usable hashes: {cache_path}")
    return console_id, index, tuple(games)


def load_hash_catalogue(cache_path: Path) -> tuple[int, dict[str, tuple[int, str]]]:
    """Compatibility wrapper retained for callers and tests."""
    console_id, index, _ = load_catalogue(cache_path)
    return console_id, index


def identify_local_release(path: str) -> tuple[str, str]:
    match = SERIAL_PATTERN.search(Path(path).name)
    if not match:
        return "", ""
    serial = f"{match.group(1).upper()}-{match.group(2)}{match.group(3)}"
    return serial, REGION_BY_PREFIX.get(match.group(1).upper(), "")


def load_serial_aliases(path: Path | None = None) -> dict[str, str]:
    """Curated, source-attributed serial aliases; not compatibility assertions."""
    source = path or Path(__file__).with_name("data") / "ps2_serial_aliases.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        serial.upper(): row["title"]
        for serial, row in data.items()
        if isinstance(row, dict) and isinstance(row.get("title"), str)
        and SERIAL_PATTERN.fullmatch(serial)
        and row.get("source")
    }


def suggest_by_serial(
    serial: str, games: tuple[CatalogueGame, ...], aliases: dict[str, str]
) -> tuple[CatalogueGame | None, str, float]:
    """Resolve a *documented* serial only if exactly one RA title matches."""
    title = aliases.get(serial, "")
    if not title:
        return None, "", 0.0
    matches = [game for game in games if comparable_title(game.title) == comparable_title(title)]
    if len(matches) == 1:
        return matches[0], "verified-serial-alias", 1.0
    return None, "serial-alias-no-unique-ra-title", 0.0


def friendly_local_title(path: str) -> str:
    """Show legible filenames without product codes; never infer RA compatibility."""
    name = Path(path).stem
    name = SERIAL_PATTERN.sub(" ", name)
    name = re.sub(r"^[\s._-]+|[\s._-]+$", "", name)
    name = re.sub(r"[._]+", " ", name)
    return re.sub(r"\s+", " ", name).strip() or Path(path).stem


def normalise_title(value: str) -> str:
    title = Path(value).name
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    title = re.sub(r"'s\b", "s", title, flags=re.I)
    title = re.sub(r"\.(?:cue|iso|bin|chd|pbp|md|zip|7z)$", "", title, flags=re.I)
    title = SERIAL_PATTERN.sub(" ", title)
    title = re.sub(r"[\[(](?:disc|disk|cd|dvd)\s*\d+[^\])]?[\])]", " ", title, flags=re.I)
    title = re.sub(r"\b(?:disc|disk|cd|dvd)\s*\d+\b", " ", title, flags=re.I)
    title = re.sub(r"[\[(][^\])]*(?:USA|Europe|Japan|PAL|NTSC|En,|Rev\s)[^\])]*[\])]", " ", title, flags=re.I)
    title = title.replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", title.casefold()))


def release_markers(value: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return sequel/version markers which must agree for a fuzzy match."""
    words = normalise_title(value).split()
    numbers = frozenset(word for word in words if word.isdigit())
    roman_numerals = frozenset(
        word for word in words
        if word in {"ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "xi", "xii"}
    )
    return numbers, roman_numerals


def is_compatible_title_candidate(local_path: str, candidate_title: str) -> bool:
    local_numbers, local_roman = release_markers(local_path)
    candidate_numbers, candidate_roman = release_markers(candidate_title)
    if local_numbers != candidate_numbers or local_roman != candidate_roman:
        return False
    local_words = set(normalise_title(local_path).split())
    candidate_words = set(normalise_title(candidate_title).split())
    special = {"demo", "prototype", "hack", "bonus", "compilation"}
    return (local_words & special) == (candidate_words & special)


ROMAN_NUMBERS = {
    "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "xi": "11", "xii": "12",
}


def comparable_title(value: str) -> str:
    """Canonical title used only for ranking, never to relax release safeguards."""
    ascii_title = unicodedata.normalize("NFKD", normalise_title(value))
    words = ascii_title.encode("ascii", "ignore").decode("ascii").split()
    expanded: list[str] = []
    for word in words:
        match = re.fullmatch(r"v(\d+)", word)
        if match:
            expanded.append(match.group(1))
        elif word in ROMAN_NUMBERS:
            expanded.append(ROMAN_NUMBERS[word])
        elif word.isdigit():
            expanded.append(str(int(word)))
        elif word not in {"a", "an", "the"}:
            expanded.append({"vs": "versus"}.get(word, word))
    comparable = " ".join(expanded)
    comparable = re.sub(r"\bdual shock (?:ver|version)\b", "", comparable)
    aliases = {
        "harry potter and philosophers stone": "harry potter and sorcerers stone",
        "guitar hero rocks 80s": "guitar hero encore rocks 80s",
        "lara croft tomb raider anniversary": "tomb raider anniversary",
        "lara croft tomb raider legend": "tomb raider legend",
        "disneys haunted mansion": "haunted mansion",
    }
    comparable = aliases.get(comparable.strip(), comparable)
    return " ".join(comparable.split())


def title_similarity(left: str, right: str) -> float:
    left_normal = comparable_title(left)
    right_normal = comparable_title(right)
    if not left_normal or not right_normal:
        return 0.0
    direct = SequenceMatcher(None, left_normal, right_normal).ratio()
    token_order = SequenceMatcher(
        None,
        " ".join(sorted(left_normal.split())),
        " ".join(sorted(right_normal.split())),
    ).ratio()
    left_tokens, right_tokens = set(left_normal.split()), set(right_normal.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return max(direct, token_order * 0.98, (direct * 0.75) + (overlap * 0.25))


def rank_game_candidates(
    local_path: str, games: tuple[CatalogueGame, ...]
) -> list[tuple[float, CatalogueGame]]:
    return sorted(
        (
            (title_similarity(local_path, game.title), game)
            for game in games
            if is_compatible_title_candidate(local_path, game.title)
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )


def suggest_game(local_path: str, games: tuple[CatalogueGame, ...]) -> tuple[CatalogueGame | None, str, float]:
    scored = rank_game_candidates(local_path, games)
    if not scored:
        return None, "", 0.0
    best_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if comparable_title(local_path) == comparable_title(best.title):
        return best, "exact-title", 1.0
    if best_score >= 0.88 and best_score - second_score >= 0.05:
        return best, "high", best_score
    return None, "ambiguous" if best_score >= 0.72 else "", best_score


REGIONAL_IDENTITIES = {
    "canis canem edit": "Bully",
    "fahrenheit": "Indigo Prophecy",
    "ratchet gladiator": "Ratchet: Deadlocked",
    "ratchet and clank 3": "Ratchet & Clank: Up Your Arsenal",
    "godfather": "The Godfather: The Game",
    "blood omen 2 legacy of kain series": "Legacy of Kain: Blood Omen 2",
    "king of fighters maximum impact": "KOF: Maximum Impact",
    "king of fighters maximum impact 2": "KOF: Maximum Impact 2",
    "virtua fighter 10th anniversary edition": "Virtua Fighter 10th Anniversary",
}

def review_reason(title: str, candidates: str, special: bool = False) -> str:
    """Explicit non-assertive explanation for unresolved RA identities."""
    if special:
        return "special-disc: independently verify homebrew/demo compilation support"
    source = comparable_title(title)
    if not candidates:
        return "no-RA-title-crosswalk: check RA catalogue and edition metadata"
    # Do not promote title matches across different product editions.
    guarded = ("black edition", "substance", "arena edition")
    if any(word in candidates.casefold() for word in guarded):
        return "different-edition: compare supported hash and release before replacing"
    if "eyetoy" in source and "eyetoy" in candidates.casefold():
        return "different-game: EyeToy titles are not interchangeable"
    return "candidate-review: confirm regional or branded title against RA identity"


def resolve_catalogue_identity(title: str, games: tuple[CatalogueGame, ...]):
    """Reviewed regional identity aliases; no equivalence of editions or hashes."""
    canonical = REGIONAL_IDENTITIES.get(comparable_title(title), title)
    game, method, score, review = game_db_ra_candidates(canonical, games)
    if game and canonical != title:
        method = "curated-regional-title"
    return game, method, score, review


def game_db_ra_candidates(
    title: str, games: tuple[CatalogueGame, ...]
) -> tuple[CatalogueGame | None, str, float, str]:
    """Crosswalk GameDB to RA; suggest only a clear, high-scoring single identity.

    Rejected/uncertain matches are review suggestions, never hash matches.
    """
    if not title:
        return None, "", 0.0, ""
    ranked = rank_game_candidates(title, games)
    ranked = [(score, game) for score, game in ranked if score >= 0.72]
    if not ranked:
        return None, "gamedb-no-ra-candidate", 0.0, ""
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    review = " | ".join(
        f"{game.title} [RA {game.game_id}; {score:.3f}]"
        for score, game in ranked[:3]
    )
    exact = [game for score, game in ranked
             if comparable_title(game.title) == comparable_title(title)]
    if len(exact) == 1:
        return exact[0], "gamedb-exact-title", 1.0, ""
    if len(exact) > 1:
        return None, "gamedb-ambiguous", best_score, review
    # Strict fuzzy threshold, clear margin, and identical sequel/version markers.
    # A fuzzy recommendation still needs an RAHasher-compatible replacement ISO.
    if best_score >= 0.94 and best_score - second_score >= 0.10:
        return best, "gamedb-high-confidence-title", best_score, ""
    return None, "gamedb-review", best_score, review


def alternative_candidates(
    local_path: str, games: tuple[CatalogueGame, ...], limit: int = 3
) -> str:
    candidates = [
        f"{game.title} [RA {game.game_id}; {score:.3f}]"
        for score, game in rank_game_candidates(local_path, games)
        if score >= 0.72
    ]
    return " | ".join(candidates[:limit])


def regions_from_names(names: list[str]) -> str:
    found = []
    for name in names:
        for region in REGION_WORDS:
            if re.search(rf"\b{re.escape(region)}\b", name, re.I) and region not in found:
                found.append(region)
    return "; ".join(found)


def release_region(name: str) -> str:
    for region in REGION_WORDS:
        if re.search(rf"\b{re.escape(region)}\b", name, re.I):
            return region
    return ""


def preferred_release(
    details: list[dict[str, object]],
    game_id: int | None = None,
) -> tuple[str, str, str, str, str]:
    """Choose RA's cleanest preferred TV-console release and final revision."""
    if not details:
        return "", "", "", "", ""

    def sort_key(entry: dict[str, object]) -> tuple[int, int, int, int, str]:
        name = str(entry.get("Name", ""))
        region = release_region(name)
        # Raw Danger! (RA 5616): prefer the supported English-language PAL
        # edition rather than the Japanese release. This is a recommendation
        # preference, never a claim that the local USA ISO matches its hash.
        region_rank = ({"Europe": 0, "USA": 1, "World": 1, "Japan": 2}
                       if game_id == 5616 else
                       {"USA": 0, "World": 0, "Japan": 1, "Europe": 2}).get(region, 3)
        labels = {
            str(label).casefold()
            for label in entry.get("Labels", [])
            if isinstance(label, str)
        }
        patch_rank = int(bool(entry.get("PatchUrl")) or bool(
            labels & {"rapatches", "hack", "translation"}
        ))
        preservation_rank = 0 if labels & {"redump", "nointro", "no-intro"} else 1
        revision = 0
        revision_match = re.search(r"\bRev(?:ision)?\s*([0-9]+)\b", name, re.I)
        if revision_match:
            revision = int(revision_match.group(1))
        version_match = re.search(r"\bv(\d+)(?:\.(\d+))?\b", name, re.I)
        if version_match:
            revision = max(
                revision,
                int(version_match.group(1)) * 100 + int(version_match.group(2) or 0),
            )
        return patch_rank, region_rank, preservation_rank, -revision, name.casefold()

    chosen = min(details, key=sort_key)
    labels = "; ".join(
        sorted(
            str(label)
            for label in chosen.get("Labels", [])
            if isinstance(label, str)
        )
    )
    return (
        str(chosen.get("Name", "")).strip(),
        release_region(str(chosen.get("Name", ""))),
        str(chosen.get("MD5", "")).casefold(),
        labels,
        str(chosen.get("PatchUrl", "") or "").strip(),
    )


def release_guidance(
    local_region: str,
    preferred_region: str,
    preferred_name: str = "",
    preferred_labels: str = "",
) -> str:
    if not preferred_region:
        return ""
    labels = {label.strip().casefold() for label in preferred_labels.split(";")}
    if "rapatches" in labels:
        return (
            f"Apply the RA-supported patch for {preferred_name}"
            if preferred_name
            else "Apply the listed RA-supported patch"
        )
    if local_region == preferred_region:
        return f"Use the listed {preferred_region} Redump-compatible release/revision"
    if preferred_region == "USA":
        return "Use the listed NTSC USA Redump-compatible release"
    if preferred_region == "Japan":
        return "Use the listed NTSC Japan release (no supported USA release)"
    if preferred_region == "Europe":
        return "Use the listed PAL Europe release (no preferred USA/Japan release)"
    return f"Use the listed {preferred_region} release"


def ps1_hash_target(cue: Path) -> Path:
    """Use the referenced BIN for single-BIN PS1 CUE sheets."""
    try:
        lines = cue.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        lines = cue.read_text(encoding="cp1252").splitlines()
    except OSError as exc:
        raise MatchError(f"Cannot read PS1 CUE: {exc}") from None
    refs = []
    for line in lines:
        if not line.lstrip().upper().startswith("FILE "):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            raise MatchError("Invalid PS1 CUE FILE declaration") from None
        if len(tokens) != 3 or tokens[0].upper() != "FILE" or tokens[2].upper() != "BINARY":
            raise MatchError("Unsupported PS1 CUE FILE declaration")
        refs.append(tokens[1])
    if len(refs) != 1:
        raise MatchError("PS1 CUE requires exactly one referenced BIN")
    name = refs[0]
    if name in (".", "..") or "/" in name or "\\" in name or not name.lower().endswith(".bin"):
        raise MatchError("Unsafe PS1 BIN reference")
    target = cue.parent / name
    if target.is_symlink() or not target.is_file():
        raise MatchError(f"Referenced PS1 BIN missing: {name}")
    return target


def hash_file(hasher: Path, console_id: int, path: Path) -> str:
    try:
        result = subprocess.run(
            [str(hasher), str(console_id), str(path)],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MatchError(type(exc).__name__) from None
    combined = f"{result.stdout}\n{result.stderr}"
    try:
        return extract_hash(combined)
    except MatchError:
        message = combined.strip().splitlines()
        detail = message[-1][:160] if message else f"exit code {result.returncode}"
        raise MatchError(detail) from None


def load_reviewed_ps2_no_listings() -> set[str]:
    """Manual RA search results; not proof the upstream catalogue cannot change."""
    path = Path(__file__).resolve().parents[2] / "config" / "ps2-reviewed-no-listing.csv"
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        return {
            str(row.get("disc_serial", "")).strip().upper()
            for row in csv.DictReader(source)
            if row.get("review_status") == "no-listing"
            and re.fullmatch(r"[A-Z]{4}-[0-9]{5}", str(row.get("disc_serial", "")).strip().upper())
        }


def load_reviewed_ps2_alternatives() -> dict[str, int]:
    """Recommend a different RA-supported edition without equating disc identities."""
    path = Path(__file__).resolve().parents[2] / "config" / "ps2-reviewed-ra-identities.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        return {
            str(row["disc_serial"]).strip().upper(): int(row["ra_game_id"])
            for row in csv.DictReader(source)
            if row.get("review_status") == "supported-alternative"
        }


def load_reviewed_ps2_identities() -> dict[str, int]:
    """Disc-specific crosswalk; never treat manual identity as a verified hash."""
    path = Path(__file__).resolve().parents[2] / "config" / "ps2-reviewed-ra-identities.csv"
    if not path.is_file():
        return {}
    result: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row.get("review_status") != "reviewed":
                continue
            serial = (row.get("disc_serial") or "").strip().upper()
            if not re.fullmatch(r"[A-Z]{4}-[0-9]{5}", serial):
                continue
            try:
                result[serial] = int(row["ra_game_id"])
            except (ValueError, KeyError, TypeError):
                continue
    return result


def match_collection(
    session: Session,
    root: Path,
    hasher: Path,
    cache_dir: Path,
    report_path: Path,
    client: RetroAchievementsClient | None = None,
) -> tuple[MatchSummary, ...]:
    if not hasher.is_file():
        raise MatchError(f"RAHasher is not installed: {hasher}")
    if not root.is_dir():
        raise MatchError(f"Collection mount is unavailable: {root}")

    report_rows: list[dict[str, object]] = []
    summaries: list[MatchSummary] = []
    detail_cache: dict[int, list[dict[str, object]]] = {}
    serial_aliases = load_serial_aliases()
    reviewed_ps2 = load_reviewed_ps2_identities()
    reviewed_alternatives = load_reviewed_ps2_alternatives()
    reviewed_no_listing = load_reviewed_ps2_no_listings()
    gamedb_cache = Path('/var/cache/retrodb/providers/gamedb')

    for slug, extensions in HASH_TARGET_EXTENSIONS.items():
        platform = session.scalar(select(Platform).where(Platform.slug == slug))
        if platform is None:
            raise MatchError(f"Platform is missing from the database: {slug}")
        catalogue_path = cache_dir / f"{slug}.json"
        console_id, catalogue, games = load_catalogue(catalogue_path)
        records = json.loads(catalogue_path.read_text(encoding="utf-8"))
        counts_by_id = {int(g["ID"]): int(g.get("NumAchievements", 0))
                        for g in records if isinstance(g, dict) and "ID" in g}
        with_sets = tuple(g for g in games if counts_by_id.get(g.game_id, 0) > 0)
        no_sets = tuple(g for g in games if counts_by_id.get(g.game_id, 0) == 0)
        print(f"[INFO] {platform.name}: {len(with_sets)} RA catalogue games with achievements; {len(no_sets)} without achievements.")
        try:
            gamedb_titles = load_gamedb(gamedb_cache, slug)
        except (OSError, ValueError) as exc:
            print(f'[WARN] GameDB {slug} cache unavailable: {exc}')
            gamedb_titles = {}
        print(f'[+] GameDB {slug}: {len(gamedb_titles)} cached serial titles.')
        items = list(session.scalars(select(LibraryItem).where(
            LibraryItem.platform_id == platform.id,
            LibraryItem.extension.in_(extensions),
            LibraryItem.is_missing.is_(False),
            ~LibraryItem.filename.ilike("OLD\\_%", escape="\\"),
        ).order_by(LibraryItem.relative_path)))
        counts = Counter()
        no_set_evidence = Counter()
        total = len(items)
        print(f"[+] {platform.name}: {total} disc images to check.")

        for number, item in enumerate(items, start=1):
            path = root / item.relative_path
            if item.ra_hash:
                counts["cached"] += 1
            else:
                try:
                    item.ra_hash = hash_file(hasher, console_id, ps1_hash_target(path) if slug == "playstation" else path)
                    item.ra_hash_error = None
                except MatchError as exc:
                    item.ra_hash = None
                    item.ra_hash_error = str(exc)[:500]
                item.ra_hashed_at = datetime.now(timezone.utc)

            match = catalogue.get(item.ra_hash or "")
            if match:
                item.ra_game_id, item.ra_game_title = match
                item.ra_match_status = "matched"
            elif item.ra_hash:
                item.ra_game_id = None
                item.ra_game_title = None
                item.ra_match_status = "unmatched"
            else:
                item.ra_game_id = None
                item.ra_game_title = None
                item.ra_match_status = "failed"
            session.commit()
            counts[item.ra_match_status or "failed"] += 1

            serial, local_region = identify_local_release(item.relative_path)
            internal_serial = internal_disc_serial(path, slug)
            # Preserve observed conflicts for review; never silently overwrite
            # a filename serial with a different internal disc identity.
            serial_conflict = bool(serial and internal_serial and serial != internal_serial)
            identity_source = "filename" if serial else "unidentified"
            if not serial and internal_serial:
                serial = internal_serial
                local_region = REGION_BY_PREFIX.get(serial.split("-", 1)[0], "")
                identity_source = "system-cnf"
            gamedb_title = gamedb_titles.get(serial, '')
            if slug == "playstation" and serial == "SCES-01000":
                gamedb_title = "Kula World"  # European title of Roll Away (USA)

            # Non-retail discs are identified but never promoted from a retail
            # title alone. Their hashes can still legitimately match RA.
            special_disc = serial.startswith("USGR-") or serial == "SCPM-85101"
            if serial == "SCPM-85101" and not gamedb_title:
                gamedb_title = "McDonald's Original Happy Disc (promotional demo)"
            elif serial == "USGR-00036" and not gamedb_title:
                gamedb_title = "Shoot 'Em Up Collection (hack compilation)"
            no_set_game = None
            # Curated PS1 crosswalks for different regional names / catalogue gaps.
            # These are game identities, NOT assertions that this disc hash is
            # RA-compatible. Only honour them when the RA catalogue confirms
            # that the target has no achievement set.
            if slug == "playstation" and item.ra_match_status == "unmatched":
                observed_title = (gamedb_title or friendly_local_title(item.relative_path)).casefold()
                if "supersonic racers" in observed_title or "dare devil derby 3d" in observed_title:
                    curated_id = 16649
                elif serial == "SLES-02017":
                    curated_id = 18622  # 4x4 World Trophy = Test Drive: Off-Road 3
                elif serial == "SLES-04129":
                    curated_id = 19456  # Dance Europe = Dance:UK
                elif serial == "SLES-00097":
                    # Exhumed is the European release of PS1 PowerSlave.
                    curated_id = 15920
                elif serial == "SLES-01244":
                    # European Assault: verified catalogue identity from manual review.
                    curated_id = 26626
                else:
                    curated_id = None
                if curated_id and curated_id in counts_by_id and counts_by_id[curated_id] == 0:
                    no_set_game = next((g for g in no_sets if g.game_id == curated_id), None)
            reviewed_no_set_ids = {"SLES-00097": 15920, "SLES-02017": 18622,
                                   "SLES-04129": 19456}
            fallback_no_set_id = (reviewed_no_set_ids.get(serial)
                                  if slug == "playstation" and item.ra_match_status == "unmatched"
                                  else None)
            exhumed_fallback = bool(fallback_no_set_id and fallback_no_set_id not in counts_by_id)
            recommendation = None
            confidence = "reviewed-disc-id-no-set" if exhumed_fallback else ""
            score = 0.0
            alternatives = ""
            if item.ra_match_status == "unmatched" and slug == "playstation-2" and not special_disc and serial not in reviewed_no_listing:
                confirmed_id = reviewed_ps2.get(serial)
                if confirmed_id is not None:
                    reviewed_game = next((g for g in games if g.game_id == confirmed_id), None)
                    if reviewed_game is None:
                        print(f"[WARN] Reviewed ID {confirmed_id} for {serial} absent from cached RA catalogue; manual review retained.")
                    elif counts_by_id.get(confirmed_id, 0) > 0:
                        recommendation = reviewed_game
                        confidence = "reviewed-disc-id"
                        score = 1.0
                    else:
                        no_set_game = reviewed_game
                        confidence = "reviewed-disc-id-no-set"
            if item.ra_match_status == "unmatched" and slug == "playstation-2" and not special_disc and not recommendation:
                alternative_id = reviewed_alternatives.get(serial)
                alternative_game = next((g for g in with_sets if g.game_id == alternative_id), None)
                if alternative_game:
                    recommendation = alternative_game
                    no_set_game = None
                    confidence = "supported-alternative-edition"
                    score = 1.0
            if item.ra_match_status == "unmatched" and slug == "playstation" and serial == "SLUS-00865":
                # WipEout 3 USA is NOT the Special Edition. This is an
                # alternative-edition recommendation, never a hash match.
                special_edition = next((g for g in with_sets if g.game_id == 13912), None)
                if special_edition is not None:
                    recommendation = special_edition
                    confidence = "supported-alternative-edition"
                    score = 1.0
            if item.ra_match_status == "unmatched" and slug == "playstation" and not special_disc and not recommendation and not no_set_game:
                # Manually cross-referenced retail PS1 releases. Identity only;
                # hash matching remains the sole RA-compatible criterion.
                reviewed_ps1 = {"SCES-01000": 14865,  # Kula World (Europe) = Roll Away (USA)
                                 "SLES-00054": 13493,  # X-Com: Enemy Unknown = X-COM: UFO Defense
                                  "SLPS-02430": 11243,  # Chrono Trigger Japan => Final Fantasy Chronicles USA
                                  "SCES-01706": 11305, "SCES-00242": 5332, "SLUS-00893": 11357,
                                "SLES-01761": 823,  # Action Man: Mission Xtreme = Operation Extreme
                                 "SCUS-94455": 11278, "SCUS-94488": 11278,  # Gran Turismo 2: Arcade / Simulation
                                 "SLUS-01161": 11588, "SLUS-01318": 11588,  # Driver 2: Disc 1 / Disc 2
                                 "SLES-00097": 15920}  # Exhumed = Powerslave (European release)
                reviewed_id = reviewed_ps1.get(serial)
                if reviewed_id is not None:
                    reviewed_game = next((g for g in with_sets if g.game_id == reviewed_id), None)
                    if reviewed_game is not None:
                        recommendation = reviewed_game
                        confidence = "reviewed-disc-id"
                        score = 1.0
            if item.ra_match_status == "unmatched" and not special_disc and not recommendation and not no_set_game and not exhumed_fallback and serial not in reviewed_no_listing:
                if slug == "playstation-2":
                    recommendation, confidence, score = suggest_by_serial(
                        serial, with_sets, serial_aliases
                    )
                gamedb_review = ""
                if recommendation is None and gamedb_title:
                    game, method, value, gamedb_review = resolve_catalogue_identity(
                        gamedb_title, with_sets
                    )
                    if game:
                        recommendation, confidence, score = game, method, value
                    else:
                        confidence = method
                if recommendation is None and confidence not in ('serial-alias-no-unique-ra-title',):
                    filename_game, filename_method, filename_score = suggest_game(
                        item.relative_path, with_sets
                    )
                    # Do not silently override a different GameDB identification.
                    if filename_game and gamedb_title and comparable_title(
                        filename_game.title
                    ) != comparable_title(gamedb_title):
                        filename_game = None
                    if filename_game:
                        recommendation, confidence, score = (
                            filename_game, filename_method, filename_score
                        )
                    elif not gamedb_title:
                        confidence = filename_method
                if recommendation is None:
                    alternatives = gamedb_review or alternative_candidates(
                        item.relative_path, with_sets
                    )
                if recommendation:
                    counts["recommended"] += 1

            if item.ra_match_status == "unmatched" and not recommendation and not no_set_game and not exhumed_fallback and not special_disc and serial not in reviewed_no_listing:
                identity = gamedb_title or friendly_local_title(item.relative_path)
                candidate, method, _, review = resolve_catalogue_identity(
                    identity, no_sets
                )
                if candidate:
                    no_set_game = candidate
                    no_set_evidence[method] += 1
                    confidence = confidence or method
                elif review and not alternatives:
                    alternatives = review

            accepted_hashes: list[str] = []
            accepted_names: list[str] = []
            labels: list[str] = []
            preferred_name = preferred_region = preferred_hash = preferred_labels = ""
            preferred_patch_url = ""
            if recommendation:
                accepted_hashes = list(recommendation.hashes)
                if client:
                    try:
                        if recommendation.game_id not in detail_cache:
                            detail_cache[recommendation.game_id] = client.get_game_hashes(
                                recommendation.game_id
                            )
                        details = detail_cache[recommendation.game_id]
                        accepted_hashes = [
                            str(entry.get("MD5", "")).casefold()
                            for entry in details if entry.get("MD5")
                        ] or accepted_hashes
                        accepted_names = [
                            str(entry.get("Name", "")).strip()
                            for entry in details if entry.get("Name")
                        ]
                        labels = sorted({
                            str(label)
                            for entry in details
                            for label in entry.get("Labels", [])
                            if isinstance(label, str)
                        })
                        (
                            preferred_name,
                            preferred_region,
                            preferred_hash,
                            preferred_labels,
                            preferred_patch_url,
                        ) = preferred_release(details, recommendation.game_id)
                    except RetroAchievementsError:
                        confidence += "-metadata-unavailable"

            manually_unlisted = (
                (slug == "playstation" and serial == "SLUS-01470" and item.ra_match_status == "unmatched" and not recommendation and not no_set_game)
                or (slug == "playstation-2"
                and serial in reviewed_no_listing
                and item.ra_match_status == "unmatched"
                and recommendation is None and no_set_game is None)
            )
            if manually_unlisted:
                confidence = "manual-no-ra-listing"
                alternatives = ""

            report_rows.append({
                "platform": platform.name,
                "status": item.ra_match_status,
                "path": item.relative_path,
                "local_serial": serial,
                "internal_disc_serial": internal_serial,
                "disc_id_source": identity_source,
                "disc_id_conflict": "YES" if serial_conflict else "NO",
                "local_friendly_title": friendly_local_title(item.relative_path),
                "gamedb_title": gamedb_title,
                "identity_review_reason": review_reason(
                    gamedb_title or friendly_local_title(item.relative_path),
                    alternatives, special_disc
                ) if not recommendation and not no_set_game and not exhumed_fallback and not match else "",
                "identity_resolution": (
                    "manual-no-ra-listing" if manually_unlisted else
                    "verified-ra-hash" if match else
                    confidence if recommendation or no_set_game or exhumed_fallback else
                    "special-disc" if special_disc else
                    "review-candidates" if alternatives else
                    "no-catalogue-crosswalk"
                ),
                "ra_set_status": ("NOT_LISTED" if manually_unlisted else "HAS_SET" if (recommendation or match) and
                    counts_by_id.get(recommendation.game_id if recommendation else match[0], 0) > 0
                    else "NO_SET" if (no_set_game or match or exhumed_fallback) else "UNRESOLVED"),
                "no_set_ra_game_id": (
                    no_set_game.game_id if no_set_game else
                    match[0] if match and counts_by_id.get(match[0], 0) == 0 else fallback_no_set_id if exhumed_fallback else ""
                ),
                "no_set_ra_title": (
                    no_set_game.title if no_set_game else
                    match[1] if match and counts_by_id.get(match[0], 0) == 0 else {15920: "PowerSlave", 18622: "Test Drive: Off-Road 3", 19456: "Dance:UK"}.get(fallback_no_set_id, "") if exhumed_fallback else ""
                ),
                "gamedb_identified": "YES" if gamedb_title else "NO",
                "disc_classification": ("special-disc-review" if special_disc else "standard"),
                "local_region": local_region,
                "local_ra_hash": item.ra_hash or "",
                "ra_game_id": item.ra_game_id or "",
                "ra_game_title": item.ra_game_title or "",
                "recommendation_confidence": confidence,
                "recommendation_score": f"{score:.3f}" if recommendation else "",
                "recommended_ra_game_id": recommendation.game_id if recommendation else "",
                "recommended_ra_title": recommendation.title if recommendation else "",
                "alternative_candidates": alternatives,
                "preferred_release_name": preferred_name,
                "preferred_region": preferred_region,
                "preferred_ra_hash": preferred_hash,
                "preferred_ra_labels": preferred_labels,
                "preferred_patch_url": preferred_patch_url,
                "release_guidance": release_guidance(
                    local_region, preferred_region, preferred_name, preferred_labels
                ),
                "accepted_regions": regions_from_names(accepted_names),
                "accepted_file_names": " | ".join(accepted_names),
                "accepted_ra_hashes": " | ".join(accepted_hashes),
                "ra_labels": " | ".join(labels),
                "error": item.ra_hash_error or "",
            })
            if number % 25 == 0 or number == total:
                print(f"[RUN] {platform.name}: {number}/{total} checked.")

        if no_set_evidence:
            print(f"[INFO] {platform.name}: NO_SET identity evidence: " + ", ".join(f"{method}={count}" for method, count in sorted(no_set_evidence.items())))
        summaries.append(MatchSummary(
            platform.name, total, counts["matched"], counts["unmatched"],
            counts["failed"], counts["cached"], counts["recommended"],
        ))

    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    fields = [
        "platform", "status", "path", "local_serial", "internal_disc_serial", "disc_id_source", "disc_id_conflict", "local_region",
        "local_friendly_title", "gamedb_title", "gamedb_identified",
        "identity_resolution", "identity_review_reason",
        "ra_set_status", "no_set_ra_game_id", "no_set_ra_title",
        "disc_classification",
        "local_ra_hash", "ra_game_id", "ra_game_title",
        "recommendation_confidence", "recommendation_score",
        "recommended_ra_game_id", "recommended_ra_title",
        "alternative_candidates", "preferred_release_name", "preferred_region",
        "preferred_ra_hash", "preferred_ra_labels", "release_guidance",
        "preferred_patch_url",
        "accepted_regions", "accepted_file_names", "accepted_ra_hashes",
        "ra_labels", "error",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report_rows)
    temporary.replace(report_path)
    return tuple(summaries)
