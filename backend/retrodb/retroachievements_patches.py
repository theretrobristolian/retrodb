"""Create safe patch workspaces for RetroAchievements-supported disc patches."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

from retrodb.retroachievements_match import HASH_PATTERN, hash_file, normalise_title


class PatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PatchPlanSummary:
    patches: int
    official_links: int
    workspace: Path


@dataclass(frozen=True)
class PatchPrepareSummary:
    patches: int
    already_verified: int
    candidates: int
    missing: int


@dataclass(frozen=True)
class PatchDownloadSummary:
    patches: int
    downloaded: int
    reused: int
    failed: int


MAX_PATCH_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_PATCH_EXTRACT_BYTES = 256 * 1024 * 1024
MAX_PATCH_FILES = 500


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:80] or "unknown-game"


def _official_patch_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not (
        host == "retroachievements.org"
        or host.endswith(".retroachievements.org")
        or host == "github.com"
        or host.endswith(".githubusercontent.com")
    ):
        return ""
    return value


def _load_rows(report_path: Path) -> list[dict[str, str]]:
    try:
        with report_path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise PatchError(f"Cannot read compatibility report: {report_path}") from exc


def _patch_url_from_cache(cache_dir: Path, game_id: str, target_hash: str) -> str:
    if not game_id or not target_hash:
        return ""
    path = cache_dir / "games" / f"{game_id}.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("MD5", "")).casefold() == target_hash.casefold():
            return _official_patch_url(str(entry.get("PatchUrl", "") or "").strip())
    return ""


def _patch_rows(report_path: Path, cache_dir: Path) -> list[dict[str, str]]:
    result = []
    for row in _load_rows(report_path):
        labels = {part.strip().casefold() for part in row.get("preferred_ra_labels", "").split(";")}
        if "rapatches" not in labels:
            continue
        target_hash = row.get("preferred_ra_hash", "").casefold()
        if not HASH_PATTERN.fullmatch(target_hash):
            continue
        row = dict(row)
        row["preferred_patch_url"] = _official_patch_url(
            row.get("preferred_patch_url", "")
        ) or _patch_url_from_cache(
            cache_dir, row.get("recommended_ra_game_id", ""), target_hash
        )
        result.append(row)
    return result


def create_patch_plan(report_path: Path, cache_dir: Path, workspace: Path) -> PatchPlanSummary:
    rows = _patch_rows(report_path, cache_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("downloads", "incoming", "workspace", "verified", "failed"):
        (workspace / name).mkdir(exist_ok=True)

    manifest = []
    for row in rows:
        game_id = row.get("recommended_ra_game_id", "unknown")
        title = row.get("recommended_ra_title", "Unknown game")
        game_dir = workspace / "downloads" / f"{game_id}-{_safe_slug(title)}"
        game_dir.mkdir(exist_ok=True)
        entry = {
            "ra_game_id": game_id,
            "title": title,
            "platform": row.get("platform", ""),
            "local_path": row.get("path", ""),
            "local_region": row.get("local_region", ""),
            "local_ra_hash": row.get("local_ra_hash", ""),
            "required_release": row.get("preferred_release_name", ""),
            "required_region": row.get("preferred_region", ""),
            "expected_ra_hash": row.get("preferred_ra_hash", ""),
            "patch_url": row.get("preferred_patch_url", ""),
            "status": "patch-link-found" if row.get("preferred_patch_url") else "manual-link-required",
        }
        manifest.append(entry)
        (game_dir / "manifest.json").write_text(
            json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        patch_line = entry["patch_url"] or "Not exposed by cached RA metadata; open the RA game page's Supported Game Files section."
        readme = f"""# {title}

## Required release

- Platform: {entry['platform']}
- Release: {entry['required_release']}
- Region: {entry['required_region']}
- Expected RetroAchievements hash after patching: `{entry['expected_ra_hash']}`
- Official patch: {patch_line}

## Safe workflow

1. Obtain the exact clean release named above from your own media.
2. Put it in `{workspace / 'incoming'}`. Do not alter the RetroNAS original.
3. Run `sudo bash server/retronas.sh patch-prepare`.
4. Only apply the patch after its README/source checksum agrees with the clean image.
5. Verify the patched output with RAHasher. It must equal the expected hash above.

