# PS2 multiplayer evidence and RetroDB least-privilege design

## Co-Optimus as an independent PS2 provider

Reference: https://www.co-optimus.com/games.php?type=online

Co-Optimus tracks **cooperative** play, not all competitive multiplayer. Its separate fields for local/couch co-op, online co-op, combination co-op, split screen, LAN/system-link and player limits are useful, but a blank or missing Co-Optimus listing MUST NOT be interpreted as no multiplayer support. A game such as a competitive racing title may have online multiplayer but no co-op.

Recommended evidence object (future ingestion): `platform`, `game_title`, `region` (if independently evidenced), `disc_id` (only if explicitly evidenced), `local_coop_players`, `online_coop_players`, `combo_coop_players`, `lan_coop_players`, `split_screen`, `co_op_campaign`, `source_url`, `checked_at`, `confidence`. Preserve `null` for unreported, `0` only for explicit documented absence. Do not infer maximum competitive player count from a cooperative limit, or vice versa.

The Co-Optimus listing returned HTTP 403 from the research environment on 25 October 2026; automated bulk scraping is intentionally **not enabled**. Before importing large datasets, establish source-access permission/licensing, canonical PS2 identifiers, rate limits, corrections and provenance. Individual externally verified records can later be added with source-specific citations. It is fine to link to the source now.

## Minimum-privilege service boundaries

| Component | Identity | Capabilities |
|---|---|---|
| Nginx | root master / www-data workers (distribution default) | Handle browser TLS/basic authentication, reverse proxy to local application |
| RetroDB | existing dedicated `retrodb` system account | DB connection, read-only library metadata, service-owned cache directories, no sudo |
| RetroNAS | SMB mount configured read-only | Service account can read permitted game files; no write/rename/delete authority |
| xeRAbora | its existing service account/user | Owns its private profile credentials and process |
| Web administrator (future) | authenticated application identity | Request allowlisted operations with CSRF protection and audit log |
| Privileged task runner (future) | narrowly scoped root-owned unit/helper | Only fixed, validated operations, not arbitrary shell strings or global sudo |

The application stays on `127.0.0.1:8000`, and Nginx is opt-in. Reverse proxy now requires HTTP Basic authentication configured by interactive `htpasswd` bootstrap; **Basic auth over plain HTTP does not protect passwords** against interception. Prefer HTTPS with a trusted AD CS certificate, limit inbound 80/443 to your trusted VLAN, and disable HTTP serving of authenticated content once HTTPS is available. Other direct ports (including the backend, XLink and xeRAbora) need separate firewall review; putting RetroDB behind Nginx does **not** secure those services.

**Browser profile switching not enabled:** xeRAbora's current console switch edits `/etc/systemd/system/xerabora.service.d/profile.conf` and restarts a service. The web process must never gain direct sudo rights. First implement a dedicated helper that accepts only an exact pre-registered profile identifier; isolate profiles under xeRAbora's owner; require POST + CSRF + application login/session, limit operations by user role, reject concurrent requests, log every action, and verify rollback on failure. Explicitly notify users to close PS2 games and reboot/re-pair OPL-RA.

**Browser software updates not enabled:** require signed/trusted update source, change preview, exclusive lock, rollback and service-specific privileges. In particular, never automatically update the xeRAbora binary on CPUs without required instruction sets.

**Certificate note:** Issue a server-auth certificate with `retrodb.it.gattaca.house` as a DNS SAN, deploy a matching private key, install issuing chain, and ensure client trust. Certificate lifecycle/renewal needs explicit ownership. An HTTP/HTTPS toggle in an authenticated app must not be permitted to call shell directly.
