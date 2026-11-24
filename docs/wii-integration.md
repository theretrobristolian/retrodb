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
The normal **Audit games** workflow now includes **Nintendo Wii** as its last
stage when `roms/nintendo/wii` exists. Alternatively, choose **More options
→ 12 Audit Nintendo Wii** for a standalone, read-only run.

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

If an administrator has obtained a Wii title catalogue in a compatible
GameTDB XML format, it may be placed at:

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
