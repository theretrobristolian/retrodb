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

## Game library table improvements (25 October 2026)

Console and All Games pages now provide a scrollable table with sticky headings and a sticky global navigation bar; the table shows **game name**, **disc serial** (badge when a recognised serial appears in the stored filename/path), **RetroAchievements game ID**, **achievement match** (gold 🏆 only for a stored matched disc hash with RA ID), and optionally **file format**. Use the **Columns** checkboxes to show/hide columns; preferences are kept in browser local storage. Server-side filters allow verified RA or other/unknown games, title/filename/RA sorting and paging across the collection. These controls also work in read-only guest mode.

**Why some names differ from Excel:** `server/report_excel.py` builds its Game name from RA title → recommended RA title → GameDB title → friendly local title → filename. The current PostgreSQL `library_item` rows expose only `ra_game_title` and filename; the extra GameDB/friendly title selections from report-time audit data are not yet persisted in this table. For unmatched discs the web view first checks GameDB by disc serial and then falls back to a cleaned filename, so some names can remain imperfect. Titles are now resolved using stored RA name, the local GameDB serial-title cache, or a cleaned filename before alphabetical sorting, filtering and pagination. The additional recommended-release/local-audit name fields from Excel are not yet stored in the web database. The correct next improvement is to persist verified GameDB/friendly titles and disc identities during the collection audit/import and sort by a stable indexed display/sort title. Never interpret missing RA data as proof a game is unsupported.

To deploy: `cd ~/retrodb && git pull --ff-only && sudo bash server/deploy.sh`. This is read-only: no ROM or RetroNAS changes.

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

### iPhone Home Screen black screen / Nginx Basic auth

If Safari works but the installed Home Screen app shows a blank screen, investigate the separate standalone web-app context and the Nginx HTTP Basic authentication challenge before altering TLS or certificates. As an immediate workaround on iOS 26, remove the existing Home Screen icon, revisit the HTTPS site in Safari, choose **Share → Add to Home Screen**, and turn **Open as Web App** **off**. This creates a Safari-launching Home Screen shortcut with the RetroDB name/icon, without weakening server authentication.

A fully standalone Home Screen app should use application-managed authenticated sessions (secure cookies, CSRF protection, explicit logout), not rely solely on an HTTP Basic-auth browser challenge. Do not add an unauthenticated Nginx exception for `/` or for app administration to work around this. This behaviour is not yet verified on all iOS versions.

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

Co-Optimus is a promising independent source for **PS2 cooperative player counts** (couch, online, split-screen and LAN). It is not a source of complete competitive multiplayer limits. Bulk import is deliberately postponed because the site's content was not reliably retrievable and provenance/licensing must be respected. See [PS2 multiplayer and least-privilege design](docs/ps2-coop-and-service-security.md).

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

# RetroDB

RetroDB is an open-source, self-hosted catalogue and browser for retro-game collections.

The long-term aim is a fast, secure web front end for a physical game room or private collection: closer to **Plex for locally stored games** than a launcher or ROM-distribution service. It will catalogue what is available, explain how to use each console, and present curated game lists through tablets, phones and QR codes.

> **Project status (October 2026):** working self-hosted backend, PostgreSQL/API health endpoints, read-only PS1/PS2 RetroNAS inventory, RetroAchievements hash audits, GameDB title matching, formatted Excel reports, OPL filename management, and checksum-verified official PS2 patch deployment. The mobile read-only catalogue and HTTPS guest mode are operational; further metadata enrichment and reliable named-user sign-in remain unfinished.

## Vision

RetroDB should eventually:

