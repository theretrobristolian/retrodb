# RetroNAS collection scanning

RetroDB connects to RetroNAS through a deliberately read-only SMB mount. It never needs RetroNAS root or administrator access.

## Supported layout

RetroNAS exposes its generic collection under the top-level `retronas` share. RetroDB initially inventories:

- `roms/sony/playstation1`
- `roms/sony/playstation2`

These are RetroNAS's canonical generic paths. Symlinked alternative layouts are not traversed, avoiding duplicate inventory records.

## Configure the connection

First install the CIFS client dependency and deploy the current application:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

Then run the guided setup:

```bash
sudo bash server/configure-retronas.sh
```

It asks for the RetroNAS DNS name/IP, SMB share name, username and password. The defaults are share `retronas` and username `pi`; use the values configured on your RetroNAS system.

The password is entered invisibly and stored only in `/etc/retrodb/retronas.credentials`, owned by root with mode `0600`. It never enters Git, the database, a command line or normal logs.

The resulting systemd mount uses SMB 3.1.1 and is forced read-only with `nosuid`, `nodev` and `noexec`. It mounts at `/mnt/retrodb-retronas` and reconnects after reboot.

## Run the inventory

```bash
sudo bash server/retronas.sh scan
```

The inventory reports the exact mount and platform paths, then breaks results down by platform, top-level media folder (for example PS2 `cd` and `dvd`) and file format. Skipped extensions are itemised. Counts are explicitly files rather than games, because a PS1 BIN/CUE pair is two files representing one disc.

It stores relative path, filename, extension, size, modification time, platform, last-seen time and missing state. It recognises common PS1/PS2 image formats and does not alter or upload collection files.

Other operations:

```bash
sudo bash server/retronas.sh status
sudo bash server/retronas.sh unmount
sudo bash server/retronas.sh mount
```

## Identification and hash matching

The inventory itself counts and records files; the subsequent **implemented** matching stage calculates platform-specific RetroAchievements hashes and compares them with the cached provider catalogue. Whole-file SHA/MD5 values are not a substitute for RetroAchievements disc hashing.

## Check RetroAchievements compatibility

RetroDB uses the rcheevos-compatible RAHasher engine, pinned to version 1.8.3 and verified against its published SHA-256 digest before installation. It hashes the PS1 CUE entry points and PS2 ISO images using the platform-specific RetroAchievements algorithm.

```bash
sudo bash server/retronas.sh match
```

Progress is checkpointed after every disc. Re-running the command reuses stored hashes, including after interruption, while still comparing them with the latest cached catalogue. A changed collection file has its stored result cleared automatically during the next inventory scan.

The summary reports compatible, unmatched and failed images per platform. Full results are written to:

```text
/var/lib/retrodb/reports/retroachievements-compatibility.csv
```

View it with `sudo column -s, -t < /var/lib/retrodb/reports/retroachievements-compatibility.csv | less -S`, or copy it to an administrator-owned location for spreadsheet analysis.

## Understanding release recommendations

The CSV includes the local disc serial and inferred region where the filename contains a standard PlayStation product code. For example, `SLUS`/ `SCUS` indicates USA and `SLES`/ `SCES` indicates Europe.

For an unmatched hash, RetroDB conservatively compares the cleaned local filename with the achievement-enabled RA catalogue. Exact and unambiguous high-confidence title matches receive:

- the suggested RA game ID and title;
- RA's accepted file names, including region/revision/disc text;
- every accepted RA hash for that game;
- labels supplied by RA, such as `nointro`.

Ambiguous names are not guessed. The recommendation is a research aid, not proof that an unrelated download is correct. Only obtain images from media you are legally entitled to use, and verify a candidate with RAHasher rather than relying on a conventional whole-file checksum.

The per-game metadata is cached for 180 days. Re-run the matcher to regenerate the enriched report:

```bash
sudo bash server/retronas.sh match
```

## Release preference and ambiguous titles

For TV-connected PlayStation systems, RetroDB ranks supported releases using RetroAchievements' documented policy:

1. clean NTSC USA releases;
2. clean NTSC Japan releases when no USA release is supported, commonly Japan-exclusive games;
3. PAL Europe releases when they are the supported regional option, commonly Europe-exclusive games;
4. the latest supported revision within the preferred region.

The report's `preferred_release_name`, `preferred_region`, `preferred_ra_hash` and `release_guidance` columns turn the complete accepted-file list into one actionable recommendation. This selection only considers files explicitly returned by RetroAchievements; it does not invent an unsupported regional release.

Title matching combines punctuation/diacritic normalization, article handling, word-order comparison and strict sequel/version safeguards. When the best result is not sufficiently distinct, RetroDB leaves the recommendation blank and lists up to three scored possibilities in `alternative_candidates` for manual review.

## Prepare RetroAchievements patches

After generating the compatibility report, create the patch workspace and
per-game instructions:

```bash
sudo bash server/retronas.sh patch-plan
```

