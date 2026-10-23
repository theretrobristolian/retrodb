# Server build

This directory contains standalone Linux host provisioning for RetroDB.

## Supported targets

- Debian Stable — primary
- Ubuntu Server LTS — secondary

The bootstrap requires systemd and APT. RetroNAS follows the same broad Debian-family, Bash and Ansible model, keeping a future integration path straightforward.

## Prepare a minimal Debian installation

A minimal Debian installation may not include `sudo`. Become root, install it and add the normal administrator account to the `sudo` group. Replace `david` with the account created during installation when necessary:

```bash
su -c 'apt update && apt install -y sudo && /usr/sbin/usermod -aG sudo david'
su -c '/usr/sbin/reboot'
```

Reconnect so the new group membership applies, update the complete base OS, remove obsolete packages and reboot:

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
sudo reboot
```

Reconnect again before continuing.

## Installation sequence

Install Git, clone RetroDB and enter the repository:

```bash
sudo apt install -y git
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb
```

Run the read-only preflight first:

```bash
sudo bash server/build.sh --check
```

On a new Debian host, warnings about missing packages, the `retrodb` account and its directories are expected. Apply the build and then validate the finished state:

```bash
sudo bash server/build.sh
sudo bash server/build.sh --check
```

The final check should report that all base packages are installed, PostgreSQL is running, and no account or directory warnings remain.

The default run is idempotent: rerunning it restores required packages, accounts, directories, ownership and the PostgreSQL loopback setting.

## Output and diagnostics

Normal output is deliberately concise:

```text
[RUN] Installing base dependencies...
[OK]  Installing base dependencies
```

Underlying command output is captured. If a step fails, the step is marked `[FAILED]` and the captured diagnostic output is displayed automatically.

Use `--verbose` when live APT, PostgreSQL and system command output is needed:

```bash
sudo bash server/build.sh --verbose
```

`--check` remains read-only and can be combined with `--verbose`, although the check itself normally produces little underlying output.

## Application deployment

After the host bootstrap passes its check, deploy the application foundation:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

The build step now includes `rsync`, which the deployment uses to copy the checked-out release into `/opt/retrodb`.

The deployment:

- generates a random PostgreSQL password when one does not already exist
- stores the database URL only in `/etc/retrodb/retrodb.env`
- creates the `retrodb` PostgreSQL role and database
- synchronises application files into `/opt/retrodb`
- creates an isolated Python virtual environment
- installs the pinned production dependencies
- applies Alembic migrations
- installs and starts the hardened systemd service
- calls the database-backed health endpoint

Normal output is concise. Add `--verbose` to display all underlying commands:

```bash
sudo bash server/deploy.sh --verbose
```

Validate the running service locally:

```bash
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/health
sudo systemctl status retrodb
```

The service deliberately binds only to loopback. LAN or guest access will be added later through a separately hardened HTTPS reverse proxy.

### Launch the menus from anywhere

Run this **once** from your checkout as your normal user (it asks for sudo only to write into `/usr/local/bin`):

```bash
cd ~/retrodb
git pull --ff-only origin main
bash server/install-launchers.sh
```

Then from any directory, type `retrodb` for the collection manager or `xerabora` / `xeRAbora` for the xeRAbora installer/profile manager. Arguments are forwarded to the underlying scripts (e.g. `retrodb audit`, `xerabora status`). Both commands use your **current shell user's profile and HOME**, not root's; don't prefix them with `sudo`. The wrappers target this checkout and stay current as you `git pull`. If you move the checkout to a new path, rerun the installer.

**Updated menu layout:** The main menu has `1) Audit game collection`, `2) Patch a PS2 game`, `3) Rename PS2 games` and `4) More options`. The submenu contains `1) Export reports`, `2) Download official patches`, `3) Service status`, `4) Recover OPL renames` and `5) View patch journal`. Export-only refreshes **formatting and proposals from an existing audit**; it does **not** rescan, rehash or refresh RA catalogue data. Run the full audit after changing actual game files.

Fresh RetroDB deployment automatically installs `/usr/local/bin/retrodb` and prints the command to open the menu. Fresh xeRAbora installation similarly offers `xerabora`. The separate `server/install-launchers.sh` can be rerun manually to repair or change shortcuts.

## RetroDB terminal manager

Run the standalone ASCII dashboard as your normal Debian user:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash -n server/manager.sh
bash server/manager.sh
```

