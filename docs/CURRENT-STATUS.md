# RetroDB — current project status

Updated: 26 October 2026. **This page takes precedence over dated development notes elsewhere in the repository.** Deployment-specific configuration on the actual Debian VM must still be checked before changing a running service.

## Recent PS1/PS2 management improvements (26 October 2026)

- Interactive `retrodb` menu supports one-at-a-time RetroAchievements patch selection. PS1 verified CUE/BIN results can be deployed to RetroNAS after explicit confirmation, using a temporary RW mount, `OLD_` checksum-verified backups and a deployment journal; ordinary auditing retains its read-only mount. PS2's earlier network deployment code has not yet been integrated into the current one-game menu path.
- PS1 CUE/BIN paired rename previews use internal disc serials, GameDB titles, collision checks and recovery journals. The explicitly reviewed Metal Gear Solid Disc 1 filename serial correction is supported; ambiguous disc identities remain blocked.
- Friendly PS1 web labels preserve known `(Disc N)` suffixes; reviewed disc mappings include four Geppy-X discs. Revision suffixes are suppressed from display titles. This is not yet a comprehensive multi-disc catalogue.
- These latest code changes have been committed on `feature/ps1-cue-audit`; they should be validated on the VM before merging or tagging a release.

## Patch source checksum caching (26 October 2026)

Patch-preparation Stage 7 now persists calculated MD5, CRC32 and RetroAchievements source hashes in `/var/lib/retrodb/patches/source-digest-cache.json` (under the configured patch workspace). Previously digests were cached only within a single run, so each audit could reread multiple gigabytes from RetroNAS. Cache entries are reused only while the path, file size, modification time, change time and file identity agree; RA hashes also include the hasher executable signature, and PS1 CUE hashes include every referenced track's stat. The first audit after this update will still read uncached files; **later audits should be significantly quicker** if files are unchanged. This is a metadata-based cache, not a cryptographic proof that an adversarially replaced file is unchanged. For an independent fresh verification, remove the digest cache file and rerun a read-only audit.

Stage 7's terminal output reports **digest cache hits and new reads**, and distinguishes patch sources lacking an expected checksum from actual checksum mismatches. Lack of checksum does not make a patch safe to apply; the normal reviewed/verified patching constraints remain in place. This change does not modify the collection, patches, or ROM images. Runtime timing and cache hits have not yet been verified on the deployed VM.

## Supported and working

- Debian 13 VM, PostgreSQL, systemd RetroDB API and responsive web interface.
- PS1/PS2 collection indexing and serial-based GameDB title lookup.
- RetroAchievements matching, artwork caching, trophy status and profile-linked UI.
- LizardByte GameDB/IGDB enrichment for **game modes, ratings, genres and release years**, with conservative matching and manual-review markers.
- Main library columns: **Game, Disc ID, Region, RetroAchievements**. Region flags are *hints* based on recognised PS1/PS2 serial prefixes, not verified worldwide distribution.
- xeRAbora server-side v1.0.0 web UI and linked-player switching verified on the owner's Debian VM.

## Not yet fully validated / deliberately not implemented

- **xeRAbora v1.0.0 on the physical PS2** (console-side network handshake, game detection and achievement unlocks): pending a fresh console test. The server has an official v1.0.0 `OPL-RA.ELF` verified by SHA-256, but that does not establish what is installed on the console.
- Exact local player counts, mouse, GunCon, keyboard, multitap and other back-of-box capabilities **are not supplied reliably** by the current metadata integrations. An IGDB "multiplayer" category is not proof of online play on a specific disc.
- Ambiguous GameDB matches are held for review; do not auto-assign game identity based on names alone.
- A clean installation of all components on a brand-new VM has not been confirmed end-to-end.
- The latest code may be newer than the installed VM until the owner pulls and deploys it.

## Main development and deploy workflow

The intended release branch is **main**. Active PS1 auditing, patching and naming development is currently on **`feature/ps1-cue-audit`**; do not switch to `main` before pulling changes from that branch. Older xeRAbora feature branches are separate. For an ordinary RetroDB web/backend update:

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
curl -fsS http://127.0.0.1:8000/health
```

The xeRAbora service and PS2 loader are **separate components**. Updating the RetroDB application does not implicitly replace the manual v1.0.0 Linux xeRAbora executable or the physical PS2's ELF. Verify versions and preserve working binaries/profiles before making xeRAbora changes. See [xeRAbora setup](../integrations/xerabora/README.md).

## Version tags

As of this review, no release tags were confirmed. When creating the **first project tag**, use a provisional project-specific tag such as `retrodb-v0.1.0` on the current tested `main` commit. **Do not confuse this with upstream xeRAbora v1.0.0.** A tag should mean a known milestone and record which tests passed, not imply RetroDB is production-stable.

To create a signed-off annotated tag **after validating your VM**:

```bash
cd ~/retrodb
git pull --ff-only
git status --short
git tag -a retrodb-v0.1.0 -m "RetroDB v0.1.0: PS1/PS2 catalogue and web UI milestone"
git push origin retrodb-v0.1.0
```

The push requires GitHub authentication (SSH or a token); account passwords do not work over HTTPS. Prefer a GitHub release entry describing any known limitations. **Do not retag or move published releases**, and do not create a tag until choosing the desired tested commit.

## Documentation hygiene

The lengthy historical logs at the top of root and server READMEs were accumulated during iterative development and can mention superseded defaults, old upgrade paths or exploratory designs. Treat them as historical records, **not** authoritative installation instructions. New canonical instructions should be maintained in this file and in the dedicated installation guides. Existing configurations are not automatically rewritten by README edits.
