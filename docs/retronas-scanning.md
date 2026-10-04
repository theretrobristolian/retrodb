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

## Next identification stage

A later scanner stage will calculate the platform-specific RetroAchievements hashes and compare them with the cached provider catalogue. Whole-file SHA/MD5 values are not a substitute for RetroAchievements disc hashing, so this inventory deliberately does not claim compatibility yet.

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

Place clean source images you own in `/var/lib/retrodb/patches/incoming`, then
inspect them with:

```bash
sudo bash server/retronas.sh patch-prepare
```

Candidate images are checked using RAHasher. Detailed results are written to
`/var/lib/retrodb/patches/patch-prepare.json`. A candidate still requires the
source checksum from the patch's supplied README before patching; it is only
reported as already verified when its RA hash equals the expected patched hash.
