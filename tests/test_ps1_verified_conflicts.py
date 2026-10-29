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


@pytest.mark.parametrize("profile", ["driver", "gt2-simulation"])
def test_promote_verified_pair_retains_unmatched_old_pair(tmp_path, profile):
    cfg, hash_impl = fixture_pairs(tmp_path, profile)
    journal = tmp_path / (profile + ".json")
    with patch("report_ps1_audit.disc_serial", return_value=cfg["serial"]), \
         patch.object(resolver, "ra_hash", side_effect=hash_impl):
        op = resolver.inspect(tmp_path, Path("/unused/RAHasher"), profile)
        assert op is not None
        assert op["verified_hash"] == cfg["verified"]
        resolver.apply(tmp_path, Path("/unused/RAHasher"), journal,
                       (op["verified_hash"], op["unmatched_hash"]), profile)
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
