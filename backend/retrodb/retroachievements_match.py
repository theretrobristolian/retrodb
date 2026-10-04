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
import subprocess
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from retrodb.models import LibraryItem, Platform
from retrodb.providers.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
)

HASH_PATTERN = re.compile(r"\b([0-9a-fA-F]{32})\b")
SERIAL_PATTERN = re.compile(
    r"\b(SCUS|SLUS|SCES|SLES|SCPS|SLPS|SLPM|SCCS|SCKA)[_. -]?(\d{3})[_. -]?(\d{2})\b",
    re.IGNORECASE,
)
HASH_TARGET_EXTENSIONS = {"playstation": {"cue"}, "playstation-2": {"iso"}}
REGION_BY_PREFIX = {
    "SCUS": "USA", "SLUS": "USA",
    "SCES": "Europe", "SLES": "Europe",
    "SCPS": "Japan", "SLPS": "Japan", "SLPM": "Japan",
    "SCCS": "China", "SCKA": "Korea",
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


def normalise_title(value: str) -> str:
    title = Path(value).name
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
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
    special = {"demo", "prototype", "hack", "bonus"}
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
        elif word not in {"a", "an", "the"}:
            expanded.append({"vs": "versus"}.get(word, word))
    comparable = " ".join(expanded)
    comparable = re.sub(r"\bdual shock (?:ver|version)\b", "", comparable)
    aliases = {
        "harry potter and philosophers stone": "harry potter and sorcerers stone",
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
) -> tuple[str, str, str, str]:
    """Choose RA's cleanest preferred TV-console release and final revision."""
    if not details:
        return "", "", "", ""

    def sort_key(entry: dict[str, object]) -> tuple[int, int, int, int, str]:
        name = str(entry.get("Name", ""))
        region = release_region(name)
        region_rank = {
            "USA": 0, "World": 0, "Japan": 1, "Europe": 2,
        }.get(region, 3)
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

    for slug, extensions in HASH_TARGET_EXTENSIONS.items():
        platform = session.scalar(select(Platform).where(Platform.slug == slug))
        if platform is None:
            raise MatchError(f"Platform is missing from the database: {slug}")
        console_id, catalogue, games = load_catalogue(cache_dir / f"{slug}.json")
        items = list(session.scalars(select(LibraryItem).where(
            LibraryItem.platform_id == platform.id,
            LibraryItem.extension.in_(extensions),
            LibraryItem.is_missing.is_(False),
        ).order_by(LibraryItem.relative_path)))
        counts = Counter()
        total = len(items)
        print(f"[+] {platform.name}: {total} disc images to check.")

        for number, item in enumerate(items, start=1):
            path = root / item.relative_path
            if item.ra_hash:
                counts["cached"] += 1
            else:
                try:
                    item.ra_hash = hash_file(hasher, console_id, path)
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
            recommendation = None
            confidence = ""
            score = 0.0
            alternatives = ""
            if item.ra_match_status == "unmatched":
                recommendation, confidence, score = suggest_game(item.relative_path, games)
                if confidence == "ambiguous":
                    alternatives = alternative_candidates(item.relative_path, games)
                if recommendation:
                    counts["recommended"] += 1

            accepted_hashes: list[str] = []
            accepted_names: list[str] = []
            labels: list[str] = []
            preferred_name = preferred_region = preferred_hash = preferred_labels = ""
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
                        ) = preferred_release(details)
                    except RetroAchievementsError:
                        confidence += "-metadata-unavailable"

            report_rows.append({
                "platform": platform.name,
                "status": item.ra_match_status,
                "path": item.relative_path,
                "local_serial": serial,
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

        summaries.append(MatchSummary(
            platform.name, total, counts["matched"], counts["unmatched"],
            counts["failed"], counts["cached"], counts["recommended"],
        ))

    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    fields = [
        "platform", "status", "path", "local_serial", "local_region",
        "local_ra_hash", "ra_game_id", "ra_game_title",
        "recommendation_confidence", "recommendation_score",
        "recommended_ra_game_id", "recommended_ra_title",
        "alternative_candidates", "preferred_release_name", "preferred_region",
        "preferred_ra_hash", "preferred_ra_labels", "release_guidance",
        "accepted_regions", "accepted_file_names", "accepted_ra_hashes",
        "ra_labels", "error",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report_rows)
    temporary.replace(report_path)
    return tuple(summaries)