- catalogue games across many platforms without using console-specific database tables
- distinguish a game from its regional releases, discs and dump/media variants
- map identifiers from sources such as RetroAchievements, Redump, No-Intro, OPL and PSBBN
- record developers, publishers, release dates, regions, languages and historical age ratings
- store external review scores separately from personal ratings and curated collections
- identify locally available files without committing games, ROMs, disc images or copyrighted artwork
- show cover art, synopses, controls, manuals and collection availability
- document physical console instances, modifications, controllers and reset/menu shortcuts
- support child-appropriate and owner-approved collections through a separate policy layer
- provide read-only guest pages suitable for QR codes and a front-desk kiosk
- integrate with an existing RetroNAS installation or run on a separate Linux server
- later provide safe tools for building curated storage media and backing up compatible save devices

The initial reference platforms are **PlayStation and PlayStation 2**, but the data model and provider interfaces will be platform-neutral.

## Guiding principles

### The database is the source of truth

PostgreSQL will store structured metadata and relationships. Large files such as artwork, manuals, metadata snapshots and local game files remain on storage; the database records their location and integrity information.

### One model for every platform

RetroDB will use relationships such as:

```text
Game
└── Release (platform, region, language, edition)
    └── Media (disc, serial, product code, hashes)
        └── Library item (local storage path and availability)
```

Platforms are data, not separate schemas or tables.

### Providers are replaceable

Every upstream source will have its own adapter and follow the same broad pipeline:

```text
fetch → validate → cache → normalise → import
```

Application code should not depend directly on one provider's API or data format.

### Cache responsibly

RetroAchievements and similar community services must not be repeatedly queried during development or ordinary browsing.

RetroDB will keep:

1. an immutable raw response cache
2. a normalised, provider-independent snapshot
3. the local PostgreSQL representation

Normal refreshes should be infrequent—initially every six months for largely static metadata—with manual refresh available. Tests and normal development must use fixtures and never contact upstream services by default.

Cached third-party datasets will not be redistributed until their licences and redistribution permissions have been confirmed.

### Secure by design

- PostgreSQL is local/private-network only and is never published directly.
- Public collection pages are read-only.
- Administration is a separate authenticated surface intended for a trusted network.
- Secrets live outside Git and receive restrictive permissions.
- The application runs as an unprivileged service account.
- RetroDB does not make RetroNAS's legacy protocols safe; a RetroNAS host must remain behind a firewall on a private network.
- No installer will silently expose an Internet-facing service.

## Intended architecture

```text
Browser / kiosk / QR link
          │ HTTPS
          ▼
     Reverse proxy
          │
          ▼
  RetroDB web + API
          │
          ├── PostgreSQL
          ├── background workers
          └── local/NAS storage
                ├── artwork
                ├── manuals
                ├── provider cache
                └── collection files
```

The planned application stack is:

- **Operating system:** Debian Stable (primary), Ubuntu Server LTS (secondary)
- **Database:** PostgreSQL
- **Backend/API:** Python and FastAPI
- **Web UI:** server-rendered templates with lightweight progressive enhancement
- **Service management:** systemd
- **Provisioning:** idempotent Bash bootstrap initially; Ansible role for RetroNAS integration later
- **Reverse proxy:** to be selected and hardened before the first web release

## Why Debian Stable?

RetroNAS currently uses Bash, APT, Ansible and systemd-oriented services. Debian Stable therefore provides the closest standalone development target and the least-friction route to a future RetroNAS installer.

Ubuntu Server LTS remains a sensible VM test platform and will be supported where practical, but RetroDB will avoid becoming Ubuntu-specific.

## Deployment models

### Standalone

RetroDB runs on its own Debian/Ubuntu VM or small server and reads collection storage through a deliberately configured mount. This is the recommended development and security model.

### Alongside RetroNAS

For smaller private home networks, RetroDB may run on the RetroNAS host and use its storage paths directly. The application must still use an unprivileged account, a local database connection and explicit network boundaries.

### Future RetroNAS component

Once the standalone application is mature, `deployment/retronas/` will contain an Ansible role or installer suitable for review and potential integration with RetroNAS. RetroDB will not be built tightly inside RetroNAS first.

## Server build

The starter build script is at:

```text
server/build.sh
```

### Debian host preparation

