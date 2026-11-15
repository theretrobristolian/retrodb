"""Terminal permissions menu: read-only account discovery and safe allowlists."""
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "retrodb_permissions", Path(__file__).resolve().parents[1] / "server" / "server_permissions.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_web_users_are_sorted_and_hashes_are_not_returned(tmp_path):
    ht = tmp_path / "web-users.htpasswd"
    ht.write_text("zoe:$2b$hash\nalex:$2b$hash\n", encoding="utf-8")
    assert mod.web_usernames(ht) == ["alex", "zoe"]


def test_admin_permissions_are_read_from_json(tmp_path):
    path = tmp_path / "admins.json"
    assert mod.admin_usernames(path) == set()
    path.write_text(json.dumps({"admins": ["zoe", "alex"]}), encoding="utf-8")
    assert mod.admin_usernames(path) == {"zoe", "alex"}


@pytest.mark.parametrize("payload", [
    {"admins": ["alice", "alice"]},
    {"admins": ["not valid"]},
    {"admins": "alice"},
    {"unexpected": ["alice"]},
    {"admins": ["alice"], "extra": True},
])
def test_rejects_malformed_permissions(tmp_path, payload):
    path = tmp_path / "admins.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.admin_usernames(path)


def test_duplicate_or_invalid_web_accounts_rejected(tmp_path):
    ht = tmp_path / "web-users.htpasswd"
    ht.write_text("alice:hash\nalice:hash\n", encoding="utf-8")
    with pytest.raises(ValueError):
        mod.web_usernames(ht)
    ht.write_text("bad user:hash\n", encoding="utf-8")
    with pytest.raises(ValueError):
        mod.web_usernames(ht)


def test_unprivileged_process_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    target = tmp_path / "admins.json"
    target.write_text('{"admins":["alice"]}\n', encoding="utf-8")
    with pytest.raises(PermissionError):
        mod.write_admins({"bob"}, target)
    assert json.loads(target.read_text()) == {"admins": ["alice"]}


def test_rejects_invalid_selected_user_before_any_write(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        mod.write_admins({"name with spaces"}, tmp_path / "admins.json")
