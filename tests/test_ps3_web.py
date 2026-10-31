"""PS3 web catalogue naming and platform-count regressions."""
from types import SimpleNamespace

from retrodb.web_ui import disc_id, disc_region, name, platform_counts


def ps3_item(filename):
    return SimpleNamespace(filename=filename,
                           relative_path="roms/sony/playstation3/iso/" + filename,
                           ra_game_title=None)


def test_ps3_serial_region_and_release_name():
    item = ps3_item("Gran Turismo 5 - XL Edition [BCUS98114].iso")
    assert disc_id(item) == "BCUS98114"
    assert name(item, "playstation-3") == "Gran Turismo 5 - XL Edition"
    assert disc_region("BCUS98114", "playstation-3")[0] == "🇺🇸"
    assert disc_region("BLES00917", "playstation-3")[0] == "🇪🇺"
    assert disc_region("BLJM61097", "playstation-3")[0] == "🇯🇵"


def test_ps1_console_counts_exclude_bin_tracks():
    class RecordingSession:
        def execute(self, stmt):
            self.stmt = stmt
            return SimpleNamespace(all=lambda: [])

    db = RecordingSession()
    platform_counts(db)
    sql = str(db.stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'cue'" in sql
    assert "'bin'" not in sql
