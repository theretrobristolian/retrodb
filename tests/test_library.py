from pathlib import Path
from retrodb.library import GAME_EXTENSIONS, PLATFORM_PATHS

def test_retronas_platform_paths_are_canonical():
    assert PLATFORM_PATHS["playstation"] == Path("roms/sony/playstation1")
    assert PLATFORM_PATHS["playstation-2"] == Path("roms/sony/playstation2")

def test_disc_image_extensions_are_recognised():
    assert {".cue", ".bin", ".chd", ".iso", ".cso"}.issubset(GAME_EXTENSIONS)