The current RetroNAS mount remains read-only. No ROM has been downloaded, copied or modified by patch-plan.
"""
        (game_dir / "README.md").write_text(readme, encoding="utf-8")

    (workspace / "patch-plan.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return PatchPlanSummary(len(rows), sum(bool(row.get("preferred_patch_url")) for row in rows), workspace)


def _download_patch(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "RetroDB/0.1 patch downloader"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - URL is allowlisted below
        final_url = response.geturl()
        if not _official_patch_url(final_url):
            raise PatchError(f"Patch download redirected to an untrusted host: {final_url}")
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_PATCH_DOWNLOAD_BYTES:
            raise PatchError("Patch archive exceeds the 64 MiB download limit")
        with destination.open("wb") as handle:
            copied = 0
            while chunk := response.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_PATCH_DOWNLOAD_BYTES:
                    raise PatchError("Patch archive exceeds the 64 MiB download limit")
                handle.write(chunk)


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_PATCH_FILES:
                raise PatchError("Patch archive contains too many files")
            if sum(member.file_size for member in members) > MAX_PATCH_EXTRACT_BYTES:
                raise PatchError("Expanded patch archive exceeds the 256 MiB limit")
            root = destination.resolve()
            for member in members:
                target = (destination / member.filename).resolve()
                if target != root and root not in target.parents:
                    raise PatchError(f"Unsafe path in patch archive: {member.filename}")
            bundle.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise PatchError("Downloaded patch is not a valid ZIP archive") from exc


def download_patch_archives(workspace: Path) -> PatchDownloadSummary:
    plan_path = workspace / "patch-plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PatchError(f"Cannot read patch plan: {plan_path}; run patch-plan first") from exc
    if not isinstance(plan, list):
        raise PatchError(f"Invalid patch plan: {plan_path}")

    downloaded = reused = failed = 0
    results = []
    downloads_root = workspace / "downloads"
    downloads_root.mkdir(parents=True, exist_ok=True)
    for entry in plan:
        title = str(entry.get("title", "Unknown game"))
        game_id = str(entry.get("ra_game_id", "unknown"))
        url = _official_patch_url(str(entry.get("patch_url", "")))
        result = {"ra_game_id": game_id, "title": title, "patch_url": url}
        if not url:
            result.update(status="failed", error="No trusted official patch URL")
            failed += 1
            results.append(result)
            continue
        game_dir = downloads_root / f"{game_id}-{_safe_slug(title)}"
        archive = game_dir / "official-patch.zip"
        extracted = game_dir / "extracted"
        temporary = game_dir / "official-patch.zip.part"
        try:
            game_dir.mkdir(parents=True, exist_ok=True)
            if archive.is_file() and extracted.is_dir():
                reused += 1
                status = "reused"
            else:
                temporary.unlink(missing_ok=True)
                _download_patch(url, temporary)
                temporary.replace(archive)
                if extracted.exists():
                    shutil.rmtree(extracted)
                extracted.mkdir()
                _safe_extract_zip(archive, extracted)
                downloaded += 1
                status = "downloaded"
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            guidance = sorted(
                str(path.relative_to(game_dir)) for path in extracted.rglob("*")
                if path.is_file() and path.suffix.casefold() in {".md", ".txt", ".nfo"}
            )
            result.update(
                status=status,
                archive=str(archive),
                archive_sha256=digest,
                extracted_to=str(extracted),
                guidance_files=guidance,
            )
        except (OSError, ValueError, PatchError) as exc:
            temporary.unlink(missing_ok=True)
            result.update(status="failed", error=str(exc))
            failed += 1
        results.append(result)

    (workspace / "patch-download.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return PatchDownloadSummary(len(plan), downloaded, reused, failed)


def prepare_patch_sources(
    report_path: Path,
    cache_dir: Path,
    workspace: Path,
    collection_root: Path,
    hasher: Path,
) -> PatchPrepareSummary:
    rows = _patch_rows(report_path, cache_dir)
    incoming = workspace / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    candidates = [path for path in incoming.rglob("*") if path.is_file() and path.suffix.casefold() in {".cue", ".iso"}]
    already_verified = candidate_count = missing = 0
    results = []
    console_ids = {"Sony PlayStation": 12, "Sony PlayStation 2": 21}

    for row in rows:
        title_key = normalise_title(row.get("recommended_ra_title", ""))
        matching = [path for path in candidates if title_key and title_key in normalise_title(path.name)]
        state = "missing-source"
        found = ""
        actual_hash = ""
        for path in matching:
            console_id = console_ids.get(row.get("platform", ""))
            if not console_id:
                continue
            actual_hash = hash_file(hasher, console_id, path)
            found = str(path)
            if actual_hash == row.get("preferred_ra_hash", "").casefold():
                state = "already-patched-and-verified"
                already_verified += 1
            else:
                state = "candidate-source-needs-patch-readme-validation"
                candidate_count += 1
            break
        else:
            missing += 1
        results.append({
            "title": row.get("recommended_ra_title", ""),
            "state": state,
            "candidate_path": found,
            "candidate_ra_hash": actual_hash,
            "expected_patched_ra_hash": row.get("preferred_ra_hash", ""),
            "collection_source": str(collection_root / row.get("path", "")),
        })

    (workspace / "patch-prepare.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return PatchPrepareSummary(len(rows), already_verified, candidate_count, missing)
