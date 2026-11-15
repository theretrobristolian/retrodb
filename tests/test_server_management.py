"""Settings server controls: authorisation, confirmation and restricted helper."""
import importlib.util
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from retrodb.main import app
from retrodb import session_auth, server_management


def test_settings_server_blocks_guests_and_unapproved_users(monkeypatch, tmp_path):
    monkeypatch.setenv("RETRODB_SESSION_SECRET", "test-only-secret-" + "x" * 60)
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "__retrodb_guest__")
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house")
    assert client.get("/settings/server").status_code == 403
    assert client.post("/settings/server/action", data={"action": "reboot-server"}).status_code == 403
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "visitor")
    monkeypatch.setattr(server_management, "user_from_cookie", lambda _: "visitor")
    admins = tmp_path / "admins.json"
    admins.write_text('{"admins":["operator"]}')
    monkeypatch.setattr(server_management, "ADMINS", admins)
    restricted = client.get("/settings/server")
    assert restricted.status_code == 200
    assert "limited to explicitly approved" in restricted.text
    assert 'data-open-dialog="reboot-server"' not in restricted.text
    assert client.post("/settings/server/action", data={"action": "reboot-server"}).status_code == 403


def test_admin_server_buttons_require_exact_csrf_and_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("RETRODB_SESSION_SECRET", "test-only-secret-" + "x" * 60)
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "operator")
    monkeypatch.setattr(server_management, "user_from_cookie", lambda _: "operator")
    admins = tmp_path / "admins.json"
    admins.write_text('{"admins":["operator"]}')
    monkeypatch.setattr(server_management, "ADMINS", admins)
    calls = []
    monkeypatch.setattr(server_management, "perform_action",
                        lambda user, action: calls.append((user, action)))
    client = TestClient(app, base_url="https://retrodb.it.gattaca.house", follow_redirects=False)
    view = client.get("/settings/server")
    assert view.status_code == 200
    assert 'data-open-dialog="restart-xerabora"' in view.text
    assert 'data-open-dialog="reboot-server"' in view.text
    assert calls == []
    tokens = re.findall(r'name="csrf_token" value="([^"]+)"', view.text)
    assert tokens
    path = "/settings/server/action"
    assert client.post(path, data={"action": "reboot-server", "confirm": "REBOOT",
                                   "csrf_token": "invalid"}).status_code == 403
    assert client.post(path, data={"action": "reboot-server", "confirm": "RESTART",
                                   "csrf_token": tokens[-1]}).status_code == 403
    assert calls == []
    success = client.post(path, data={"action": "restart-xerabora",
                                     "confirm": "RESTART", "csrf_token": tokens[-1]})
    assert success.status_code == 303
    assert success.headers["location"] == "/settings/server?result=restart"
    assert calls == [("operator", "restart-xerabora")]


def test_restricted_helper_only_accepts_allowlisted_operations(monkeypatch, tmp_path):
    helper = Path(__file__).resolve().parents[1] / "server" / "xerabora-switch-helper.py"
    spec = importlib.util.spec_from_file_location("retrodb_restart_helper", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    admins = tmp_path / "admins.json"
    admins.write_text('{"admins":["operator"]}')
    monkeypatch.setattr(module, "SERVER_ADMINS", admins)
    calls = []
    monkeypatch.setattr(module, "command", lambda *args: calls.append(args))
    assert module.execute_admin_request({"admin": "operator", "operation": "restart-xerabora"})
    assert calls == [("/usr/bin/systemctl", "--no-block", "restart", "xerabora.service")]
    calls.clear()
    assert module.execute_admin_request({"admin": "operator", "operation": "reboot-server"})
    assert calls[0][:3] == ("/usr/bin/systemd-run", "--unit=retrodb-web-reboot", "--on-active=10s")
    calls.clear()
    import pytest
    with pytest.raises(PermissionError):
        module.execute_admin_request({"admin": "visitor", "operation": "reboot-server"})
    with pytest.raises(ValueError):
        module.execute_admin_request({"admin": "operator", "operation": "shutdown"})
    with pytest.raises(ValueError):
        module.execute_admin_request({"admin": "operator", "operation": "restart-xerabora",
                                      "service": "ssh.service"})
    assert calls == []