This creates `/var/lib/retrodb/patches` with manifests and READMEs for releases
labelled `rapatches` by RetroAchievements. Patch URLs are accepted only from
RetroAchievements or GitHub hosts. The command does not download ROMs, copy
collection files or modify the read-only RetroNAS mount.

Download and safely extract the official patch packages:

```bash
sudo bash server/retronas.sh patch-download
```

Downloads are limited to trusted RetroAchievements/GitHub hosts and 64 MiB per
archive. ZIP traversal, excessive file counts and expanded archives over 256
MiB are rejected. Results, SHA-256 checksums and discovered instruction files
are recorded in `/var/lib/retrodb/patches/patch-download.json`. Existing
downloads are reused, so the command is safe to repeat.

Place clean source images you own in `/var/lib/retrodb/patches/incoming`, then
inspect them with:

```bash
sudo bash server/retronas.sh patch-prepare
```

Candidate images are checked using RAHasher. Detailed results are written to
`/var/lib/retrodb/patches/patch-prepare.json`. A candidate still requires the
source checksum from the patch's supplied README before patching; it is only
reported as already verified when its RA hash equals the expected patched hash.

`patch-prepare` parses the supplied README and verifies its required RAHash,
MD5 or CRC32 against both the corresponding file on the read-only RetroNAS
mount and any image placed in `incoming`. For PlayStation CUE sheets, raw-file
checksums are calculated against the referenced BIN. No collection file is
copied or changed during preparation.

Apply patches only to sources verified by `patch-prepare`:

```bash
sudo bash server/retronas.sh patch-apply
```

The command uses the current root-level XDelta patch, ignoring archived copies
under `Old Patch`. It creates one temporary output at a time, verifies the
result with RAHasher and retains only successful results under
`/var/lib/retrodb/patches/verified`. Failed outputs are deleted and recorded in
`patch-apply.json`. RetroNAS originals remain read-only and unchanged.


## Current end-to-end audit and controlled NAS writes

The interactive entry point is `retrodb` (or `bash server/manager.sh`) as the ordinary Linux user.

| Main menu | Operation |
|---|---|
| 1 | Audit PS1 and PS2 through the read-only RetroNAS mount, then export compatibility reports and rename proposals |
| 2 | Patch **one** RA game ID: check the original source checksum; reuse a verified existing local output or create one; offer **PS1** network deployment with a separate `DEPLOY-<RA_GAME_ID>` confirmation |
| 3 | Preview and confirm PS1 paired BIN/CUE renames or PS2 OPL renames |
| 4 | More options (including exports, downloads, recovery tools and status) |

### PS1 patch deployment and `OLD_` backups

Local patching alone **never writes to RetroNAS**. A separate deployment confirmation within menu 2 permits temporary network write access for a single PS1 game. The normal audit share remains mounted read-only at `/mnt/retrodb-retronas`; a temporary SMB mount at `/mnt/retrodb-retronas-pilot-rw` is created only for confirmed write operations and unmounted afterward.

The PS1 deployment reads `/var/lib/retrodb/patches/patch-apply.json` and requires an existing `patched-and-verified` result with the expected 32-character RA hash. It copies the **unmodified patched CUE and BIN files under their verified patch filenames**, checks staged SHA-256 checksums and RetroAchievements hash, creates `OLD_` backups of the original CUE and BIN, checks backup SHA-256 checksums, publishes the new files and verifies their RA hash once more. After successful verification, the former active filenames are retired; the `OLD_` copies remain. The original CUE's track layout is not rewritten.

An existing `OLD_` backup or destination collision blocks deployment. Operations are journalled under `~/retrodb-exports/opl-rename-journals/ps1-deploy-*.json`. If any step fails, **check the journal and the NAS files before retrying**, especially when a write may have started. Do not delete backups or temporary files while investigating.

PS2's historical `server/patch_retronas.py` mechanism also uses `OLD_` backups and checksum verification, but **the current interactive menu 2 does not automatically deploy PS2 patches to the NAS**. Do not assume the PS1 deployment process applies to PS2 ISO images.

### PS1 filenames, paired renames and multiple discs

Menu 3's PS1 workflow audits CUE references, reads an internal serial from the corresponding BIN when possible, uses cached GameDB titles, and previews changes before a confirmed rename of eligible BIN/CUE pairs. It does not alter BIN data. Destination collisions, unverifiable serials and ambiguous multi-file track layouts require review; the rename executor records a local journal before modifying filenames or CUE references.

Friendly titles preserve `(Disc N)` when disc numbering is independently supported by reviewed serial mappings or an existing per-disc filename. Reviewed examples include Metal Gear Solid (two discs) and Geppy-X (four discs, serials `SLPS-01995` through `SLPS-01998`). Do **not** infer disc order from sorting files or from a shared RetroAchievements game title. Unknown multi-disc identities remain manual-review work. Display names omit revision suffixes such as `(Rev 1)`, without claiming those revisions are identical for RA compatibility.

After any confirmed patch deployment or rename, run menu 1 again to refresh the inventory and reports.
