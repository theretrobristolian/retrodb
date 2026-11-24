"""Keep normal audits concise without weakening patch verification or CSV reports."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"


def test_full_audit_skips_expensive_patch_prepare():
    text = (SERVER / "manager.sh").read_text(encoding="utf-8")
    audit = text.split("\naudit() {", 1)[1].split("\npatch_audit() {", 1)[0]
    patch_audit = text.split("\npatch_audit() {", 1)[1].split("\npatch_download() {", 1)[0]
    patch_apply = text.split("\npatch_apply() {", 1)[1].split("\ndeploy_ps1_patch() {", 1)[0]
    assert 'step "7/10" "Check cached patch packages' in audit
    assert "patch-prepare" not in patch_audit
    assert "patch-download" in patch_audit
    assert "patch-prepare" in patch_apply
    assert 'local prep_arg="-"' in text
    assert '--quiet --root "$ps3_iso"' in text


def test_ps3_quiet_audit_still_writes_full_csv_and_keeps_preview_verbose(tmp_path):
    iso_root = tmp_path / "isos"
    iso_root.mkdir()
    # Existing disc ID in filename means we do not need an expensive ISO inspection.
    for name in ("Already Named [BLES00246].iso",
                 "Another Game [BCES00141].iso",
                 "Wrong Title [BLUS30115].iso"):
        (iso_root / name).write_bytes(b"test")
    titles = tmp_path / "titles.json"
    titles.write_text('{"BLES00246":"Already Named","BCES00141":"Another Game","BLUS30115":"Correct Title"}')
    command = [sys.executable, str(SERVER / "ps3_rename.py"),
               "audit", "--root", str(iso_root), "--catalogue", str(titles),
               "--output", str(tmp_path / "audit.csv")]
    loud = subprocess.run(command, capture_output=True, text=True, check=True)
    quiet = subprocess.run(command + ["--quiet"], capture_output=True, text=True, check=True)
    assert (tmp_path / "audit.csv").is_file()
    import csv
    with (tmp_path / "audit.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3
    assert "Already Named [BLES00246].iso" in loud.stdout
    assert "VALID" in loud.stdout
    assert quiet.stdout.count("Already Named [BLES00246].iso") <= loud.stdout.count("Already Named [BLES00246].iso")
    assert "[PS3]" in quiet.stdout
    assert "Audited 3 ISOs" in quiet.stdout
