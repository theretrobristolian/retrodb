## OPL artwork archive import and streamlined game cover (October 2026)

Game details display **exactly one centred cover** beneath the heading **Cover art**: RetroAchievements artwork is preferred; if the image fails, a PSBBN serial-matched image is tried instead. No duplicate side-by-side covers or per-image captions.

The community [Luden02 OPL art archive](https://github.com/Luden02/psx-ps2-opl-art-database) has top-level `PS1/<DISC_ID>/<DISC_ID>_COV.png` and `PS2/<DISC_ID>/<DISC_ID>_COV.png` directories, plus other OPL art types. Its public repository is **several gigabytes** and contains many thousands of images; copying the whole thing is optional and can consume significant storage. Do **not** clone it into the RetroDB application directory or treat the OPL share as an image-archive backup.

After extracting/cloning the archive, `server/import-opl-art.py` can flatten all PS2 PNG artwork into your **existing OPL ART share**, preserving standard OPL filenames and skipping preexisting files by default. It makes no guesses about the NAS mount or OPL share location, and defaults to dry-run. PS1 artwork has an optional **separate staging folder**, because PS1 POPStarter/OPL artwork placement and naming depend on the specific frontend. Nothing is copied to a PS1 live path unless separately specified.

Example (replace the illustrative paths with your actual *existing* mounted directories):

```bash
git clone --depth 1 https://github.com/Luden02/psx-ps2-opl-art-database.git /srv/opl-art-source
python3 server/import-opl-art.py --source /srv/opl-art-source --ps2-art /mnt/retronas/ART
python3 server/import-opl-art.py --source /srv/opl-art-source --ps2-art /mnt/retronas/ART --apply
```

**CAUTION:** The example mount `/mnt/retronas/ART` is *not confirmed on your server*; do not run the import until the destination is verified to be the real OPL share. Script refuses nonexistent destination directories and never deletes files. Artwork usage and redistribution remain subject to rights held by the respective contributors. This importer does not automatically change RetroDB's cover provider priority or index the OPL share yet.

## Verified xeRAbora v1.0.0 server upgrade and RetroDB switching (25 October 2026)

**Verified on the user's Debian 13 (Trixie) x86-64 VM:** yoba's `xerabora-1.0.0-ubuntu24.04-linux-x86_64` ELF resolves its shared libraries and launches; the upgraded xeRAbora v1.0.0 web dashboard loads on port **18280**. Systemd runs the client as unprivileged user `david`, from `/opt/xerabora/xerabora-linux-x86_64`, with `--server --no-sound --ui-port 18280` and per-player `XDG_CONFIG_HOME` overrides.

**End-to-end server-side account switching verified:** both RetroDB accounts (`retrodb` linked to `theretrobristolian`; `PoodingPower` linked to `PoodingPower`) correctly display the linked RetroAchievements profile and can successfully switch the xeRAbora service back and forth using the authenticated **My Profile → Use this player** action. Existing credentials, player mappings, and the v1.0.0 dashboard survive the switches. The `set-startup-delay.sh 10` change was applied and tested successfully; the 10-second `ExecStartPre` pause improves switch responsiveness versus 20 seconds. Automatic recovery `RestartSec=10` remains unchanged.

**Not yet verified:** the new v1.0.0 binary's **actual PS2 console-side connection, in-game memory tracking, unlocks and leaderboard functionality**. Earlier successful gameplay tests were on an earlier build and must not be used as evidence that the newly installed v1.0.0 console side is proven. Confirm these separately before describing v1.0.0 as fully validated.

The Ubuntu 24.04-labelled binary runs on Debian 13 in this tested environment; this is an observation, not a guarantee for other systems. Install and upgrade procedures should keep a previous binary available for rollback. No RetroDB web application deployment or PS2 app development is implied by this documentation update.

## Efficient bulk RA artwork fetching (25 October 2026)

**New default:** `server/prefetch-artwork.py --mode icons` uses the official `API_GetGameList.php` bulk catalogue endpoint for PS1 (RA system 12) and PS2 (RA system 21), with `h=0` (do **not** download supported hashes) and `f=0`. The two large catalogue responses are each cached under `/var/cache/retrodb/artwork/ra/catalogue-12.json` and `catalogue-21.json` for **30 days**. This is a major reduction in metadata API calls for icon discovery; the RA API explicitly warns that game-list responses can be very large and must not be polled often. Matching uses *only the 840 or so RA game IDs already indexed in your local PostgreSQL library* (no additional ROM scanning), then downloads missing icon PNGs from the CDN individually. Images cannot be bundled into one API call. Existing metadata/artwork are reused; cached misses are skipped.

After deployment, preview and run:

```bash
cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh
sudo -u retrodb /opt/retrodb/.venv/bin/python /opt/retrodb/server/prefetch-artwork.py --dry-run
sudo -u retrodb /opt/retrodb/.venv/bin/python /opt/retrodb/server/prefetch-artwork.py --limit 25 --delay 12
```

The console catalogue may require **one fetch per console on the first icon run**, but subsequent 25-game icon batches reuse the local catalogue without another RA metadata API request. **`--mode full`** retains the previous per-game extended-metadata path, fetching `ImageBoxArt`, `ImageTitle`, `ImageIngame`, developer, publisher, genre and release year, with the same rate-conscious spacing. Example: `sudo -u retrodb /opt/retrodb/.venv/bin/python /opt/retrodb/server/prefetch-artwork.py --mode full --limit 10 --delay 20`. This is necessary for richer cover metadata not included in the system-wide game list. All operations are resumable and never delete previously cached full metadata.

**Important:** If an older `--mode full` batch is currently running, let it finish before starting a second batch to avoid overlapping API requests. Source changes are committed but not yet executed on the live VM.

## Resumable, rate-conscious RetroAchievements artwork prefetch (October 2026)

RetroDB now offers `server/prefetch-artwork.py` to populate the **existing local RA metadata cache and actual image files** from the distinct RA game IDs in the PostgreSQL `library_item` table. It avoids individual browser-triggered metadata fetch bursts and deduplicates identical RA game IDs across disc releases. It never scans/copies ROMs or writes database records.

Run **after a normal deploy**, as the `retrodb` service account (the program explicitly refuses to run as root):

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
sudo -u retrodb /opt/retrodb/.venv/bin/python /opt/retrodb/server/prefetch-artwork.py --dry-run
sudo -u retrodb /opt/retrodb/.venv/bin/python /opt/retrodb/server/prefetch-artwork.py --limit 25 --delay 12
```

Default: **at most 25 distinct games per batch**, **12 seconds between RA API calls** (minimum enforced 10 seconds), no parallel requests, skip fresh 30-day metadata, skip downloaded images. Re-run the identical command to continue where the previous batch left off. `--limit 10 --delay 20` is gentler. `--refresh` explicitly refreshes otherwise-fresh metadata (avoid unnecessarily). These are conservative client-side defaults, **not provider-approved quotas or a guarantee against throttling**. On HTTP 429/403 the prefetch stops rather than retrying aggressively; check any `Retry-After` guidance before resuming. A single failed image is skipped; transient errors are reported.

The prefetch downloads RA icon/box/title/ingame images to `/var/cache/retrodb/artwork/ra/GAME_ID/KIND.png`. The app now serves downloaded images locally from `/art/ra/GAME_ID/KIND`, falling back to the RA CDN until the local file exists. Metadata continues to be stored in `/var/cache/retrodb/artwork/ra/GAME_ID.json`. This does not make any bulk changes to PSBBN art caching and never sends browser users the RA API key. The cache can be used by guest library visitors. The server's existing `RETRODB_RA_API_KEY` must be set in `/etc/retrodb/retrodb.env`.

First run is **committed but not live-tested on the user's Debian VM**. The tool reports counts, skips fresh entries and stops safely at the end of each batch. If RA throttles even at these settings, stop and space batches further apart rather than increasing concurrency.

## Game artwork and basic release metadata (October 2026)

The game details page now displays a RetroAchievements game icon next to the title, RA box art in the main content, and additional serial-matched artwork from the community [PSBBN Art Database](https://github.com/CosmicScale/psbbn-art-database) when available. It also shows release date, publisher, developer and genre sourced from the **RetroAchievements Game Extended Details** API. Information is optional and may be absent; RA game-level release dates do not necessarily identify the exact regional disc release.

RetroAchievements metadata is cached at `/var/cache/retrodb/artwork/ra/<gameid>.json` for up to 30 days, using the already configured `RETRODB_RA_API_KEY` in `/etc/retrodb/retrodb.env`. Community art requests use sanitized disc IDs such as `SLUS_209.59` and download at most 4 MB of verified PNG data into `/var/cache/retrodb/artwork/psbbn/`. Failed lookups are cached for one day; image failures do not prevent the game page loading. Cached PSBBN art is served from `/art/psbbn/<serial>`, including to read-only guests. Image provenance is clearly labelled. This first iteration uses publicly supplied images with attribution and does not import the GPL art-downloader code. No bulk background scraping or automatic library mutations are performed.

Deploy: `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. Open any existing game detail page. The first request for a newly matched game may be a little slower while artwork/metadata is cached. Further sources, region-specific publisher/rating metadata, accessory flags, player counts and filters remain future work. This change is source-committed and **not yet runtime-tested on the user's VM**.

## Polished xeRAbora profile switching (October 2026)

The linked player's **My Profile** page uses a compact **Use this player** button and an iPhone-friendly confirmation dialog instead of the old inline warning checkbox. The dialog explains that selecting a different shared xeRAbora player interrupts any connected PS2 session and may require restarting OPL-RA/reselecting the appropriate MemCard Pro 2 image. The **Switch player** button disables on submit to reduce accidental repeat taps.

A successful switch now follows **POST → 303 redirect → GET /profile** to avoid an accidental second switch when Safari reloads or navigates back. The feedback is different for `switched` (service restarted for the selected account) and `already` (the helper reported the selected account was already active, no restart needed). This addresses the confusing message seen immediately after a manual player change. These messages indicate the result returned by the helper; they are **not** proof of live PS2 session ownership. The underlying least-privilege Unix socket helper, administrator-approved mapping and signed CSRF form validation are unchanged. Newly added regression tests exercise both outcomes; real iPhone behaviour needs verification after deployment.

Deploy with `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. The already-installed optional switch helper does not need reinstallation for this interface-only update.

## Linked RetroAchievements profiles and optional xeRAbora switch (25 October 2026)

**Implemented:** Named RetroDB users now have a **My profile** navigation entry and `GET /profile`. The page reads an **administrator-approved mapping**, displays the official RetroAchievements avatar, username, motto, hardcore points and softcore points (where the RA Web API is configured), and links to the RA website. Guest users cannot access it. The user's RA password is **never collected by RetroDB**. The existing bcrypt local login remains authoritative; looking up a public RA user does **not** verify ownership. A single server-side Web API key from `/etc/retrodb/retrodb.env` (`RETRODB_RA_API_KEY`) is used for public profile reads; never expose or check this key into Git.

**Set up an explicit link**, after deploying the current repository:

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
sudo python3 server/manage-profile-links.py list
sudo python3 server/manage-profile-links.py link LOCAL_RETRODB_USERNAME RETROACHIEVEMENTS_USERNAME
```

The script verifies the **local username exists** in `/etc/retrodb/web-users.htpasswd`, creates `/etc/retrodb/profile-links.json` with `root:retrodb`, permissions `0640`, and only associates accounts when a trusted administrator runs it. Replace the uppercase example arguments with actual names. Existing links are preserved when adding others. Refresh `/profile` after linking; a backend restart is not needed.

**Optional xeRAbora profile switching:** xeRAbora has its own cached credentials under the xeRAbora service user's `~/.config/xerabora-profiles/PROFILE/xerabora/credentials`. A local RetroDB account may be mapped to a **pre-existing** profile by an administrator (the helper never receives an RA password):

```bash
sudo python3 server/manage-profile-links.py link LOCAL_RETRODB_USERNAME RETROACHIEVEMENTS_USERNAME --xerabora-profile EXISTING_XERABORA_PROFILE
sudo bash server/enable-xerabora-web-switch.sh
```

The second command is an **explicit opt-in**, separate from `deploy.sh`. It installs the `retrodb-xerabora-switch.socket` and `.service` systemd units. The web process retains `NoNewPrivileges=true`; it can only contact a group-restricted local Unix socket, never execute arbitrary commands or use sudo. The separate root helper checks the calling UID, reloads the root-controlled allowlist, validates the requested target and the xeRAbora user's existing profile/credential files, and applies a fixed xeRAbora systemd override. It does **not** create users or reveal any credentials. A logged-in player must tick an explicit interruption warning and submit a CSRF-signed POST before switching; guest mode cannot call it. An approved switch restarts xeRAbora; **quit the game and relaunch OPL-RA / restart your PS2**, and select the correct MemCard Pro 2 image. This is a **shared PS2 service**, not independent per-player sessions.

**Important:** The new helper was committed with application-level regression tests but **has not been installed or end-to-end tested on your Debian host**. Before installing the optional root service, inspect the systemd units and helper script and take a backup of `/etc/systemd/system/xerabora.service.d/profile.conf`; use the terminal xeRAbora profile menu until you're ready to test an interruption. For any error see `sudo journalctl -u retrodb-xerabora-switch.service -n 80 --no-pager`. Disable the optional socket with `sudo systemctl disable --now retrodb-xerabora-switch.socket`. The rest of the RetroDB catalogue and login work without this optional component.

## Named-user login fix: password-file directory permissions (25 October 2026)

**Root cause identified:** `server/configure-web-access.sh` creates `/etc/retrodb` as `root:www-data` with mode `0750`, while `retrodb.service` runs as `retrodb:retrodb`. Although the application bcrypt hashes are installed at `/etc/retrodb/web-users-app.htpasswd` with `root:retrodb 0640`, the service user could not traverse the parent directory. Password verification silently caught the resulting permission error and displayed **Incorrect username or password**, even after resetting a valid account. The deployment now makes the parent directory traverse-only to non-owner/non-group users (`root:www-data 0751`) while preserving individual file restrictions, and explicitly checks that the `retrodb` service account can read its hashes.

Apply immediately using `sudo chmod 0751 /etc/retrodb` and validate with `sudo -u retrodb test -r /etc/retrodb/web-users-app.htpasswd && echo 'Password hashes readable'`. Then retry an existing named-user login; no service restart or password reset should be required for this access fix. For a persistent deployment fix, `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. The final successful browser login remains to be verified on the user's environment.

## Safari guest sign-out correction (25 October 2026)

**Fixed in source:** The guest **Leave guest view** / signed-in **Sign out** form formerly submitted `POST /logout` without a CSRF form token, while the logout handler insisted on matching `Origin`/ `Referer` to the HTTPS hostname. Safari, especially installed Home Screen web apps, can send `Origin: null` or omit those headers. This could yield a bare 403 response presented as a download instead of logging out.

Catalogue pages now include an **expiring, HMAC-signed logout CSRF field**. `POST /logout` verifies this token (including for guest sessions), clears the signed cookie and redirects to `/login`. Invalid/stale tokens produce a human-readable HTML error rather than an empty response. Regression tests cover Safari's null-origin guest sign-out and rejecting forged tokens. **This must still be tested on a real iPhone.** It does not change the separate, still-unverified named-user login flow.

Deploy: `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. Then close/reopen the iPhone home-screen app and test **View as guest → Leave guest view**. If the form expired, reload the catalogue first.

## Terminal menu update health-check fix (25 October 2026)

The application-managed web sessions deliberately protect `GET /health`: an unauthenticated request returns HTTP **401**, not 200. Earlier `retrodb → More options → 6) Update RetroDB` ran `curl --fail http://127.0.0.1:8000/health` **after** a successful deployment, producing a misleading `curl: (22) ... 401` / `[ERROR] Operation failed`. This was a post-deployment validation bug, not evidence that migrations, service restart or the actual deployment failed.

The updater now requires `/login` to respond **200** and the unauthenticated `/health` endpoint to respond **401**. The terminal menu shows `Local API: auth required` rather than `unavailable` on a protected API. Do not remove session protection from health or APIs merely to satisfy a menu check. Service availability can still be inspected using `systemctl status retrodb`, `journalctl -u retrodb`, and the login route.

### Mobile-width library table (25 October 2026)

On iPhone, the catalogue now uses a width-constrained, fixed-layout table instead of the old 660px minimum. Long game names and disc serials wrap within their columns. RetroAchievements status is an **icon only**: a gold 🏆 for a locally **verified matching RA disc hash plus game ID**, or a dim/crossed trophy for other and unknown states (which **does not** mean confirmed unsupported). The icon retains a descriptive hover/accessibility title. The RA header is abbreviated to save space. Sticky table headings and the independent vertical scroll remain, as do selectable columns, guest access and desktop rendering. On very narrow displays, hiding RA ID or Disc ID through the Columns controls provides more room for titles.

Deploy: `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. No new schema, ROM mutations, or permissions required.

## GameDB titles in the web catalogue (October 2026)

The web UI now **reuses the same cached GameDB serial-to-title map as the RetroAchievements audit** at `/var/cache/retrodb/providers/gamedb/{playstation,playstation-2}.json`. For a game with no populated `ra_game_title`, it extracts the disc serial from the filename/path and checks the local GameDB cache before using a cleaned filename fallback. This resolves known abbreviated filenames such as GTA VCS when the respective disc ID is present in GameDB. A verified RA title retains precedence. Searching, A–Z filters and game-title sorting use these resolved names **before 100-item pagination**. The game-details heading uses the same lookup.

No web request downloads data or changes ROMs. The cache must already exist, be valid, and be readable by the `retrodb` service user; if not, titles gracefully fall back to filenames. To inspect a missing record:

```bash
sudo -u retrodb python3 - <<'PY'
import json
from pathlib import Path
p=Path('/var/cache/retrodb/providers/gamedb/playstation-2.json')
print('GameDB cache exists:', p.is_file())
if p.is_file():
    data=json.loads(p.read_text())
    for serial in ('SLES-52541','SLES-54622'):
        print(serial, data.get(serial, '(no GameDB match)'))
PY
```

The audit/export title priority remains broader (including recommended RA titles and other audit-time hints). Those additional fields are still not persisted to `library_item`, so a smaller number of titles may differ from the Excel export. The current in-memory name sort is intended for the existing ~1,200-file collection; for much larger catalogues, resolved titles should be materialized and indexed in PostgreSQL.

## Console game library UI (25 October 2026)

The read-only `/library` and `/library/{slug}` views now display game titles, parsed serial badges, RA game IDs, and 🏆 only for records with `ra_match_status=matched` and a populated RA game ID. The Format column is optional. Select RA filters, sort direction/column, A–Z or search; columns can be shown/hidden with local browser preferences. The table header is sticky within a vertically scrollable table, and the site header is pinned.

Names use the database `ra_game_title` where present, otherwise the locally cached GameDB title matched by disc serial, and finally a cleaned filename. Name sorting, search and A–Z filtering resolve those displayed titles before pagination. Note that the Excel report additionally uses recommended RA names, GameDB and local-friendly-title audit fields which are **not yet persisted to library_item**; perfect parity requires importing those fields. No ROM or database modification is performed by these UI changes.

Deploy with `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. Tests were added but should be run locally using the repo test environment.

## Current web access status and intended HTTP/HTTPS policy (25 October 2026)

**Verified on the household setup:** RetroDB is available over **https://retrodb.it.gattaca.house/** through Nginx with a certificate issued by the private **Gattaca-Root-CA**. The CA has been installed/trusted on the Mac and iPhone. The RetroDB favicon, iPhone Home Screen icon and application name render correctly, and **View as guest** successfully opens the PS1/PS2 catalogue on iPhone. The guest session can browse consoles, search the library and view game details; RetroDB management, online services, APIs and xeRAbora/profile-switching functionality are not exposed to guests. The restrictions are enforced in the FastAPI session middleware, not just hidden links.

**Resolved login incident:** Named-user login was confirmed working after correcting the service account's access to the bcrypt password file. Earlier form submissions generated `Invalid request origin` and `Invalid login form`; a server-side test using deliberately invalid credentials did pass CSRF validation and reached the expected HTTP 401 password-verification response. Guest entry/logout and named-user login are operational; longer-term per-user roles, MFA and per-device session revocation remain future work. Privileged xeRAbora switching is separately gated by an approved profile mapping, signed confirmation and an opt-in restricted service.

**Protocol/security policy (design, not deployed functionality):**

| Access | HTTP on trusted LAN | HTTPS |
|---|---|---|
| Guest catalogue (read-only) | **Desired future option; not enabled/verified** | **Working** |
| Named-user password login/session | **Must not be permitted** | **Working with HTTPS sessions** |
| Management, APIs, xeRAbora profile switching | **Never exposed to guests** | **Authentication/authorization required; privileged operations not yet implemented** |

Current `server/configure-web-access.sh https` creates an **HTTP → HTTPS redirect**; it does **not** serve guest catalogue pages over plain HTTP. FastAPI guest mode currently issues the same `Secure`, `HttpOnly`, `SameSite=Lax` session cookie type as named-user sessions, so plain HTTP guest mode needs explicit engineering changes. Do **not** remove `Secure` from authenticated cookies or expose `/login`, `/guest` POST, or management routes on HTTP. A future HTTP guest-only listener should enforce strict route/method allowlisting **at the reverse proxy and application layers**, avoid password fields and credentials on HTTP, and work without a shared session cookie that could affect HTTPS authentication. Limit even guest HTTP to the trusted LAN/VPN, since game records may disclose filenames and collection paths.

**Using RetroDB from an iPhone:** trust the public Gattaca CA (install the certificate profile **and** enable full root trust under Settings → General → About → Certificate Trust Settings); open `https://retrodb.it.gattaca.house/login` in Safari; choose **View as guest**; use Share → **Add to Home Screen** and name the shortcut **RetroDB**. If an old icon is cached, remove the old shortcut and add it afresh. The site is not offline-capable.

**Deploy current code:**

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
```

**Troubleshooting named logins:** Check `sudo journalctl -u retrodb -n 80 --no-pager`, the Safari Web Inspector POST to `/login`, response status and whether the form has a `csrf_token`. Never publish real passwords, session cookies or CSRF tokens in issues or screenshots. Avoid claiming an HTTP 401 response with intentionally bad credentials proves a real user's successful sign-in; it only proves the request reached password verification.

---
## iPhone standalone web app: persistent HTTPS login (October 2026)

RetroDB now provides **application-managed login sessions** instead of requiring the Nginx HTTP Basic authentication dialog on every Home Screen launch. It reuses the existing bcrypt `htpasswd` usernames/passwords and signs a Secure, HttpOnly, SameSite=Lax cookie valid for up to **30 days** on that device. A login form, explicit Sign out button and application-level protection for pages and APIs are included. Login and guest-entry POSTs validate signed, expiring CSRF form tokens rather than requiring Origin/Referer headers; logout still checks the request origin when supplied. Web operations remain read-only; application sessions are **not yet role-based accounts**.

**Important two-phase migration** — run on Debian while retaining the current HTTPS reverse proxy:

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
sudo bash server/enable-web-sessions.sh
```

The deployment generates a durable signing secret in `/etc/retrodb/retrodb.env` (root + retrodb group only), copies existing bcrypt hashes into `/etc/retrodb/web-users-app.htpasswd` (root + retrodb group only), and restarts only RetroDB. It does **not** disclose passwords. The second command **fails closed** unless the localhost login returns 200 while the unauthenticated homepage redirects (303) and protected health API rejects access (401); only then does it remove Nginx's Basic authentication directives from the **HTTPS** vhost and reload Nginx. Nginx continues terminating trusted TLS. If migration fails, leave the original Nginx authentication enabled and inspect `journalctl -u retrodb -n 80 --no-pager`.

Visit `https://retrodb.it.gattaca.house/` in iPhone Safari. **Guest mode is working; named-user login is now working after correcting the password directory permissions.** Once named-user sign-in is fixed, sign in via the RetroDB-branded form. Remove the old home-screen shortcut and install a new one with **Open as Web App enabled**. Home-screen apps have independent cookie storage, so you may need to log in **once more inside the new app**, then it should persist across launches for up to 30 days unless the session is cleared, expires, the signing secret changes or the account is removed. Do not reuse the old shortcut to test icon changes. The Apple touch icon and manifest are now public application assets once the Nginx Basic-auth requirement is removed, fixing the unauthenticated icon-fetch problem.

**Accounts:** Password file remains managed with `sudo htpasswd -B /etc/retrodb/web-users.htpasswd USERNAME`. After adding, changing or removing accounts, sync the updated bcrypt hashes securely for the unprivileged application:

```bash
sudo install -o root -g retrodb -m 0640 /etc/retrodb/web-users.htpasswd /etc/retrodb/web-users-app.htpasswd
```

For emergency rollback of Nginx Basic authentication (without changing the certificate), re-run the existing `sudo bash server/configure-web-access.sh https /etc/retrodb/certs/fullchain.pem /etc/retrodb/certs/privkey.pem` script; this deliberately reinstates the original proxy login. Avoid exposing port 8000 or port 80 externally. Keep 443 limited to trusted LAN/VPN clients.

Known limitations: session renewal currently requires signing in at expiry; changing a password does not automatically revoke a previously issued session until its 30-day expiry, though removing an account does. There is not yet per-device session revocation, account lockout, per-user permissions, or MFA; retain VLAN/firewall protections and do not enable privileged browser actions until these controls are implemented.

## iPhone home-screen / favicon branding

Borrowing the *web-app metadata pattern* from [Beoremote-Pro](https://github.com/theretrobristolian/Beoremote-Pro), RetroDB now supplies its own branded favicon (`/favicon.svg`), Apple touch icon (`/apple-touch-icon.png`), Android/PWA icons (`/icons/icon-192.png`, `/icons/icon-512.png`) and manifest (`/manifest.webmanifest`). The browser title and installed home-screen name are **RetroDB**. All icons are generated locally, without external assets or extra dependencies. This is a home-screen-capable website, not an offline-capable app; browsing still requires access to your trusted network and HTTPS server.

To deploy updated FastAPI routes and branding on the Debian VM:

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
```

Then open **https://retrodb.it.gattaca.house/** in iPhone Safari, tap Share → **Add to Home Screen**, confirm the name **RetroDB** and select **Add**. If previously added, remove the old home-screen bookmark and add it again to refresh cached metadata/icons. Safari may cache the favicon and touch icon; reload the site if necessary. After the application-session migration, Nginx Basic authentication is removed from the HTTPS virtual host; the app login and guest entry are handled by RetroDB.

## Security and PS2 multiplayer notes (25 October 2026)

**Important security change:** `server/configure-web-access.sh` now requires a browser login (created with an interactive bcrypt `htpasswd` prompt on first run). If you installed the earlier unauthenticated proxy, re-run the configuration to apply this protection. For **HTTPS**, configure a trusted certificate; HTTP Basic authentication sent over ordinary HTTP is **not secure against credential interception**. Keep the service LAN-only while upgrading to HTTPS. The web app remains bound to loopback and runs as the dedicated `retrodb` account; no browser sudo or systemd management endpoints are enabled. Existing Nginx sites are not intentionally removed. Review certificate and firewall permissions before offering access to other household users.

Co-Optimus is a promising independent source for **PS2 cooperative player counts** (couch, online, split-screen and LAN). It is not a source of complete competitive multiplayer limits. Bulk import is deliberately postponed because the site's content was not reliably retrievable and provenance/licensing must be respected. See [PS2 multiplayer and least-privilege design](docs/ps2-coop-and-service-security.md) (relative to the repository root).

## RetroDB LAN access and online services (preview)

RetroDB still binds only to `127.0.0.1:8000` internally. For optional **LAN-only HTTP** access at `http://retrodb.it.gattaca.house`, first ensure your local DNS record resolves to the Debian VM and that its firewall only permits trusted LAN clients, then run:

```bash
cd ~/retrodb
sudo bash server/deploy.sh
sudo bash server/configure-web-access.sh http
```

This installs/enables Nginx as a reverse proxy on port 80. It does not change the RetroDB Uvicorn listener. If Nginx already hosts other sites, **review the generated virtual host and test the existing configuration first**. Do not expose port 80 or 443 to the internet: **the application itself does not yet have a role-aware login (Nginx enforces Basic authentication)**.

For **HTTPS**, obtain a server certificate with DNS name `retrodb.it.gattaca.house`, full trust chain and matching private key (for example from a trusted AD CS issuing CA), then run:

```bash
sudo bash server/configure-web-access.sh https /path/to/fullchain.pem /path/to/privatekey.pem
```

This copies the chain and key to `/etc/retrodb/tls` and configures an HTTPS Nginx listener with HTTP redirected to HTTPS. Client browsers must trust the issuing CA; the certificate must contain the DNS name in Subject Alternative Name. You can change between `http` and `https` by rerunning the corresponding script with appropriate input. There is deliberately **no unauthenticated browser switch** for server/TLS configuration.

The web UI now has an **Online Services** tab with direct links to xeRAbora (`http://retrodb.it.gattaca.house:18280/`), XLink Kai (`http://xlinkkai:34522/`), RetroAchievements and GitHub. These are **links, not service-health checks**. Browsers must be able to resolve and reach the service names and ports. xeRAbora player switching remains terminal-only until we implement strong browser authentication and a tightly scoped service helper; its private player credentials are not exposed to RetroDB.

To publish the already imported PS2 community online compatibility data for game-detail pages:

```bash
sudo bash server/publish-online-data.sh
```

This copies only public source metadata JSON from the invoking user's `~/.cache/retrodb` to a service-readable directory, **not** xeRAbora credentials or RA API keys. On PS2 game pages RetroDB uses a serial parsed from the indexed filename/path for exact release matching; games without an identifiable serial remain `UNKNOWN`. LAN/XLink title matching and PostgreSQL import are not yet connected to these pages. Online service availability remains **UNVERIFIED**.

## RetroDB web frontend v1 (October 2026)

RetroDB now includes a **real, read-only browser UI** in the existing FastAPI application. It is an early preview, not a fully populated Plex-style catalogue. The root page shows the platforms configured in PostgreSQL; select one to browse indexed library files. Available pages:

- `/` — console homepage with indexed file counts.
- `/library` and `/library/{platform-slug}` — searchable A–Z / paginated inventory (100 files per page).
- `/game/{library-item-id}` — local game file details and known RetroAchievements identifiers/status.
- `/management` — read-only collection status, indexed/missing counts, and future management actions.
- `/health` and `/api/v1/platforms` — existing service health and JSON API.

**Safe trial on the Debian VM** (the service is loopback-only by design):

```bash
# On the RetroDB VM, after restarting the retrodb launcher to update main:
cd ~/retrodb
sudo bash server/deploy.sh
```

On your **own computer** establish an SSH tunnel (keep this terminal open):

```bash
ssh -N -L 8000:127.0.0.1:8000 david@retrodb.it.gattaca.house
```

Then open **http://127.0.0.1:8000/** in your computer's browser. This deliberately does **not** expose the web UI publicly or automatically to the LAN. If you already use local port 8000, substitute local port 18000 in the SSH command (`-L 18000:127.0.0.1:8000`) and browse `http://127.0.0.1:18000/`.

If your page shows zero indexed games, you can populate the database's **read-only inventory** using the existing scanner on the VM (this is separate from the full RA audit and does not hash ISOs):

```bash
sudo -u retrodb env PYTHONPATH=/opt/retrodb/backend \\
  /opt/retrodb/.venv/bin/python -m retrodb.cli \\
  library-scan --root /mnt/retrodb-retronas
```

This scan needs the RetroNAS automount working and the `retrodb` service account to be able to read the share. The scanner updates only PostgreSQL inventory records; RetroNAS is never written to. The current scanner covers PS1 and PS2 paths only; further consoles are planned.

**Important:** The web UI reads PostgreSQL's existing `library_item` inventory, not the CSV and Excel audit snapshots. If the console counts show zero, it means the DB inventory has not yet been scanned/populated; **it does not mean your RetroNAS game files are missing**. The existing menu / inventory scan remains the source for indexing. In v1, online DNS and XLink reports still live in the offline imported data and Excel report; database-backed game online settings, manuals, artwork, genre, profile progress, job progress, and authenticated rescan/update buttons are future work. These controls are intentionally non-functional placeholders and not security-sensitive shell-command endpoints. RetroNAS remains read-only; nothing touches the xeRAbora binary or its existing web UI.

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

**Automatic updates on menu launch:** Typing `retrodb` checks the trusted project's `origin/main` and fast-forwards the repository before showing the menu, if the tracked working tree is clean and the checkout is on `main`. A timeout, offline GitHub connection, local modifications or diverged branch **never causes a forced reset**; RetroDB opens the already-installed menu and prints a warning. Only the interactive menu triggers this check; `retrodb audit` and other non-menu commands do not. This updates checked-out menu/scripts, **not** the deployed backend service under `/opt/retrodb`, which still requires `sudo bash server/deploy.sh` after backend changes. For existing installations, first run `cd ~/retrodb && git pull --ff-only origin main` once to install the new auto-update logic.

### Maintenance from the RetroDB menu

In **More options**, select **6 — Update RetroDB** for a complete, explicitly confirmed application update. It validates the trusted GitHub checkout, pulls clean `main` changes via fast-forward, checks/repairs the required host dependencies when necessary, runs `server/deploy.sh` (including database migrations and a controlled service restart), and validates the health endpoint. The updater does not patch game images, rename ROMs or update xeRAbora itself. The launch-time updater still refreshes only menu/source scripts and never restarts services without confirmation.

Select **7 — Upgrade Debian** for host operating-system maintenance. This refreshes APT metadata, displays a `full-upgrade` **simulation**, requires typing `UPGRADE SYSTEM`, and then runs the actual package upgrade. It does not reboot or autoremove automatically; a required reboot is reported for manual scheduling. System upgrades can interrupt other services, so review the preview and perform them during a maintenance window.

These actions are distinct: the first updates the RetroDB application and its service; the second updates the Debian/Ubuntu host's packages. Both are implemented in `server/maintenance.sh`, and neither runs just because you opened the menu.

### Cross-platform Action Required report

The standard `RetroDB-Compatibility.xlsx` now has an **Action Required** worksheet immediately after Summary, combining PS1, PS2 and any other platforms exported by the report generator. It includes only unresolved games, unverified RA-supported releases, checksum-verified patch opportunities and hash failures that still need action. It excludes verified games, no-set/no-listing games, and redundant entries already covered by a verified copy of the same RA game. Rows are sorted by error, patch, replacement release and identity investigation.

The sheet includes platform, game name, full filename, disc ID, current status, proposed action, recommended release and region, RA ID, an existing verified copy when identifiable, reason, alternative RA candidates, local RA hash, accepted hashes and source path. The original per-platform sheets remain unchanged. Download **`RetroDB-Compatibility.xlsx`** as normal; no additional workbook or command is necessary. A **full audit** refreshes the underlying identity/hash data; export-only recreates the workbook from the previous audit.

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

### Manually reviewed PS2 RetroAchievements identities (October 2026)

The review crosswalk `config/ps2-reviewed-ra-identities.csv` stores verified-by-human disc serial to RA game ID suggestions. It is ingested by the PS2 matcher after the RA catalogue loads. Only rows marked `reviewed` are eligible; entries marked `needs-edition-review` (e.g. *MGS2 Sons of Liberty* vs *Substance*, *NFS Most Wanted* vs *Black Edition*, *Outlaw Volleyball Remixed*) **are intentionally excluded**. When an ID is missing from the current cached RA catalogue, a warning is logged and normal review handling continues.

The RA catalogue determines whether the resolved ID has achievements. With a set, the image gets an RA-supported **recommendation**, not a verified green state; a green RA match still requires the local RAHasher hash to equal a registered RA hash. With no set, the image can be classified `NO_SET`. Recommended release hashes and region information are fetched by the normal existing flow when available.

To apply crosswalk updates, use **More options → Update RetroDB** (deploys the backend and config into `/opt/retrodb`) and then **Audit game collection**. Merely regenerating Excel exports cannot update identities from cached audit data. Local/manual findings remain inspectable in CSV without editing application code.

### Multiple official patch variants (Max Payne, RA 19129)

The patch planner now searches all cached RA game-hash entries carrying the official `rapatches` label and an approved patch URL, **not only the preferred hash**. Each distinct supported hash has its own patch download/preparation workspace. The preparation step prioritises the actual read-only RetroNAS collection ISO when checking source MD5/CRC32 or RA hash; an existing clean ISO is never considered ready merely because its serial or region matches.

For *Max Payne* (PS2), the USA `SLUS-20230` collection source was manually verified against the official Bartis1989 patch source MD5 `10dd8182af1e4d4216be61216768f712`. RetroDB must independently repeat that check against the patch README, then pass the **patched output** RA hash `dd5f58908acd8062a13551de7a1d5fbe` before any NAS replacement. The PAL `SLES-50325` source is not interchangeable.

After **More options → Update RetroDB**, run **Audit game collection** to refresh the patch plan and download all official variants. Then use **Patch a PS2 game**, select RA ID `19129`, and check the local dry-run result. Only type the patch confirmation if the exact source is shown and dry-run RA hash passes. The operation copies the original to an `OLD_` backup, SHA256-verifies it, then stages and RA-verifies the new ISO on the NAS before replacing the active filename. **Do not remove the backup until Max Payne boots and saves correctly.** The official RA forum warns that this anti-cheat patch requires a fresh game save on a memory card without existing Max Payne data.

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
