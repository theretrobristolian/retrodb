# RetroNAS collection scanning

RetroDB will inventory an existing collection without requiring administrative access to RetroNAS.

## Intended access model

Use one of these restricted, read-only approaches:

1. mount a dedicated read-only SMB share on the RetroDB host
2. mount a read-only NFS export restricted to the RetroDB host
3. use a dedicated SFTP account confined to the collection path

Do not store a RetroNAS administrator or root credential in RetroDB.

## Initial inventory

The scanner will collect:

- storage-relative path
- filename and extension
- file size
- modification time
- hashes required by the relevant platform/provider
- disc serial or product code where it can be extracted safely
- archive membership without modifying source files

It will not upload game images to RetroAchievements or another metadata provider.

## RetroAchievements matching

The first PS1 and PS2 workflow will:

1. obtain and cache supported RetroAchievements games and hashes
2. scan local collection files from the read-only mount
3. apply the correct platform-specific identification method
4. classify each item as matched, ambiguous, unsupported or unreadable
5. show which local files are compatible and which alternative dump/release is required

Provider metadata will be refreshed infrequently and tests will use local fixtures.
