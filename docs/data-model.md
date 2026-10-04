# Core data model

Migration `0001_initial_core_schema` establishes the first durable RetroDB catalogue structure.

## Entity hierarchy

```text
Game
└── Release
    ├── Platform
    ├── Region
    ├── Publisher
    ├── Languages
    └── Media
        ├── Disc number
        ├── Serial / product code
        └── CRC32 / MD5 / SHA-1
```

A game is the abstract work. A release is a platform, region and edition-specific publication. Media represents an identifiable disc or other dump variant belonging to that release.

## Initial tables

- `platform`
- `company`
- `region`
- `language`
- `game`
- `release`
- `release_language`
- `media`
- `external_provider`
- `external_reference`

`external_reference` maps a provider identifier to exactly one game, release or media record. This avoids pretending that RetroAchievements, Redump and No-Intro share one universal identifier.

## Seed data

The migration creates only stable reference data:

- Sony PlayStation
- Sony PlayStation 2
- Europe, United Kingdom, Japan and United States
- English and Japanese
- RetroAchievements, Redump and No-Intro provider definitions

No sample or copyrighted game metadata is inserted by the migration.

## API proof

After deployment:

```bash
curl -s http://127.0.0.1:8000/api/v1/platforms | jq
```

returns the PS1 and PS2 platform rows through the application and database stack.
