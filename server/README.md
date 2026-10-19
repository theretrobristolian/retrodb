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

## RetroDB terminal manager

Run the standalone ASCII dashboard as your normal Debian user:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash -n server/manager.sh
bash server/manager.sh
```

Its header shows RetroDB/PostgreSQL status, the RetroNAS mount, RAHasher, report availability and the xeRAbora service/Web UI. RetroDB currently provides a local API health endpoint at `http://127.0.0.1:8000/health`, **not a complete RetroDB browser frontend**.

The simplified menu focuses on three workflows:

- **1 — FULL AUDIT:** Eight labelled stages: check the read-only RetroNAS mount and RAHasher; sync the RA catalogue; fetch/cache GameDB's PS2 serial/title catalogue; inventory PS1/PS2; hash and match against RA; prepare patch manifest; download official patches and verify candidate sources; export Excel and raw CSV. The workflow stops on an error and never modifies ROMs on RetroNAS. Downloaded GameDB data is cached for 180 days. The GameDB lookup uses the **filename serial**; disc internal ID inspection is future work.
- **2 — Download official patch packages:** Create/update the patch manifest and download/reuse official patch packages locally. No ROM patching occurs.
- **3 — Apply verified patches locally:** Requires typing `APPLY`, refreshes source checksum verification, and only applies patches to eligible clean images. Patched outputs are placed in `/var/lib/retrodb/patches/verified/` and validated using RAHasher. Review those outputs and copy them back to RetroNAS yourself; the original share remains read-only.
- **4 — Export latest Excel:** Rebuild Excel and copy raw CSV from the existing audit without scanning or downloading patches.
- **5 — Service/integration details:** Show RetroDB, xeRAbora and RetroNAS systemd status.

Run `bash server/manager.sh` for the menu, or `bash server/manager.sh audit`, `export`, `patches` or `patch-apply` directly.

The manager exports `~/retrodb-exports/RetroDB-Compatibility.xlsx` alongside the raw `retroachievements-compatibility.csv`. The Excel report has a **Summary** tab and separate **PlayStation 1** and **PlayStation 2** tabs. Console tabs are sorted by friendly game name and show the filename, disc ID, RA compatibility, a separate **Patchable** YES/NO field, clear issue/recommendation, RA game ID, recommended release, region and patch reference. The Summary tab separately totals verified RA-compatible games, confirmed patchable sources, other suggested ISO replacements, unknown games and hash errors. **RA compatible YES** means the existing ISO/disc image hash matches RA. **Patchable YES** requires a matching source entry in `/var/lib/retrodb/patches/patch-prepare.json` with state `clean-base-verified-ready-to-patch`, and the verified candidate must be the actual RetroNAS collection file, not a separately supplied incoming image. A mere patch URL or `rapatches` label does *not* qualify. Generate that verification with `sudo bash server/retronas.sh patch-plan`, `patch-download`, then `patch-prepare`. Re-run `patch-prepare` after changing any source files; the report reflects the *last preparation run*, not a new checksum test during Excel export. Patchability does not mean RA compatibility until the patched output passes RAHasher verification. It uses Python's standard library (no additional package installation). The export directory and files are private to the Linux account (directory `700`, files `600`), leaving the protected original in `/var/lib/retrodb/reports/` unchanged. It displays macOS/Linux and Windows PowerShell `scp` commands for downloading the CSV **from your computer**, outside the SSH session. The Excel workbook is the recommended download; the CSV is available when deeper technical troubleshooting is needed. Neither the audit nor the export modifies ROMs on RetroNAS.

Direct commands: `bash server/manager.sh status`, `bash server/manager.sh audit`, `bash server/manager.sh export`, `bash server/manager.sh patches`, `bash server/manager.sh patch-apply`.



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
