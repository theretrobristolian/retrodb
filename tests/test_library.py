from pathlib import Path
from retrodb.library import GAME_EXTENSIONS, PLATFORM_PATHS, _top_folder

def test_retronas_platform_paths_are_canonical():
    assert PLATFORM_PATHS["playstation"] == Path("roms/sony/playstation1")
    assert PLATFORM_PATHS["playstation-2"] == Path("roms/sony/playstation2")

def test_disc_image_extensions_are_recognised():
    assert {".cue", ".bin", ".chd", ".iso", ".cso"}.issubset(GAME_EXTENSIONS)

def test_top_folder_reports_cd_and_dvd_layouts():
    root = Path("/mount/roms/sony/playstation2")
    assert _top_folder(root / "cd" / "game.iso", root) == "cd"
    assert _top_folder(root / "dvd" / "game.iso", root) == "dvd"
    assert _top_folder(root / "game.iso", root) == "(root)"
