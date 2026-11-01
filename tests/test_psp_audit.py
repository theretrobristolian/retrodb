import struct
from report_psp_audit import inventory, normalise, parse_sfo, verify_hash


def test_psp_serial():
    assert normalise("ULUS10160") == "ULUS10160"
    assert normalise("ULUS-10160") == "ULUS10160"
    assert normalise("unknown") == ""


def test_sfo_identity():
    # Minimal valid SFO containing a DISC_ID string.
    key = b"DISC_ID\\0".replace(b"\\0", b"\\x00")
    value = b"ULUS10160\\x00".replace(b"\\x00", b"\x00")
    header = b"\x00PSF" + struct.pack("<IIII", 0x101, 36, 36+len(key), 1)
    index = struct.pack("<HHIII", 0, 0x0204, len(value), len(value), 0)
    result = parse_sfo(header + index + key + value)
    assert result["DISC_ID"] == "ULUS10160"


def test_read_only_inventory_records_unreadable_iso(tmp_path):
    root=tmp_path/"iso"
    root.mkdir()
    target=root/"Grand Theft Auto Vice City Stories [ULUS10160].iso"
    target.write_bytes(b"not a real ISO")
    (root/"OLD_Archive.iso").write_bytes(b"data")
    rows=inventory(root,{"ULUS10160":"Grand Theft Auto: Vice City Stories"})
    assert len(rows)==1
    assert rows[0]["status"]=="REVIEW_IDENTITY"
    assert "ISO metadata error" in rows[0]["reason"]
    assert rows[0]["ra_status"]=="NOT_CHECKED"
    assert target.read_bytes()==b"not a real ISO"


def test_hash_classification(tmp_path):
    # A fake executable isolates the parsing of RAHasher output.
    executable=tmp_path/"hasher"
    executable.write_text("#!/bin/sh\\necho 0123456789abcdef0123456789abcdef\\n".replace("\\n","\n"))
    executable.chmod(0o755)
    iso=tmp_path/"test.iso"
    iso.touch()
    lookup={"0123456789abcdef0123456789abcdef":("42","Example",7)}
    status,hash_value,game_id,title,error=verify_hash(executable,iso,lookup)
    assert (status,game_id,title,error)==("SUPPORTED","42","Example","")