A minimal Debian installation may not include `sudo`. Sign in with the normal account created during setup, become root, then install `sudo` and grant that account administrative access. Replace `david` if a different username was created:

```bash
su -c 'apt update && apt install -y sudo && /usr/sbin/usermod -aG sudo david'
su -c '/usr/sbin/reboot'
```

Reconnect after the reboot, then fully update the base operating system:

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
sudo reboot
```

Reconnect once more before installing RetroDB.

On a fresh test VM:

```bash
sudo apt install -y git
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb

sudo bash server/build.sh --check
sudo bash server/build.sh
sudo bash server/build.sh --check
```

The first check is read-only. Missing package, service-account and directory warnings are expected on an unprepared host. The build applies the configuration, and the final check verifies that the machine reached the intended state.

The script is designed to be safely rerun. At this stage it:

- supports Debian and Ubuntu through APT
- validates that systemd is available
- installs the initial OS dependencies
- creates an unprivileged `retrodb` service account
- creates application, configuration, data, cache, log and backup directories
- applies restrictive ownership and permissions
- configures PostgreSQL to listen only on loopback
- enables and validates PostgreSQL
- reports what it changed and what remains unimplemented

Normal output shows concise `[RUN]` and `[OK]` status lines. Underlying command output is captured and displayed automatically when a step fails. For live diagnostic output, run:

```bash
sudo bash server/build.sh --verbose
```

The host bootstrap prepares the operating system but does not expose a website. Once its check passes, deploy the v0.1 application foundation:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

The deployment creates the local PostgreSQL role/database, generates protected credentials outside Git, installs the Python environment, applies migrations, starts the hardened systemd service and validates:

```text
http://127.0.0.1:8000/live
http://127.0.0.1:8000/health
```

The application remains loopback-only until an HTTPS reverse proxy and explicit LAN access policy are added.

## Configure RetroAchievements

RetroAchievements credentials are stored only in the protected server file:

```text
/etc/retrodb/retrodb.env
```

The deployment creates a clearly labelled section for the username and **Web API key**. Follow the [RetroAchievements setup guide](docs/retroachievements-setup.md) to obtain the correct key and enter it safely.

Do not put a real API key in Git, screenshots, issues or support messages.

## Connect a RetroNAS collection

RetroDB mounts the standard RetroNAS SMB share read-only for PS1/PS2 inventory and RetroAchievements audits. Explicitly confirmed OPL renames and PS2 patch deployment use a **separate temporary writable SMB mount**, never changing the default read-only audit mount. Follow the [RetroNAS scanning guide](docs/retronas-scanning.md). Credentials remain root-only and collection files are never modified.

### Launch the menus from anywhere

Run this **once** from your checkout as your normal user (it asks for sudo only to write into `/usr/local/bin`):

```bash
cd ~/retrodb
git pull --ff-only origin main
bash server/install-launchers.sh
```

Then from any directory, type `retrodb` for the collection manager or `xerabora` / `xeRAbora` for the xeRAbora installer/profile manager. Arguments are forwarded to the underlying scripts (e.g. `retrodb audit`, `xerabora status`). Both commands use your **current shell user's profile and HOME**, not root's; don't prefix them with `sudo`. The wrappers target this checkout and stay current as you `git pull`. If you move the checkout to a new path, rerun the installer.

Fresh installs now register command-line shortcuts automatically: the RetroDB deployment installs `retrodb` and prints how to launch the menu, while the xeRAbora installer registers `xerabora` / `xeRAbora`. You can still rerun `bash server/install-launchers.sh` manually.

The streamlined RetroDB main menu includes **Audit game collection**, **Patch a PS2 game**, **Rename PS2 games**, and **More options**. The submenu houses export-only reports, local patch downloads, service status and operation journals. Export-only is useful to regenerate a workbook or proposals from an existing audit; it never scans or refreshes hashes. 

**Automatic updates on menu launch:** Typing `retrodb` checks the trusted project's `origin/main` and fast-forwards the repository before showing the menu, if the tracked working tree is clean and the checkout is on `main`. A timeout, offline GitHub connection, local modifications or diverged branch **never causes a forced reset**; RetroDB opens the already-installed menu and prints a warning. Only the interactive menu triggers this check; `retrodb audit` and other non-menu commands do not. This updates checked-out menu/scripts, **not** the deployed backend service under `/opt/retrodb`, which still requires `sudo bash server/deploy.sh` after backend changes. For existing installations, first run `cd ~/retrodb && git pull --ff-only origin main` once to install the new auto-update logic.

### Maintenance from the RetroDB menu

In **More options**, select **6 — Update RetroDB** for a complete, explicitly confirmed application update. It validates the trusted GitHub checkout, pulls clean `main` changes via fast-forward, checks/repairs the required host dependencies when necessary, runs `server/deploy.sh` (including database migrations and a controlled service restart), and validates the health endpoint. The updater does not patch game images, rename ROMs or update xeRAbora itself. The launch-time updater still refreshes only menu/source scripts and never restarts services without confirmation.

Select **7 — Upgrade Debian** for host operating-system maintenance. This refreshes APT metadata, displays a `full-upgrade` **simulation**, requires typing `UPGRADE SYSTEM`, and then runs the actual package upgrade. It does not reboot or autoremove automatically; a required reboot is reported for manual scheduling. System upgrades can interrupt other services, so review the preview and perform them during a maintenance window.

These actions are distinct: the first updates the RetroDB application and its service; the second updates the Debian/Ubuntu host's packages. Both are implemented in `server/maintenance.sh`, and neither runs just because you opened the menu.

### Cross-platform Action Required report

The standard `RetroDB-Compatibility.xlsx` now has an **Action Required** worksheet immediately after Summary, combining PS1, PS2 and any other platforms exported by the report generator. It includes only unresolved games, unverified RA-supported releases, checksum-verified patch opportunities and hash failures that still need action. It excludes verified games, no-set/no-listing games, and redundant entries already covered by a verified copy of the same RA game. Rows are sorted by error, patch, replacement release and identity investigation.

The sheet includes platform, game name, full filename, disc ID, current status, proposed action, recommended release and region, RA ID, an existing verified copy when identifiable, reason, alternative RA candidates, local RA hash, accepted hashes and source path. The original per-platform sheets remain unchanged. Download **`RetroDB-Compatibility.xlsx`** as normal; no additional workbook or command is necessary. A **full audit** refreshes the underlying identity/hash data; export-only recreates the workbook from the previous audit.

## Network and online-play compatibility (initial implementation)

RetroDB now has an **offline-first PS2 online compatibility importer** and a **PS2 Online** sheet in the normal `RetroDB-Compatibility.xlsx` workbook. It stores release-specific source evidence by disc serial, independently of RetroAchievements hashes, and labels absent/unmatched evidence `UNKNOWN` rather than falsely claiming a game lacks online play. This initial importer can explicitly download a CSV snapshot of the [PS2 Online Community's 2026 spreadsheet](https://docs.google.com/spreadsheets/d/15pfhL36qmC-iKr8MNjNXNLwgacG4VOmkfvwVxV5vGzo/edit?gid=0#gid=0); **there is no automatic background internet fetching**.

To populate the workbook, choose **More options → 9) Import PS2 online data → 1) Fetch public community sheet now**. If Google's CSV export cannot be downloaded from your VM, manually export the spreadsheet's first tab (`gid=0`) to CSV, copy it to the VM, and choose **option 2) Import an existing CSV file**. The imported evidence is saved at `~/.cache/retrodb/online-compatibility.json` under the current user's account (not in Git). Choose **More options → 1) Export reports** to rebuild Excel without rehashing the collection. Until an import is performed, the PS2 Online sheet shows your actual local discs but marks network capabilities unknown.

The initial community import captures historical online listing, original service host, community DNS/server labels, reported DNS-playability status, XLink Kai, player counts, co-op, setup requirements and notes. **Native LAN capability is intentionally unknown for now**, rather than guessing from XLink status. A community report of DNS availability is not a guarantee that servers still work today. Exact regional disc serial matching avoids incorrectly asserting that one PAL or NTSC edition shares another release's network support.

### Long-term cross-platform direction

The canonical model will eventually represent **Game → Release → Capabilities → Connection methods → Configuration guides**, with separate source evidence, dates and player-specific achievement progress. This is not PS2-only: Dreamcast (DreamPi/dial-up and community servers), original Xbox (Insignia), Xbox 360, PS3, GameCube, Wii, emulator-specific networking, LAN tunnelling (XLink Kai), DNS redirection and future services should use the same concepts without conflating them. A future frontend will offer console selection, a filterable A–Z game catalogue, detail pages with manuals and controller guidance, service-specific online settings and per-account achievements. These interfaces and additional platform importers are **planned**, not implemented by the initial PS2 Excel importer.

**XLink source availability note (25 October 2026):** The official wiki currently serves an HTTP 200 `application/octet-stream` response of only 229 bytes to the RetroDB VM, with no extractable game list, and its MediaWiki endpoints are similarly unusable. Until reliable direct access can be restored, import option 10 falls back to a **clearly labelled bundled snapshot of 45 identifiable titles from the 56-title official list**. This is partial, not an up-to-date live import. It includes source metadata and can be replaced by a successful direct import later; no unsupported titles are inferred. The importer logs a warning whenever this fallback is used.

### Second source: Team XLink PS2 LAN catalogue

Use **More options → 10) Refresh XLink PS2 LAN** to fetch Team XLink's manually verified PS2 LAN-support list from https://www.teamxlink.co.uk/wiki/PlayStation_2. This is an optional, explicit import and is stored as `~/.cache/retrodb/xlink-ps2.json` alongside the PS2 online/DNS data. The importer refuses a missing or unexpectedly small table instead of overwriting previous data.

XLink's wiki lists titles without disc serials, so RetroDB matches **normalised exact titles** as lower-confidence, title-level evidence. `LAN` and `XLink Kai` will display `YES (title-level)` when such a match is found; this is **not an assurance that every region, disc revision or network setup works**. The PS2 Online sheet contains `Source confidence` and `XLink evidence` fields; `Currently playable` stays `UNVERIFIED`. Use **More options → 1) Export reports** to regenerate Excel after a successful import. Neither import changes game files or the RetroDB service.

### Independent XLink evidence (October 2026)

The **PS2 Online** workbook now preserves two separate XLink observations:
- **Community XLink report**: what the release-specific online/DNS spreadsheet claims.
- **XLink catalogue**: whether the separately imported Team XLink title list contains that game (title-level, never a guaranteed region match).

The **XLink conflict** column flags `REVIEW: community NO / XLink listed` when the sources disagree. **Source confidence** combines the applicable match scopes, including a `partial snapshot` indication when appropriate. The previous aggregate XLink field remains for convenience but should not be used as a claim of verified, currently operational online play.

**Online Summary** now separates community XLink `YES`, XLink catalogue matches, and conflict counts. Refreshing either imported catalogue remains optional; simply **re-export reports** to apply the current code to previously imported data. No ROM or RetroNAS content is modified.

### Online Summary and service evidence

The workbook now contains both **PS2 Online** (one row per local PS2 image) and **Online Summary** (counts and a shortlist of documented online releases). Original historical online support, community DNS reports and XLink Kai reports are different fields; `Currently playable` remains `UNVERIFIED` until separately checked. Neither a community DNS `YES` nor a past online listing proves that a replacement server is live. LAN stays `UNKNOWN` until independently sourced. Connection methods are recorded as structured method labels (e.g. `custom_dns` and `lan_tunnel`) ready for future platform-neutral services such as DreamPi and Insignia.

The Excel writer now supports column labels beyond Z, allowing future capability/evidence fields without truncation. Regenerate the workbook using **More options → 1) Export reports**; no full ROM rehash is required. To refresh the community source records with the latest schema first, use **More options → 9) Import PS2 online data**.

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

## Current collection-management workflow

On a configured Debian host, update and launch the interactive manager:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash server/manager.sh
```

