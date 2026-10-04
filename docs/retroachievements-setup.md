# Configure RetroAchievements

RetroDB uses a RetroAchievements **username** and **Web API key** to retrieve catalogue metadata. It does not need your RetroAchievements password or Connect API token.

## 1. Obtain a Web API key

1. Sign in at [RetroAchievements](https://retroachievements.org/).
2. Open your RetroAchievements control panel.
3. Find the **Keys** section.
4. Copy the **Web API Key** value.

The official instructions are available in the [RetroAchievements API getting-started guide](https://api-docs.retroachievements.org/getting-started.html).

Treat the key like a password. Do not paste it into a GitHub issue, commit, screenshot, support message or command output.

## 2. Open the protected RetroDB configuration

On the RetroDB server:

```bash
sudo nano /etc/retrodb/retrodb.env
```

The file is arranged into labelled sections. Find:

```text
# RetroAchievements Web API
RETRODB_RA_USERNAME=
RETRODB_RA_API_KEY=
```

Enter the account username and Web API key after the equals signs:

```text
RETRODB_RA_USERNAME=YourUsername
RETRODB_RA_API_KEY=your-secret-web-api-key
```

Do not add spaces around the equals sign.

In Nano:

- press `Ctrl+O`, then Enter to save
- press `Ctrl+X` to exit

The file is readable only by root and the `retrodb` service group. The real file is outside the Git repository.

## 3. Restart RetroDB

```bash
sudo systemctl restart retrodb
sudo systemctl status retrodb --no-pager
```

Test the credentials without displaying them:

```bash
sudo bash server/retroachievements.sh test
```

A successful test reports only that the connection worked and the number of systems returned. Errors are sanitised so the key is never printed.

## 4. Download the PS1 and PS2 compatibility catalogues

```bash
sudo bash server/retroachievements.sh sync
```

This downloads only games which have achievements, including their recognised hashes. Results are cached beneath `/var/cache/retrodb/providers/retroachievements/` for 180 days so normal runs do not repeatedly call the upstream API.

Use a forced refresh only when you deliberately want current upstream data:

```bash
sudo bash server/retroachievements.sh sync --force
```

The cache contains public catalogue metadata and hashes, never the username or API key.

## Screenshots

Screenshots can be added under:

```text
docs/images/retroachievements/
```

Recommended guide images:

1. RetroAchievements control panel navigation
2. Keys section with the Web API key fully obscured
3. Example RetroDB configuration with fake values
4. Successful connection-test output

Never capture or commit a real API key.