Its header shows RetroDB/PostgreSQL status, the RetroNAS mount, RAHasher, report availability and the xeRAbora service/Web UI. RetroDB currently provides a local API health endpoint at `http://127.0.0.1:8000/health`, **not a complete RetroDB browser frontend**.

The operational workflows are:

1. **Audit game collection (main 1):** eight stages covering preflight, cached RA and GameDB catalogues, read-only inventory and hashing, patch manifest/download/source checks and report exports.
2. **Download/update official patches (More options 2):** refresh official patch packages locally; no ISO changes.
3. **Patch a PS2 game (main 2):** choose a verified RA game ID, run a local patch/hash-verified dry run, then explicitly type `PATCH-<RA_GAME_ID>` to authorise a temporary RW connection. The original file is backed up as `OLD_<filename>`, checked with SHA-256, and the replacement is RA-hash-verified on the NAS. Keep backups until real-console testing is complete.
4. **Export latest Excel workbooks (More options 1):** rebuild both compatibility and OPL proposal workbooks from the existing audit without rehashing.
5. **Service/integration details (More options 3).**
6. **Rename PS2 games (main 3):** preview eligible changes, require `RENAMEALL`, and use a temporary writable mount and a rollback journal; collision/review cases are not renamed.
7. **Inspect/resume interrupted OPL rename journal (More options 4).**
8. **Show latest PS2 patch deployment journal (More options 5).**

Exports in `~/retrodb-exports/`:

| File | Purpose |
| --- | --- |
| `RetroDB-Compatibility.xlsx` | Filterable Summary / PlayStation 1 / PlayStation 2 workbook with RA status, patchability, eligible coverage and recommendations |
| `RetroDB-OPL-Rename-Proposals.xlsx` | Filterable/frozen-header review workbook with proposed/current filenames, statuses, collisions and notes |
| `RetroDB-OPL-Rename-Proposals.csv` | **Authoritative input** to the OPL rename executor, not merely a spreadsheet export |
| `retroachievements-compatibility.csv` | Raw diagnostic audit data |

Example: download both current Excel reports **from your Mac terminal**, not from an SSH session on RetroDB:

```bash
scp david@retrodb.it.gattaca.house:retrodb-exports/{RetroDB-Compatibility.xlsx,RetroDB-OPL-Rename-Proposals.xlsx} ~/Downloads/
```

A new **full audit** is required after any ISO patch or OPL rename so that the database and raw audit reflect the new files. Export-only uses the last audit. Backups prefixed `OLD_` are excluded from scanning, RA matching, compatibility workbooks and rename proposals; they are **not deleted**.

RetroNAS is read-only during audits and reporting. Only explicit patch/rename operations use the separate temporary `/mnt/retrodb-retronas-pilot-rw` mount. Patch journals are written in `~/retrodb-exports/opl-rename-journals/`. If a NAS copy or rename fails, **inspect the journal and both source/backup files before retrying**. Do not assume an incomplete `OLD_` is a valid backup.

The terminal manager is the current supported operational interface; the polished RetroDB catalogue web UI remains planned.

### Safer regional aliases and unusual PS2 discs

Title normalisation now covers selected, reviewed branding/region variants
(Guitar Hero Rocks the 80s, Tomb Raider Anniversary/Legend and Disney's
Haunted Mansion). These are narrow identity aliases, not a global fuzzy
threshold reduction, and only a **verified RA hash** marks a local ISO as
compatible.

The filename serial parser also recognises `SCPM-85101` (McDonald's
Original Happy Disc, promotional demo) and `USGR-00036` (Shoot 'Em Up
Collection, hack compilation). These special discs have separate
`disc_classification` metadata and do not receive automatic **retail**
RA-title recommendations from name similarity. They can still legitimately
match RA via their hash. The Excel report includes their classification and
review note. Disc IDs and classifications are based on user-supplied
release references and should not be mistaken for cryptographic disc
validation.