Main-menu **1) Audit games** performs the full eight-stage audit. **More options → 1) Export reports** regenerates reports from the existing audit (no new scan): `~/retrodb-exports/RetroDB-Compatibility.xlsx`, `RetroDB-OPL-Rename-Proposals.xlsx`, the machine-readable OPL rename CSV, and the raw compatibility CSV. Both Excel reports include frozen/filterable headers; the compatibility workbook has Summary, PS1 and PS2 tabs.

Main-menu **2) Patch PS2 game** handles the controlled, checksum-verified patch workflow. The default audit collection mount remains read-only. The patch workflow verifies clean base images before applying any patches, and does not silently replace original ROMs. Only explicitly selected verified output may be deployed through a separate, confirmed operation. Keep original CRT/light-gun disc images: optional *No GunCon Flash* patches are not mandatory for all light-gun games.

Main-menu **3) Rename PS2 games** previews and confirms conservative OPL renames with collision safeguards. **More options** contains report exports, patch downloads, service details, rename recovery, patch journals, application maintenance, Debian upgrades, **8) RetroNAS settings** and **9) Import PS2 online data**.

**RetroNAS settings:** The submenu shows the SMB share, mount status and configuration, allows retrying the existing mount and reading its journal, and can run `server/configure-retronas.sh` after confirmation to change server/share/credentials. **4) Enable reliable on-demand mount at boot** runs `server/enable-retronas-automount.sh`, replacing eager boot-time mounting with a systemd automount. The helper preserves the original SMB 3.1.1 read-only mount definition and protected credentials; the user must confirm because the mount is briefly stopped. Status reports `on-demand`, `mounted`, or `unmounted`. This prevents a DNS-not-ready-at-boot failure from permanently blocking the initial mount, but does not guarantee recovery from every runtime disconnect.

