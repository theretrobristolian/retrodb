import json

import httpx
import pytest

from retrodb.providers.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
    find_system,
)


def test_connection_and_sync_cache_do_not_expose_key(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params["z"] == "collector"
        assert request.url.params["y"] == "top-secret"
        if request.url.path.endswith("API_GetConsoleIDs.php"):
            return httpx.Response(200, json=[{"ID": 12, "Name": "PlayStation"}])
        return httpx.Response(
            200,
            json=[{"ID": 1, "Title": "Test", "Hashes": ["abc", "def"]}],
        )

    client = RetroAchievementsClient(
        "collector", "top-secret", tmp_path, transport=httpx.MockTransport(handler)
    )
    systems = client.get_systems()
    assert find_system(systems, ("PlayStation",)) == (12, "PlayStation")

    first = client.sync_system(12, "PlayStation", "playstation")
    second = client.sync_system(12, "PlayStation", "playstation")

    assert (first.games, first.hashes, first.from_cache) == (1, 2, False)
    assert second.from_cache is True
    assert len(calls) == 2
    assert json.loads(first.cache_path.read_text())[0]["Title"] == "Test"


def test_missing_credentials_are_rejected_without_values(tmp_path):
    with pytest.raises(RetroAchievementsError, match="not configured"):
        RetroAchievementsClient("", "", tmp_path)


def test_http_errors_are_sanitised(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    client = RetroAchievementsClient("user", "secret-key", tmp_path, transport=transport)
    with pytest.raises(RetroAchievementsError) as caught:
        client.get_systems()
    assert "secret-key" not in str(caught.value)