### GameDB identification (PS2 initial integration)

The `backend/retrodb/providers/gamedb.py` provider fetches the official
[GameDB-PS2 titles release](https://github.com/niemasd/GameDB-PS2/releases/latest/download/PS2.titles.json)
and caches serial/title pairs in `/var/cache/retrodb/providers/gamedb/`.
A shared provider also declares a PS1/PSX source, ready for future rollout;
the default full audit currently **only synchronises PS2**.

When GameDB identifies a filename disc serial, the raw compatibility CSV records
`gamedb_title` and `gamedb_identified`. A GameDB title is compared against RA titles conservatively. Unique exact
canonical titles, or exceptionally high similarity (at least 0.94 with a
0.10 lead over the next candidate and matching sequel/edition safeguards),
can produce an **alternative-ISO recommendation**. Lower-scoring possible RA
matches are retained strictly as review candidates, never auto-accepted.
The original disc RA hash always determines play-ready compatibility. Otherwise the Excel report uses that title to improve
identification, but retains an **UNKNOWN** RA status. Its summary includes
`GameDB identified unknown` and `RA candidates to review` so recognised discs without a confirmed RA match
are distinguishable from completely unidentified ones.

GameDB metadata is **not proof of disc hash compatibility or the availability
of an achievement set**. Only an RAHasher match is marked RA-compatible. In
particular, a GameDB title lookup by filename depends on the filename's serial
being accurate; validating the ISO's internal disc serial is future work.

Credit: [GameDB](https://github.com/niemasd/GameDB), especially
[GameDB-PS2](https://github.com/niemasd/GameDB-PS2), and its source projects:
GameFAQs, MiSTer Addons, PlayStation Datacenter, Redump and VGCollect.
Review upstream licence and attribution terms before redistributing catalogue data.

### Disc serial identification (conservative first pass)

The matcher now recognises selected, **source-attributed** regional PS2 disc serials from
`backend/retrodb/data/ps2_serial_aliases.json`. Initially verified mappings include
`SCES-50410` (Ace Combat: Distant Thunder → Ace Combat 04: Shattered Skies),
`SCES-51608` (Jak II: Renegade → Jak II), and `SCES-51607`
(Ratchet & Clank 2 → Ratchet & Clank: Going Commando). A candidate is recommended
only if exactly one RA catalogue title matches the mapped identity. These are
**identity matches, not compatible ISO/hash confirmations**: RAHasher continues to
determine whether a particular disc image is ready to play.

The raw CSV includes `local_friendly_title` and a
`recommendation_confidence=verified-serial-alias` indication where appropriate.
Excel prefers the mapped RA game title when the identity is resolved and otherwise
uses a cleaned local filename. Existing historical reports still import correctly.

This is a small, manually verified alias catalogue, **not yet a comprehensive
Redump disc-serial index**. Games without a serial mapping or high-confidence
title recommendation remain unknown; no-RA-set status cannot be inferred from
that alone. Expand the JSON file only with independently confirmed serial/release
records and provenance. Existing title matching remains conservative, and
hash matching always has precedence.

After updating the Git checkout, deploy the current backend code and rerun the
full audit to generate fresh classifications:

```bash
cd ~/retrodb
sudo bash server/deploy.sh
bash server/manager.sh
```

## RetroAchievements credentials

The deployment adds a labelled RetroAchievements section to the protected configuration file:

```bash
sudo nano /etc/retrodb/retrodb.env
```

Enter only the account username and Web API key:

```text
RETRODB_RA_USERNAME=
RETRODB_RA_API_KEY=
```

See the [full credential setup guide](../docs/retroachievements-setup.md), including where to obtain the correct key and where redacted screenshots belong.

After saving the credentials and restarting RetroDB, test the connection and cache the achievement-enabled PlayStation and PlayStation 2 catalogues:

```bash
sudo bash server/retroachievements.sh test
sudo bash server/retroachievements.sh sync
```

The sync requests supported hashes and caches the response for 180 days. Use `sync --force` only for an intentional upstream refresh. Credentials are read from the protected file and are never placed on the command line or written to the cache.

## Security boundary

The bootstrap creates a non-login service user, protects configuration and data paths, and keeps PostgreSQL on loopback. It deliberately does not configure a firewall, mount collection shares, publish a port or place the application on the Internet.

Future work will add database creation, versioned application deployment, systemd units, migrations, health checks, backup/restore verification, reverse-proxy configuration and rollback handling.

### Effective collection compatibility (keep duplicate releases)

Excel now distinguishes **physical disc images** from **effective disc images**
used for its collection-wide RA percentage. If two PS2 images resolve to the
same nonempty RetroAchievements game ID and at least one has a verified
RAHasher match, the incompatible copy is labelled
`EXCLUDE — compatible copy present` and discounted from the effective
denominator. Both files and both detailed rows remain in place; RetroNAS is
never altered. The `Collection decision` column makes this transparent.

**Important:** this does *not* blindly deduplicate by RA game ID: multiple
verified discs for one game (e.g. disc 1 and disc 2) remain counted. Games
without a verified copy remain counted even if they share an RA ID; rows
without a reliable RA ID are not suppressed. These are **image-level**
effective counts, not yet one-game-per-RA-ID counts for verified multi-disc
sets. A separate unique-game metric can be added later.

Use menu option **4 — Export latest Excel workbook** to apply this
report-only change to the latest raw CSV without rehashing the collection.


### Recognised RA games with no achievement set

RetroDB now asks RetroAchievements for the **complete** console game directory
(`API_GetGameList`, `f=0,h=1`) rather than the old `f=1` catalogue which
omitted games without a published set. The first sync after this change must
download the expanded catalogue; future audits reuse the 180-day cache.

The matcher distinguishes a game with a recognised RA identity but **zero core
achievements** from one that has an achievement set but needs another ISO/hash.
It currently confirms no-set identity through unique canonical-title matches
to GameDB (rather than assigning questionable fuzzy identities). The CSV adds
`ra_set_status`, `no_set_ra_game_id` and `no_set_ra_title`.
The Excel report lists these as **NO SET** rather than implying that a
different-region image would unlock achievements. Unresolved entries remain
unresolved until a reliable crosswalk exists.

Summary columns now explicitly show **RA-ready %**, **Patchable %**,
**No-set %**, **Unresolved %** and **RA identified %**. Each uses the same
effective-image denominator (all images minus demonstrably redundant
incompatible copies), so values can be compared consistently. RA-ready is
restricted to verified hashes for games with an achievement set; identifying
a game without a set does not count as an achievement-ready image.


### Overall versus eligible achievement coverage

The Summary includes two distinct progress measures:

- **RA-ready %** = verified RA-compatible images / effective images.
- **Eligible RA-ready %** = verified RA-compatible images / (effective
  images minus confidently identified NO SET games).

Unresolved images **remain in the eligible denominator provisionally** rather
than inflating readiness; if a future catalogue resolves them as NO SET the
denominator shrinks. These are effective-image metrics, not complete multi-disc
unique-game coverage metrics. Both counts preserve source ROMs.


### Regional title identity resolver

A reviewed regional-title crosswalk now recognises identities including
Canis Canem Edit → Bully, Fahrenheit → Indigo Prophecy,
Ratchet: Gladiator → Ratchet: Deadlocked, and Ratchet & Clank 3 →
Ratchet & Clank: Up Your Arsenal. The same resolver checks both
achievement-enabled and no-set RA catalogue entries. Source files are
never modified, and a game identity recommendation is not a verified hash.

The raw CSV now includes `identity_resolution`; Excel adds an
**Identity evidence** column. Results distinguish verified RA hash, reviewed
regional title, candidate review, and no catalogue crosswalk. Explicit
edition distinctions such as Sons of Liberty/Substance or Most Wanted/Black
Edition are not overridden by aliases. Games without sufficient evidence
stay unresolved; the target is zero **unexplained** games, not forced matches.

### Unresolved RA identity triage

The current resolver now recognises reviewed branded titles for Blood Omen 2,
The King of Fighters: Maximum Impact (and sequel) and Virtua Fighter 10th
Anniversary. Identity mappings are suggestions only until a real RA hash
matches the ISO. Distinct editions and game entries are not assumed
interchangeable.

The raw CSV now includes `identity_review_reason`. Excel includes
`Resolution detail` for the remaining unknowns, distinguishing no RA
crosswalk, possible edition mismatch, different games and unusual
compilations. This reduces undifferentiated *Unknown* rows without claiming
there is a supported downloadable release where no official RA hash is known.

To reevaluate identities and hash metadata, deploy the updated backend and
run manager **Full Audit**. Export-only does not rerun the matching logic.

### OPL old-format naming proposal (read-only)

The manager's export option now also generates
`~/retrodb-exports/RetroDB-OPL-Rename-Proposals.csv` from the latest audit,
without requiring an additional ISO hash pass. It **never renames anything**
on the read-only RetroNAS mount.

The export preserves each disc's OPL old-style
`SLES_123.45.Game Name.iso` serial (so region variants stay distinct);
uses GameDB's serial-specific canonical title; sanitises unsupported
punctuation; and limits the title part to **27 characters** to leave
five display characters for the OPL-RA ` [RA]` marker under OPL's
32-character game-title budget.

Columns include source relative path and filename, disc serial, original
GameDB title, proposed filename and relative path, display preview,
truncation warning, proposed/unchanged/review/collision state and notes.
Missing GameDB identities, unusual disc IDs, case-only path changes and
colliding destinations are flagged for human review.

Renaming an ISO changes neither its content hash nor its genuine
RetroAchievements compatibility. A consistent GameDB title may improve
the filename-only fallback matcher, but RetroDB already prioritises
GameDB identification and verified RA hashes. Before any future rename
executor, validate SMB target behaviour, backup, stale scan paths,
cover-art and per-game OPL configuration effects.

### OPL rename review: case changes and duplicate evidence

Case-only filename changes are now normal **PROPOSED** renames, not
review blockers. On a case-insensitive SMB target, a future controlled
write executor should rename through a temporary intermediate filename
to ensure casing is actually updated.

A source image currently named **No Disc** is flagged for manual
identification, rather than being renamed to the GameDB title associated
with its reported serial. It may be a PS2 networking/setup disc; that
claim is not proven until the actual image is inspected.

During report export, RetroDB reads the **collision candidates only**
from the read-only RetroNAS mount and calculates full-file SHA-256.
Identical SHA-256 hashes produce a **manual duplicate-removal candidate**
recommendation; different SHA-256 hashes produce a **preserve/investigate**
warning. Missing source files remain unverified. No deletions or
renames occur. The report includes two additional fields:
`Duplicate recommendation` and `SHA256`.

The operation may take longer for large duplicate ISOs because it
reads each colliding source end-to-end. Do not assume identical disc IDs
or RA hashes imply byte-for-byte duplicate files.

### Excel encoding and suspect ISO inspection

The OPL rename CSV is now written as UTF-8 with a BOM, improving Excel
recognition of punctuation and non-ASCII notes. Hyper Street Fighter II:
The Anniversary Edition gets the 27-character display title
`Hyper Street Fighter II Anniv` (before the OPL-RA ` [RA]` suffix).

For a suspect `No Disc` ISO, the report now includes **Disc inspection**.
It reads the image's ISO9660 primary volume descriptor, the root-directory
`SYSTEM.CNF` file and its `BOOT`/`BOOT2` disc executable ID through the
read-only RetroNAS mount. The result may establish that the boot ID differs
from the filename serial, or it may be inconclusive for unusual layouts.
A boot ID alone does not authenticate the disc's commercial identity;
confirm against appropriate catalogues and boot content before renaming.
The original image is never changed.

After manually deleting old duplicate images, **run the FULL AUDIT** so
the cached inventory and underlying CSV reflect the revised collection.
Export-only reuses the previous inventory and can show stale duplicate
rows after files have been removed.

### OPL display-name quality pass

GameDB remains the full identity source, but the rename exporter applies a
small, reviewed display-title dictionary where naive 27-character truncation
would erase a sequel, edition, subtitle, collection identity or main game
name. Examples include Ready 2 Rumble Round 2, Midnight Club 3 DUB Remix,
Pinball HoF Williams / Gottlieb, LOTR's distinguishable releases, and TMNT
sequels. Short titles such as Guitar Hero Metallica remain untouched.

These abbreviations affect only the *proposed filename and OPL display preview*, never GameDB's stored identity or RA matching. The proposal export is read-only; the separate, explicitly confirmed menu option 6 performs actual renames.

### Historical first-40 OPL rename pilot (superseded)

The earlier first-40 pilot documented below is historical. Current menu **6** is the bulk confirmed rename operation, menu **7** is journal inspection/recovery, and menu **8** is patch journal inspection. Do not use pilot menu numbers from older documentation.

The default systemd RetroNAS mount remains **read-only at all times**.
The manager briefly creates a **second**, separately mounted CIFS connection
at `/mnt/retrodb-retronas-pilot-rw` with `rw` only for explicitly
confirmed apply/rollback actions, and unmounts that second connection
afterward. The NAS SMB credential itself must have write/rename permission.
If the original SMB account is read-only on the NAS, ask the NAS admin to
grant limited write permission or provision a distinct scoped credential.
Do not change the permanent audit mount to `rw`.

The pilot uses only CSV rows classified `PROPOSED`, skipping review,
collision, unchanged, and **case-only** changes for the initial batch
(case-only SMB handling will be added after the pilot). It validates
source existence, destination absence, and filesystem constraints. A
durable local rollback journal is created at
`~/retrodb-exports/opl-pilot-rollback.json` BEFORE the first rename
and updated after every operation. It is retained after rollback.
No file data is changed. The pilot refuses to overwrite destinations.

Keep a second copy of the journal OFF the VM, e.g. on Mac:
`scp david@retrodb.it.gattaca.house:retrodb-exports/opl-pilot-rollback.json ~/Downloads/`.
If interrupted, use menu option 8: rollback checks actual source/target
existence and recovers operations even if the last journal update was
interrupted. No new pilot can start while a previous journal exists;
archive that record only after successfully verifying rollback.

After application, test titles, artwork and settings with OPL Manager and
test a few ISOs on MMCE / OPL-RA. A full audit is needed to refresh cached
RetroDB inventory after renames. If the temporary mount fails to unmount,
manually inspect and unmount it before another operation.

### Update all OPL titles

Use menu **6 — UPDATE ALL eligible OPL titles** after menu **4 — Export**
has regenerated the latest rename proposals from a current FULL AUDIT.
It previews every proposed rename, then requires typing `RENAMEALL`.
Eligible entries must have status PROPOSED. REVIEW, COLLISION and UNCHANGED are skipped
and the skipped totals are shown before confirmation. There is no fixed
batch size. The existing read-only mount is unchanged. Only the temporary
second SMB mount is read/write, and it is unmounted afterward.

A unique per-run journal is created under
`~/retrodb-exports/opl-rename-journals/`. The earlier pilot file
`~/retrodb-exports/opl-pilot-rollback.json` is preserved. The new journal
records each original path, target, size, and progress and is written
before any renames. Back up both journals off the VM. On any error,
do not immediately rerun; check whether the journal contains partially
completed operations first.

Recovery is possible using `python3 server/opl_pilot.py rollback
--csv ~/retrodb-exports/RetroDB-OPL-Rename-Proposals.csv
--root <temporary-writable-retroNAS-mount>
--journal <exact-journal-path>`, after explicitly mounting a writable
connection. Rollback uses the original manifest (not the current CSV)
to restore exact names, and never overwrites an existing file.

### Case-only OPL filename changes

The Update All action now includes case-only proposals such as
`7 SINS.iso` -> `7 Sins.iso`. Because an SMB share may treat these
as the same name, RetroDB first renames to a unique temporary filename
in the same directory, journals this intermediate state, and then
renames to the desired case. Each step checks exact directory-entry
spelling and file size. Rollback understands both completed and
interrupted temporary states. Non-case changes continue to use direct
same-directory renames. The existing temporary-RW mount and a NEW
timestamped journal are used; old bulk/pilot manifests are preserved.

Regenerate the proposal CSV from a current inventory first. Do not
rerun the bulk action on an existing incomplete journal; inspect and
recover that run before a new batch.