**Patch-stage timing:** Stage 7 prints wall-clock start/end times and elapsed seconds for patch download/cache lookup, source-image checksum verification and the overall stage. Downloads may be reused while checksum verification still reads large ISOs across SMB. Repeated source verification is not yet skipped automatically based on these timings.

After a renaming or patch deployment operation, run a fresh audit; export-only cannot refresh hashes or paths.

Full safeguards, recovery steps and notes are in [Server operations](server/README.md) and [RetroNAS scanning](docs/retronas-scanning.md). Always test games and artwork on the target PS2/OPL-RA setup before removing retained original copies.

## PS2 RetroAchievements and xeRAbora

RetroDB's longer-term goal is not just to catalogue a ROM library, but also to **audit PS1 and PS2 game images against recognised release identifiers and RetroAchievements-supported hashes**. A title being present on RetroNAS does not necessarily mean that its particular region, revision, dump or patched image is compatible with RetroAchievements. RetroDB can help identify those differences, maintain a verified inventory, and eventually prepare a curated collection of compatible images for use on original hardware. This work is separate from the live achievements client.

For actual PS2 gameplay, the intended workflow is:

```text
RetroNAS game collection (canonical/read-only source)
      |
      v
RetroDB inventory, metadata and compatibility/hash checks
      |
      v
Select verified RetroAchievements-compatible game images
      |
      v
Copy to PS2-accessible storage (internal HDD or MMCE)
      |
      v
Real PS2 running a compatible OPL-RA build
      |
      v
Headless xeRAbora on Debian <--> RetroAchievements
```

