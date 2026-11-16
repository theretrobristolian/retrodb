"""Read-only Settings snapshots and permissions-aware layout."""
from fastapi.testclient import TestClient
import pytest

from retrodb.main import app
from retrodb import session_auth, server_management, system_info


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv("RETRODB_SESSION_SECRET", "settings-tests-only-" + "x" * 60)


def fake_snapshot():
    return {
        "hostname": "retrodb-vm",
        "ip": "192.0.2.15",
        "os": "Debian GNU/Linux 13",
        "architecture": "x86_64",
        "hardware_type": "Virtual machine",
        "model": "VMware Virtual Platform",
        "uptime": 90061,
        "cpu_cores": 4,
        "cpu_percent": 17.5,
        "memory": (2 * 1024**3, 4 * 1024**3, 50.0),
        "disk": (50 * 1024**3, 100 * 1024**3, 50.0),
        "retronas_disk": None,
        "xerabora": "active",
        "captured": "2026-11-16 12:00:00 GMT",
    }


def test_admin_settings_layout_and_static_refresh(monkeypatch):
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "operator")
    monkeypatch.setattr(server_management, "user_from_cookie", lambda _: "operator")
    monkeypatch.setattr(server_management, "is_server_admin", lambda user: True)
    reads = []
    monkeypatch.setattr(system_info, "snapshot", lambda: reads.append(1) or fake_snapshot())
    client = TestClient(app, base_url="https://retrodb.example", follow_redirects=False)
    home = client.get("/settings")
    assert home.status_code == 200
    assert "retrodb-vm" in home.text
    assert "192.0.2.15" in home.text
    assert "VMware Virtual Platform" in home.text
    assert "17.5%" in home.text
    assert "2.0 GiB" in home.text
    assert "System disk (/)" in home.text
    assert 'data-refresh-settings aria-label="Refresh system information"' in home.text
    assert home.text.index('id="system-information"') < home.text.index('id="services"')
    assert home.text.index('id="services"') < home.text.index('id="library-management"')
    assert home.text.index('data-open-dialog="reboot-server"') < home.text.index('data-open-dialog="restart-xerabora"')
    assert 'data-state="active"' in home.text
    assert "RetroNAS share" not in home.text
    assert 'data-refresh-settings aria-label="Refresh service status"' in home.text
    assert 'window.location.reload()' in home.text
    assert 'href="/settings?refresh=1#' not in home.text
    assert reads == [1]
    refreshed = client.get("/settings?refresh=1")
    assert refreshed.status_code == 200
    assert reads == [1, 1]
    assert refreshed.headers["Cache-Control"] == "no-store"
    legacy = client.get("/settings/server")
    assert legacy.status_code == 200


def test_non_admin_cannot_see_host_or_service_details(monkeypatch):
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "visitor")
    monkeypatch.setattr(server_management, "user_from_cookie", lambda _: "visitor")
    monkeypatch.setattr(server_management, "is_server_admin", lambda user: False)
    def forbidden():
        raise AssertionError("Host snapshot must not run for ordinary users")
    monkeypatch.setattr(system_info, "snapshot", forbidden)
    client = TestClient(app, base_url="https://retrodb.example")
    home = client.get("/settings")
    assert home.status_code == 200
    assert "Library management" in home.text
    assert 'data-open-dialog="reboot-server"' not in home.text
    assert 'data-open-dialog="restart-xerabora"' not in home.text


def test_telemetry_failure_still_shows_library_settings(monkeypatch):
    monkeypatch.setattr(session_auth, "user_from_cookie", lambda _: "operator")
    monkeypatch.setattr(server_management, "user_from_cookie", lambda _: "operator")
    monkeypatch.setattr(server_management, "is_server_admin", lambda user: True)
    def broken():
        raise OSError("unavailable")
    monkeypatch.setattr(system_info, "snapshot", broken)
    home = TestClient(app).get("/settings")
    assert home.status_code == 200
    assert "Library management" in home.text
    assert "Restart server" in home.text


def test_hardware_raspberry_pi_and_vm(monkeypatch):
    real = system_info.read_text
    def pi_read(path, limit=16384):
        if path == "/proc/device-tree/model":
            return "Raspberry Pi 5 Model B Rev 1.0"
        return ""
    monkeypatch.setattr(system_info, "read_text", pi_read)
    assert system_info.hardware() == ("Raspberry Pi", "Raspberry Pi 5 Model B Rev 1.0")
    def vm_read(path, limit=16384):
        return {"/sys/class/dmi/id/sys_vendor": "VMware, Inc.",
                "/sys/class/dmi/id/product_name": "VMware Virtual Platform"}.get(path, "")
    monkeypatch.setattr(system_info, "read_text", vm_read)
    category, model = system_info.hardware()
    assert category == "Virtual machine"
    assert "VMware" in model


def test_memory_cpu_disk_and_service_state_defensive(monkeypatch):
    monkeypatch.setattr(system_info, "read_text", lambda path, limit=16384:
                        "MemTotal: 4096 kB\nMemAvailable: 1024 kB\n" if path == "/proc/meminfo" else "")
    assert system_info.memory_usage() == (3072 * 1024, 4096 * 1024, 75.0)
    assert system_info.service_state("ssh.service") == "unknown"
    assert server_management.format_bytes(2 * 1024**3) == "2.0 GiB"
