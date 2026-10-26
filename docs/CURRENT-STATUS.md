# RetroDB — current project status

Updated: 26 October 2026. **This page takes precedence over dated development notes elsewhere in the repository.** Deployment-specific configuration on the actual Debian VM must still be checked before changing a running service.

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

The only maintained branch is **main**. Do not use the retired xeRAbora feature branches. For an ordinary RetroDB web/backend update:

```bash
cd ~/retrodb
git switch main
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
git switch main && git pull --ff-only
git status --short
git tag -a retrodb-v0.1.0 -m "RetroDB v0.1.0: PS1/PS2 catalogue and web UI milestone"
git push origin retrodb-v0.1.0
```

The push requires GitHub authentication (SSH or a token); account passwords do not work over HTTPS. Prefer a GitHub release entry describing any known limitations. **Do not retag or move published releases**, and do not create a tag until choosing the desired tested commit.

## Documentation hygiene

The lengthy historical logs at the top of root and server READMEs were accumulated during iterative development and can mention superseded defaults, old upgrade paths or exploratory designs. Treat them as historical records, **not** authoritative installation instructions. New canonical instructions should be maintained in this file and in the dedicated installation guides. Existing configurations are not automatically rewritten by README edits.