**Important storage distinction:** In this setup, RetroNAS is the **source library and auditing target**, not the game-loading source for these OPL-RA/MMCE tests. Compatible images need to be **copied to the appropriate PS2-accessible HDD/MMCE storage** before running them. Do not assume that a game catalogued on RetroNAS can be launched directly from that NAS through this workflow. RetroDB's collection management does not itself install games onto the console.

### Standalone xeRAbora installer

The repository also contains a community installer/updater for [xeRAbora by hacan359](https://hacan359.github.io/xerabora/#top):

**[xeRAbora Debian installer, multi-player profile manager and setup guide](integrations/xerabora/README.md)**

It installs the xeRAbora headless client, matching `OPL-RA.ELF`, systemd service and RetroAchievements account configuration on a Debian x86-64 server or VM. The installer includes prerequisite checks, release checksum verification, live per-player logging, multi-profile switching, browser dashboard access (localhost by default, optional trusted-LAN exposure on TCP 18280), service management and a confirmed uninstall option. Startup mode can be set to **Automatic**, **Manual** or **Disabled**: Automatic enables systemd startup after network readiness with a 20-second delay and restarts the client after unexpected exits with a 10-second interval. These settings remain available through the terminal manager.

**This integration is intentionally standalone:** anyone can use it with a fresh Debian host and compatible PS2 **without installing or configuring the RetroDB database, backend, RetroNAS integration or ROM auditing tools**. Likewise, RetroDB can audit and catalogue a collection without xeRAbora. They complement each other rather than requiring one another.

The xeRAbora/OPL-RA integration has been tested on a real PS2 Slim with MemCard Pro 2 in MMCE mode, with game identification and successful achievement unlocks in *Crash of the Titans* and *The Lord of the Rings: The Return of the King*. Two independent RetroAchievements profiles have been switched successfully on the existing Debian VM, with the selected player shown correctly in the xeRAbora Web UI and live achievement progression tracked. A fresh Debian install on a separate clean host remains to be tested. PS2 ELF installation and copying game images to console storage are manual steps.

**Future hardening:** The xeRAbora integration currently runs under the installing Linux account. Optional support for a dedicated, non-interactive, unprivileged xeRAbora service account is planned, but **not yet implemented**; existing installations and profile ownership are unchanged. See the [integration guide](integrations/xerabora/README.md) for details.

## Planned repository layout

```text
retrodb/
├── backend/                 # API, models, services and security
├── frontend/                # templates and static assets
├── providers/               # external metadata adapters
├── workers/                 # sync, artwork and library jobs
├── migrations/              # PostgreSQL schema migrations
├── tests/
│   └── fixtures/            # offline provider fixtures
├── server/                  # standalone host bootstrap
├── deployment/
│   └── retronas/            # future RetroNAS/Ansible integration
├── docs/                    # design and operator documentation
├── .gitignore
└── README.md
```

Empty directories contain placeholder files until implementation begins.

## Initial roadmap

1. Define the PostgreSQL schema for games, releases, media and external identifiers.
2. Add PS1 and PS2 sample records and migrations.
3. Implement the provider contract and offline fixtures.
4. Import a responsibly cached RetroAchievements snapshot.
5. Add local library scanning and storage mappings.
6. Build the read-only web catalogue and search.
7. Add age-rating and owner-approval policy.
8. Add console inventory, instructions and QR-friendly pages.
9. Harden and document administration.
10. Package a standalone release, then build the RetroNAS role.

## Data and legal boundaries

RetroDB is metadata and collection-management software. The repository will not contain ROMs, disc images, BIOS files, copyrighted manuals or unlicensed artwork. Users are responsible for the legality of their own media, backups and imported metadata.

External services retain ownership of their data. Provider modules must respect API terms, licences, attribution requirements and rate limits.

## Contributing

The project is intentionally modular so new platforms and metadata providers can be added without changing the core application. Contribution guidance and coding standards will be added once the initial schema and provider interface are stable.

---

Created by [The Retro Bristolian](https://github.com/theretrobristolian).
