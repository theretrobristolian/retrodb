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
            json=[{"ID": 1, "Title": "Test", "Hashes": ["abc", "def"], "NumAchievements": 0}],
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


def test_valid_cache_avoids_network_entirely(tmp_path):
    cache = tmp_path / "playstation.json"
    cache.write_text(json.dumps([{"ID": 1, "Hashes": ["a"], "NumAchievements": 0}]))
    def unavailable(request):
        raise AssertionError("No HTTP request should occur for a fresh catalogue")
    client = RetroAchievementsClient(
        "collector", "secret", tmp_path, transport=httpx.MockTransport(unavailable)
    )
    result = client.sync_system(12, "PlayStation", "playstation")
    assert result.from_cache and not result.stale_fallback
    assert result.hashes == 1


def test_stale_cache_fallback_after_502(tmp_path, monkeypatch):
    import os
    import time
    from datetime import timedelta
    from retrodb.providers.retroachievements import DEFAULT_CACHE_TTL
    cache = tmp_path / "playstation.json"
    cache.write_text(json.dumps([{"ID": 1, "Hashes": ["a"], "NumAchievements": 0}]))
    old = time.time() - DEFAULT_CACHE_TTL.total_seconds() - timedelta(days=1).total_seconds()
    os.utime(cache, (old, old))
    requests = []
    def bad_gateway(request):
        requests.append(request)
        return httpx.Response(502)
    monkeypatch.setattr("retrodb.providers.retroachievements.time.sleep", lambda _: None)
    client = RetroAchievementsClient(
        "collector", "secret", tmp_path, transport=httpx.MockTransport(bad_gateway)
    )
    result = client.sync_system(12, "PlayStation", "playstation")
    assert result.from_cache and result.stale_fallback
    assert len(requests) == 3
    with pytest.raises(RetroAchievementsError, match="HTTP 502"):
        client.sync_system(12, "PlayStation", "playstation", force=True)


def test_auth_error_never_uses_stale_cache(tmp_path):
    import os
    import time
    cache = tmp_path / "playstation.json"
    cache.write_text(json.dumps([{"ID": 1, "Hashes": [], "NumAchievements": 0}]))
    old = time.time() - 190 * 86400
    os.utime(cache, (old, old))
    client = RetroAchievementsClient(
        "collector", "secret", tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(401)),
    )
    with pytest.raises(RetroAchievementsError, match="HTTP 401"):
        client.sync_system(12, "PlayStation", "playstation")
