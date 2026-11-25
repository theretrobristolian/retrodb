# Nintendo Wii collection support

RetroDB indexes Wii images on the **existing read-only RetroNAS mount**, not
a separate SMB share or a new writable mount.

## Folder layout

Expected path, relative to the existing RetroNAS mount:

```text
roms/nintendo/wii/
└── Attack of the Movies 3D [S3AE5G]/
    └── S3AE5G.wbfs
```

The folder's final `[DISC_ID]` and the image basename must agree on a
six-character alphanumeric Wii disc ID. `.wbfs` is the preferred format;
`.iso` and `.rvz` files with the same layout can also be inventoried.
Split `.wbf1` sidecars, text files and non-game data are not separate games.
The scanner **never renames, rewrites, extracts or hashes the contents of the
WBFS file**. Its name and ID are *evidence of identity*, not proof the disc
dump is valid.

A Wii disc ID is not a RetroAchievements hash. An exact title match in the
official Wii catalogue is labelled **TITLE_CANDIDATE**, never EXACT_RA.
A game lacking a title match is not assumed unsupported. Neither case earns
a verified achievement badge. True Wii RA content hashing involves a
specialised disc-partition hashing algorithm and must be implemented and
tested separately before assigning verified RA game IDs.

## How to run

After updating and deploying RetroDB, use the existing `retrodb` command.
The normal **Audit games** workflow includes **Nintendo Wii** as its last
stage when `roms/nintendo/wii` exists. Wii and 32X are intentionally not
duplicated under More options; both run with the full audit.

During the audit RetroDB calls its existing cache-first provider for
RetroAchievements system **19 (Wii)** and stores the response at:

```text
/var/cache/retrodb/providers/retroachievements/wii.json
```

Use `ra-sync-wii --force` to bypass the provider's normal cache lifetime,
for example:

```bash
sudo -u retrodb env PYTHONPATH=/opt/retrodb/backend \
    /opt/retrodb/.venv/bin/python -m retrodb.cli \
    --env-file /etc/retrodb/retrodb.env ra-sync-wii --force
```

The audit writes a CSV to `~/retrodb-exports/RetroDB-Nintendo-Wii-Audit.csv`
and syncs it into RetroDB's existing PostgreSQL library. Visit:

- `/consoles/wii` for the Nintendo Wii overview
- `/library/wii` for indexed game entries
- `/consoles` for all available systems

The sync is isolated to the Wii platform; it does not mark Sony or 32X
files missing, modify ROMs or change mounts. It uses the same `retronas`
collection source as other platforms.

## Optional GameTDB names

RetroDB caches GameTDB's public English Wii disc-ID title list (up to 30 days)
when auditing or previewing Wii renames, under
`/var/cache/retrodb/providers/gametdb/wii-titles.txt`.
If GameTDB is unavailable, an existing cache is reused or the scanner
falls back to folder-title evidence. A pre-existing GameTDB XML catalogue
is also accepted at:

```text
/var/cache/retrodb/providers/gametdb/wii.xml
```

RetroDB will then prefer titles matched by the **exact six-character disc
ID**. It does not download arbitrary third-party metadata, alter release
identities or require GameTDB credentials. Missing metadata is normal;
RetroDB falls back to the title already in the folder name.

## Planned verification phase

1. Verify supported `.wbfs` content hashing against the official Wii
   RetroAchievements hashing rules, with fixtures and expected hashes.
2. Compare those *verified* hashes with registered Wii RA hashes.
3. Grant a verified badge only after the exact digest is recognised in the
   official catalogue and the registered game has published achievements.
4. Keep unsupported, uncertain, different-region and duplicate dumps visible
   without falsely claiming they are verified.

## Wii folder naming (Rename games → Nintendo Wii)

The rename preserves the Wii loader layout:

```text
Game Title [DISC_ID]/DISC_ID.wbfs
```

It renames **only the containing folder**. WBFS, ISO, RVZ and sidecar
contents are unchanged. The best title source is GameTDB matched to the
**exact six-character Wii disc ID**. If a title is unavailable, the
tool only proposes conservative ALL-CAPS formatting. It preserves
existing mixed-case titles instead of guessing expansions of abbreviations.

For example, `SUPER MONKEY BALL BANANA BLITZ [RSME8P]` becomes
`Super Monkey Ball Banana Blitz [RSME8P]`.

The tool previews all proposals, requires the exact `RENAME WII` phrase,
then uses a temporary writable SMB mount (never the normal read-only
mount). It refuses collisions and ambiguous images, and journals all
operations under `~/retrodb-exports/wii-rename-journals/`.
Case-only corrections (for example `TRAUMA TEAM` to `Trauma Team`) use a
unique intermediate folder on the same SMB share. The preflight checks
the real directory entries rather than relying on `samefile()` inode
comparisons, which may be unreliable on CIFS aliases. Its intermediate
name is recorded in the journal before the move, so an interrupted rename
can be located and recovered without touching WBFS contents.
On success RetroDB re-audits Wii and refreshes database paths.
Inspect interrupted rename journals and temporary folders before retrying.

A folder name correction never establishes RA content-hash compatibility.

## Loose Wii ISO intake (Rename games → Nintendo Wii)

Drop a full Wii ISO **temporarily** into `roms/nintendo/wii/` (the Wii
collection root), with any basename. The existing Wii rename preview reads
the six-character disc ID from offset 0 and Wii disc magic at 0x18. This
quick header check **does not** claim the ISO is a verified disc dump or
a RetroAchievements hash match.

An eligible ISO is moved, **without rewriting its bytes**, to
`GameTDB Title [DISC_ID]/DISC_ID.iso`. If exactly one folder already ends
in the same `[DISC_ID]`, that existing folder is reused regardless of its
current title. When the folder doesn't exist, an exact GameTDB disc-ID title
is mandatory; missing metadata requires manual review. An existing ISO,
ambiguous folders, wrong magic/ID, unsafe path or changed preview blocks
automatic import. Two incoming files aiming at one ISO target are refused.

Example:

```text
roms/nintendo/wii/
├── my_mario_kart.iso
└── Mario Kart Wii [RMCP01]/
    └── RMCP01.wbfs

# After confirmed import:
roms/nintendo/wii/
└── Mario Kart Wii [RMCP01]/
    ├── RMCP01.wbfs
    └── RMCP01.iso
```

The menu previews both folder corrections and loose ISO imports and requires
`RENAME WII` to proceed. The importer records its own write-ahead journal
(`import-*.json`) under
`~/retrodb-exports/wii-rename-journals/` and blocks subsequent imports
when an import journal is incomplete. Import occurs first, then eligible
folder title corrections, both on the temporary writable SMB mount. An
interrupted move must be inspected/recovered before retrying.

The read-only audit accepts several images for the same ID **only when each
has a distinct extension** (e.g. one WBFS and one ISO), and publishes one
file record per format. No RA badge is granted from header identification
alone. Full disc hashing remains optional and separate.
