from ps1_ra_no_serial import proposed, RELEASES


def test_explicit_filename_only_renames_are_safe(tmp_path):
    root = tmp_path / "collection"
    folder = root / "iso"
    folder.mkdir(parents=True)
    for game_id, (source, target, _) in RELEASES.items():
        (folder / (source + ".bin")).write_bytes(b"test")
        (folder / (source + ".cue")).write_text(
            'FILE "' + source + '.bin" BINARY\n  TRACK 01 MODE2/2352\n',
            encoding="utf-8")
    got = proposed(root, tmp_path / "unused.csv")
    assert len(got) == 4
    assert any(row[0] == "16325" and row[4].stem == "Caesars Palace II" for row in got)
    (folder / (RELEASES["15631"][1] + ".cue")).write_text("existing")
    assert len(proposed(root, tmp_path / "unused.csv")) == 3
    (folder / ("Calamity 2 - People and Traditions (USA).cue")).write_text(
        'FILE "does-not-exist.bin" BINARY\n')
    assert len(proposed(root, tmp_path / "unused.csv")) == 2
