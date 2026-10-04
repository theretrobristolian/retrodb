"""Small, cache-first client for the RetroAchievements Web API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from typing import Any

import httpx


API_BASE_URL = "https://retroachievements.org/API"
DEFAULT_CACHE_TTL = timedelta(days=180)


class RetroAchievementsError(RuntimeError):
    """A safe-to-display provider error which never contains credentials."""


@dataclass(frozen=True)
class SyncResult:
    system_id: int
    system_name: str
    games: int
    hashes: int
    cache_path: Path
    from_cache: bool


class RetroAchievementsClient:
    def __init__(
        self,
        username: str,
        api_key: str,
        cache_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.username = username.strip()
        self.api_key = api_key.strip()
        self.cache_dir = cache_dir
        self.transport = transport
        if not self.username or not self.api_key:
            raise RetroAchievementsError(
                "RetroAchievements username and Web API key are not configured."
            )

    def _request(self, endpoint: str, parameters: dict[str, Any]) -> Any:
        params = {"z": self.username, "y": self.api_key, **parameters}
        try:
            with httpx.Client(
                timeout=httpx.Timeout(120.0),
                follow_redirects=True,
                transport=self.transport,
                headers={"User-Agent": "RetroDB/0.1"},
            ) as client:
                response = client.get(f"{API_BASE_URL}/{endpoint}", params=params)
        except httpx.HTTPError as exc:
            raise RetroAchievementsError(
                f"RetroAchievements request failed ({type(exc).__name__})."
            ) from None

        if response.status_code != 200:
            raise RetroAchievementsError(
                f"RetroAchievements returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError:
            raise RetroAchievementsError(
                "RetroAchievements returned an invalid response."
            ) from None
        if isinstance(payload, dict) and payload.get("Success") is False:
            raise RetroAchievementsError("RetroAchievements rejected the request.")
        return payload

    def get_systems(self) -> list[dict[str, Any]]:
        payload = self._request("API_GetConsoleIDs.php", {})
        if not isinstance(payload, list):
            raise RetroAchievementsError(
                "RetroAchievements returned an unexpected systems response."
            )
        return payload

    def test_connection(self) -> int:
        return len(self.get_systems())

    def sync_system(
        self,
        system_id: int,
        system_name: str,
        cache_slug: str,
        *,
        force: bool = False,
    ) -> SyncResult:
        cache_path = self.cache_dir / f"{cache_slug}.json"
        payload, from_cache = self._cached_game_list(cache_path, system_id, force)
        game_count = len(payload)
        hash_count = sum(
            len(game.get("Hashes", []))
            for game in payload
            if isinstance(game, dict) and isinstance(game.get("Hashes", []), list)
        )
        return SyncResult(
            system_id=system_id,
            system_name=system_name,
            games=game_count,
            hashes=hash_count,
            cache_path=cache_path,
            from_cache=from_cache,
        )

    def _cached_game_list(
        self, cache_path: Path, system_id: int, force: bool
    ) -> tuple[list[dict[str, Any]], bool]:
        if not force and self._cache_is_fresh(cache_path):
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    return payload, True
            except (OSError, ValueError):
                pass

        payload = self._request(
            "API_GetGameList.php", {"i": system_id, "f": 1, "h": 1}
        )
        if not isinstance(payload, list):
            raise RetroAchievementsError(
                "RetroAchievements returned an unexpected game-list response."
            )
        self._write_cache(cache_path, payload)
        return payload, False

    def get_game_hashes(
        self, game_id: int, *, force: bool = False
    ) -> list[dict[str, Any]]:
        """Return hash metadata for one game, cached to avoid repeated API calls."""
        cache_path = self.cache_dir / "games" / f"{game_id}.json"
        if not force and self._cache_is_fresh(cache_path):
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    return payload
            except (OSError, ValueError):
                pass

        payload = self._request("API_GetGameHashes.php", {"i": game_id})
        results = payload.get("Results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise RetroAchievementsError(
                "RetroAchievements returned an unexpected game-hashes response."
            )
        clean = [entry for entry in results if isinstance(entry, dict)]
        self._write_cache(cache_path, clean)
        return clean

    @staticmethod
    def _cache_is_fresh(path: Path) -> bool:
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            return False
        return datetime.now(timezone.utc) - modified < DEFAULT_CACHE_TTL

    @staticmethod
    def _write_cache(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            temporary_path = Path(handle.name)
        temporary_path.replace(path)


def find_system(
    systems: list[dict[str, Any]], accepted_names: tuple[str, ...]
) -> tuple[int, str]:
    accepted = {name.casefold() for name in accepted_names}
    for system in systems:
        name = str(system.get("Name", "")).strip()
        if name.casefold() in accepted:
            try:
                return int(system["ID"]), name
            except (KeyError, TypeError, ValueError):
                break
    raise RetroAchievementsError(
        f"Could not find RetroAchievements system: {accepted_names[0]}."
    )
