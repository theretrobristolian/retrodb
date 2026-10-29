"""Safety regression tests for reviewed RA-verified PS1 CUE/BIN promotion."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import ps1_ra_conflict as resolver


def fixture_pairs(tmp_path, profile):
    cfg = resolver.PROFILES[profile]
    folder = tmp_path / "iso"
    folder.mkdir()
    for name, data in ((cfg["source"], b"verified"), (cfg["target"], b"unmatched")):
        (folder / (name + ".bin")).write_bytes(data)
        (folder / (name + ".cue")).write_text(
            'FILE "' + name + '.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
    def pretend_hash(_hasher, path):
        content = Path(path).read_bytes()
        return cfg["verified"] if content == b"verified" else "f" * 32
    return cfg, pretend_hash


def make_audit(tmp_path, cfg):
    import csv
    path = tmp_path / "ra-audit.csv"
    fields = ["platform", "path", "status", "local_serial", "ra_game_id",
              "recommended_ra_game_id", "local_ra_hash", "disc_id_conflict"]
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for stem, status, content_hash in (
            (cfg["source"], "matched", cfg["verified"]),
            (cfg["target"], "unmatched", "f" * 32),
        ):
            writer.writerow({
                "platform": "Sony PlayStation", "path": "iso/" + stem + ".cue",
                "status": status, "local_serial": cfg["serial"],
                "ra_game_id": cfg["ra_game_id"] if status == "matched" else "",
                "recommended_ra_game_id": cfg["ra_game_id"] if status == "unmatched" else "",
                "local_ra_hash": content_hash, "disc_id_conflict": "NO",
            })
    return path


@pytest.mark.parametrize("profile", ["driver", "gt2-simulation"])
def test_promote_verified_pair_retains_unmatched_old_pair(tmp_path, profile):
    cfg, hash_impl = fixture_pairs(tmp_path, profile)
    journal = tmp_path / (profile + ".json")
    audit = make_audit(tmp_path, cfg)
    with patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        op = resolver.inspect(tmp_path, Path("/unused/RAHasher"), profile, audit)
        assert op is not None
        assert op["verified_hash"] == cfg["verified"]
        resolver.apply(tmp_path, Path("/unused/RAHasher"), journal,
                       (op["verified_hash"], op["unmatched_hash"]), profile, audit)
        assert (tmp_path / "iso" / (cfg["target"] + ".bin")).read_bytes() == b"verified"
        assert (tmp_path / "iso" / ("OLD_" + cfg["target"] + ".bin")).read_bytes() == b"unmatched"
        for basename in (cfg["target"], "OLD_" + cfg["target"]):
            cue = tmp_path / "iso" / (basename + ".cue")
            assert ('FILE "' + basename + '.bin"') in cue.read_text(encoding="utf-8")
        assert journal.exists()
        resolver.verify_completed(journal, tmp_path, Path("/unused/RAHasher"))


@pytest.mark.parametrize("profile", ["driver", "gt2-simulation"])
def test_refuses_wrong_disc_identity(tmp_path, profile):
    cfg, hash_impl = fixture_pairs(tmp_path, profile)
    with patch("report_ps1_audit.disc_serial", side_effect=[cfg["serial"], "SLUS-99999"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        with pytest.raises(RuntimeError, match="serial"):
            resolver.inspect(tmp_path, Path("/unused/RAHasher"), profile)


def test_refuses_existing_old_backup(tmp_path):
    cfg, hash_impl = fixture_pairs(tmp_path, "driver")
    (tmp_path / "iso" / ("OLD_" + cfg["target"] + ".bin")).write_bytes(b"existing")
    with patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        with pytest.raises(RuntimeError, match="OLD_ backup"):
            resolver.inspect(tmp_path, Path("/unused/RAHasher"), "driver")


def test_gt2_arcade_does_not_qualify_as_simulation(tmp_path):
    cfg, hash_impl = fixture_pairs(tmp_path, "gt2-simulation")
    # On-disc serial must match the exact Simulation disc, not just game RA ID.
    with patch("report_ps1_audit.disc_serial", return_value="SCUS-94455"), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        with pytest.raises(RuntimeError, match="serial"):
            resolver.inspect(tmp_path, Path("/unused/RAHasher"), "gt2-simulation")


def test_refuses_stale_ra_audit_hash(tmp_path):
    cfg, hash_impl = fixture_pairs(tmp_path, "driver")
    audit = make_audit(tmp_path, cfg)
    raw = audit.read_text(encoding="utf-8").replace("f" * 32, "0" * 32)
    audit.write_text(raw, encoding="utf-8")
    with patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        with pytest.raises(RuntimeError, match="RA audit"):
            resolver.inspect(tmp_path, Path("/unused/RAHasher"), "driver", audit)


def test_refuses_unverified_source_hash(tmp_path):
    cfg, hash_impl = fixture_pairs(tmp_path, "gt2-simulation")
    audit = make_audit(tmp_path, cfg)
    (tmp_path / "iso" / (cfg["source"] + ".bin")).write_bytes(b"unmatched")
    with patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        with pytest.raises(RuntimeError, match="Verified hash"):
            resolver.inspect(tmp_path, Path("/unused/RAHasher"), "gt2-simulation", audit)


def test_generic_discovery_finds_verified_same_disc_collision(tmp_path):
    import csv
    folder = tmp_path / "iso"
    folder.mkdir()
    source = "Doom (USA) (Rev 1)"
    target = "Doom [SLUS-00077]"
    ra_path = tmp_path / "ra.csv"
    audit_path = tmp_path / "ps1.csv"
    ra_fields = ["platform", "path", "status", "local_serial",
                 "ra_game_id", "recommended_ra_game_id",
                 "local_ra_hash", "disc_id_conflict"]
    with ra_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=ra_fields)
        writer.writeheader()
        writer.writerow(dict(platform="Sony PlayStation", path="iso/" + source + ".cue",
                             status="matched", local_serial="SLUS-00077",
                             ra_game_id="11256", local_ra_hash="a" * 32))
        writer.writerow(dict(platform="Sony PlayStation", path="iso/" + target + ".cue",
                             status="unmatched", local_serial="SLUS-00077",
                             recommended_ra_game_id="11256", local_ra_hash="b" * 32))
    fields = ["relative_cue", "proposed_cue", "issues",
              "internal_serial", "selected_serial"]
    with audit_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(relative_cue="iso/" + source + ".cue",
                             proposed_cue="iso/" + target + ".cue",
                             issues="CUE_DESTINATION_EXISTS | BIN_DESTINATION_EXISTS",
                             internal_serial="SLUS-00077", selected_serial="SLUS-00077"))
    profiles = resolver.discover(ra_path, audit_path)
    assert len(profiles) == 1
    assert next(iter(profiles.values()))["target"] == target


def test_generic_discovery_rejects_different_disc_serial(tmp_path):
    import csv
    ra_path = tmp_path / "ra.csv"
    audit_path = tmp_path / "ps1.csv"
    with ra_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["platform", "path", "status",
                                "local_serial", "ra_game_id",
                                "recommended_ra_game_id", "local_ra_hash"])
        writer.writeheader()
        writer.writerow(dict(platform="Sony PlayStation", path="iso/Simulation.cue",
                             status="matched", local_serial="SCUS-94488",
                             ra_game_id="11278", local_ra_hash="a" * 32))
        writer.writerow(dict(platform="Sony PlayStation", path="iso/Arcade.cue",
                             status="unmatched", local_serial="SCUS-94455",
                             recommended_ra_game_id="11278", local_ra_hash="b" * 32))
    with audit_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["relative_cue", "proposed_cue",
                                                 "issues", "internal_serial",
                                                 "selected_serial"])
        writer.writeheader()
        writer.writerow(dict(relative_cue="iso/Simulation.cue",
                             proposed_cue="iso/Arcade.cue",
                             issues="CUE_DESTINATION_EXISTS | BIN_DESTINATION_EXISTS",
                             internal_serial="SCUS-94488", selected_serial="SCUS-94488"))
    assert resolver.discover(ra_path, audit_path) == {}


def test_generic_discovery_finds_identical_verified_collision(tmp_path):
    import csv
    ra = tmp_path / "ra.csv"
    files = tmp_path / "ps1.csv"
    cols = ["platform", "path", "status", "local_serial",
            "ra_game_id", "recommended_ra_game_id", "local_ra_hash"]
    with ra.open("w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=cols)
        w.writeheader()
        for stem in ("LEGO Rock Raiders (USA)", "LEGO Rock Raiders [SLUS-00937]"):
            w.writerow(dict(platform="Sony PlayStation", path="iso/" + stem + ".cue",
                            status="matched", local_serial="SLUS-00937",
                            ra_game_id="17043", local_ra_hash="a" * 32))
    with files.open("w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=["relative_cue", "proposed_cue",
                           "issues", "internal_serial", "selected_serial"])
        w.writeheader()
        w.writerow(dict(relative_cue="iso/LEGO Rock Raiders (USA).cue",
                        proposed_cue="iso/LEGO Rock Raiders [SLUS-00937].cue",
                        issues="CUE_DESTINATION_EXISTS | BIN_DESTINATION_EXISTS",
                        internal_serial="SLUS-00937", selected_serial="SLUS-00937"))
    plans = resolver.discover(ra, files)
    assert len(plans) == 1
    assert next(iter(plans.values()))["identical"] is True


def test_same_ra_identity_archives_extra_and_keeps_canonical(tmp_path):
    cfg, _ = fixture_pairs(tmp_path, "driver")
    cfg = dict(cfg, identical=True, archive_source=True, unmatched="f" * 32)
    journal = tmp_path / "archive.json"
    def hash_impl(_hasher, path):
        return cfg["verified"] if Path(path).read_bytes() == b"verified" else "f" * 32
    with patch.dict(resolver.PROFILES, {"duplicate-test": cfg}), \
         patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl), \
         patch.object(resolver, "audit_pair"):
        op = resolver.inspect(tmp_path, Path("/unused/RAHasher"), "duplicate-test")
        resolver.apply(tmp_path, Path("/unused/RAHasher"), journal,
                       (op["verified_hash"], op["unmatched_hash"]), "duplicate-test")
        directory = tmp_path / "iso"
        assert (directory / (cfg["target"] + ".bin")).read_bytes() == b"unmatched"
        assert (directory / ("OLD_" + cfg["source"] + ".bin")).read_bytes() == b"verified"
        assert not (directory / (cfg["source"] + ".cue")).exists()
        assert 'FILE "OLD_' + cfg["source"] + '.bin"' in (
            directory / ("OLD_" + cfg["source"] + ".cue")).read_text()
        resolver.verify_completed(journal, tmp_path, Path("/unused/RAHasher"))



def test_generic_discovery_no_set_identical_copies(tmp_path):
    import csv
    raw = tmp_path / "ra.csv"
    audit = tmp_path / "ps1.csv"
    with raw.open("w", newline="") as out:
        fields = ["platform", "path", "status", "local_serial",
                  "no_set_ra_game_id", "local_ra_hash"]
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        for name in ("LEGO Island 2 (USA)", "LEGO Island 2 [SLUS-01246]"):
            w.writerow(dict(platform="Sony PlayStation", path="iso/" + name + ".cue",
                            status="unmatched", local_serial="SLUS-01246",
                            no_set_ra_game_id="13898", local_ra_hash="b" * 32))
    with audit.open("w", newline="") as out:
        fields = ["relative_cue", "proposed_cue", "issues",
                  "internal_serial", "selected_serial"]
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        w.writerow(dict(relative_cue="iso/LEGO Island 2 (USA).cue",
                        proposed_cue="iso/LEGO Island 2 [SLUS-01246].cue",
                        issues="CUE_DESTINATION_EXISTS | BIN_DESTINATION_EXISTS",
                        internal_serial="SLUS-01246", selected_serial="SLUS-01246"))
    plans = resolver.discover(raw, audit)
    assert len(plans) == 1
    assert next(iter(plans.values()))["identical"] is True


def test_kula_world_planner_overrides_wrong_gamedb_title(tmp_path):
    from report_ps1_audit import plan
    cue = tmp_path / "Kula World (Europe).cue"
    binary = tmp_path / "Kula World (Europe).bin"
    binary.write_bytes(b"test")
    cue.write_text('FILE "Kula World (Europe).bin" BINARY\n'
                   '  TRACK 01 MODE2/2352\n'
                   '    INDEX 01 00:00:00\n', encoding="utf-8")
    with patch("report_ps1_audit.disc_serial", return_value="SCES-01000"):
        rows = plan(tmp_path, {"SCES-01000": "PS One Kids Autumn 2000"})
    record = next(r for r in rows if r.get("relative_cue") == cue.name)
    assert record["proposed_cue"] == "Kula World [SCES-01000].cue"
    assert "TITLE_IDENTITY_CONFLICT" not in record["issues"]


def test_special_edition_collision_not_automatically_archived(tmp_path):
    import csv
    ra = tmp_path / "ra.csv"
    files = tmp_path / "ps1.csv"
    names = ("The Lost World Special Edition (USA)", "The Lost World [SLUS-00515]")
    with ra.open("w", newline="") as out:
        cols = ["platform", "path", "status", "local_serial", "ra_game_id", "local_ra_hash"]
        writer = csv.DictWriter(out, fieldnames=cols)
        writer.writeheader()
        for name in names:
            writer.writerow(dict(platform="Sony PlayStation", path="iso/" + name + ".cue",
                                 status="matched", local_serial="SLUS-00515",
                                 ra_game_id="14615", local_ra_hash="a" * 32))
    with files.open("w", newline="") as out:
        cols = ["relative_cue", "proposed_cue", "issues",
                "internal_serial", "selected_serial"]
        writer = csv.DictWriter(out, fieldnames=cols)
        writer.writeheader()
        writer.writerow(dict(relative_cue="iso/" + names[0] + ".cue",
                             proposed_cue="iso/" + names[1] + ".cue",
                             issues="CUE_DESTINATION_EXISTS | BIN_DESTINATION_EXISTS",
                             internal_serial="SLUS-00515", selected_serial="SLUS-00515"))
    assert resolver.discover(ra, files) == {}
