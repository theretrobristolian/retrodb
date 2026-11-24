"""Wii catalogue safety checks that run without writing to PostgreSQL."""
import csv
from pathlib import Path

import pytest
from retrodb import wii_sync
from retrodb import web_ui
from types import SimpleNamespace


def report(tmp_path, rows):
    path = tmp_path / "wii.csv"
    fields = ("status", "relative_path", "filename", "disc_id", "title",
              "title_source", "region", "size_bytes", "ra_game_id",
              "ra_title", "ra_achievements", "reason")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(**changes):
    data = dict(status="TITLE_CANDIDATE",
                relative_path="Attack of the Movies 3D [S3AE5G]/S3AE5G.wbfs",
                filename="S3AE5G.wbfs", disc_id="S3AE5G",
                title="Attack of the Movies 3D", title_source="folder",
                region="USA", size_bytes=1024, ra_game_id="123",
                ra_title="Attack of the Movies 3D", ra_achievements="19",
                reason="RA title candidate only; WBFS content hash not verified")
    data.update(changes)
    return data


@pytest.mark.parametrize("change", [
    {"relative_path": "../elsewhere/S3AE5G.wbfs"},
    {"relative_path": "/absolute/S3AE5G.wbfs"},
    {"relative_path": "S3AE5G.wbfs"},
    {"relative_path": "Wrong [S3AE5G]/OTHER1.wbfs", "filename": "OTHER1.wbfs"},
    {"relative_path": "Attack of the Movies 3D [S3AE5G]/S3AE5G.exe", "filename": "S3AE5G.exe"},
    {"status": "EXACT_RA"},
    {"disc_id": "OTHER1"},
])
def test_unsafe_records_rejected_before_database_access(tmp_path, change):
    csv_path = report(tmp_path, [row(**change)])
    with pytest.raises(ValueError):
        wii_sync.sync(csv_path, tmp_path)


def test_duplicate_paths_rejected(tmp_path):
    csv_path = report(tmp_path, [row(), row()])
    with pytest.raises(ValueError, match="Duplicate"):
        wii_sync.sync(csv_path, tmp_path)


def test_disc_id_and_region_are_visible_in_web_ui():
    item = SimpleNamespace(filename="S3AE5G.wbfs",
                           relative_path="roms/nintendo/wii/Attack of the Movies 3D [S3AE5G]/S3AE5G.wbfs",
                           ra_game_id=None, ra_match_status="review")
    assert web_ui.disc_id(item) == "S3AE5G"
    assert "USA" in web_ui.disc_region("S3AE5G", "wii")[1]
    assert not web_ui.ra_supported(item, "wii")
    assert web_ui.name(SimpleNamespace(**vars(item), ra_game_title="Attack of the Movies 3D"), "wii") == "Attack of the Movies 3D"
