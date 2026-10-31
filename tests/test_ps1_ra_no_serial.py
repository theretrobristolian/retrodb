import csv
from pathlib import Path
from ps1_ra_no_serial import proposed, RELEASES


def test_three_matched_calamity_pairs_are_proposed(tmp_path):
    root=tmp_path/"collection"
    folder=root/"iso"
    folder.mkdir(parents=True)
    audit=tmp_path/"ra.csv"
    rows=[]
    for game_id,(source,target,digest) in RELEASES.items():
        (folder/(source+".bin")).write_bytes(b"test")
        (folder/(source+".cue")).write_text('FILE "'+source+'.bin" BINARY\n  TRACK 01 MODE2/2352\n',encoding="utf-8")
        rows.append({"platform":"Sony PlayStation","status":"no_set","ra_game_id":game_id,
                     "local_ra_hash":digest,"path":"iso/"+source+".cue"})
    with audit.open("w",newline="") as h:
        writer=csv.DictWriter(h,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    got=proposed(root,audit)
    assert len(got)==3
    # Never invent an SCUS/SLUS product serial for these special releases.
    assert all("[RA-" in row[4].stem for row in got)
    (folder/(RELEASES["15631"][1]+".cue")).write_text("existing")
    assert len(proposed(root,audit))==2
    rows[1]["status"]="unmatched"
    with audit.open("w",newline="") as h:
        writer=csv.DictWriter(h,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    assert len(proposed(root,audit))==1
