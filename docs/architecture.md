# Architecture notes

RetroDB is planned as one modular application with clear trust boundaries.

## Core components

- PostgreSQL stores normalised metadata and local collection state.
- The backend exposes public read-only catalogue routes and separate authenticated administration.
- Workers fetch, validate, cache, normalise and import provider data.
- The web front end uses server-rendered HTML suitable for phones, tablets and kiosks.
- Collection files, artwork and manuals remain on local or NAS storage.

## Network boundary

The database should never be reachable from guest clients. Guest networks receive HTTPS access only to the read-only web surface. Administration, SSH, database access, NAS protocols and RetroNAS management remain on a trusted network.

RetroNAS can expose intentionally old and insecure protocols for real hardware compatibility. Installing RetroDB beside it does not change that risk or make the host suitable for public Internet exposure.

## Data model direction

The first schema will model platforms, games, releases, media, companies, regions, languages, external references, age ratings, review scores, curated collections, local storage, artwork, manuals, console instances and provider sync history.

No platform receives its own game table.
