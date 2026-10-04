# RetroNAS collection scanning

RetroDB connects to RetroNAS through a deliberately read-only SMB mount. It never needs RetroNAS root or administrator access.

## Supported layout

RetroNAS exposes its generic collection under the top-level `retronas` share. RetroDB initially inventories:

- `roms/sony/playstation1`
- `roms/sony/playstation2`

These are RetroNAS's canonical generic paths. Symlinked alternative layouts are not traversed, avoiding duplicate inventory records.

## Configure the connection

First install the CIFS client dependency and deploy the current application:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

Then run the guided setup:

```bash
sudo bash server/configure-retronas.sh
```

It asks for the RetroNAS DNS name/IP, SMB share name, username and password. The defaults are share `retronas` and username `pi`; use the values configured on your RetroNAS system.

The password is entered invisibly and stored only in `/etc/retrodb/retronas.credentials`, owned by root with mode `0600`. It never enters Git, the database, a command line or normal logs.

The resulting systemd mount uses SMB 3.1.1 and is forced read-only with `nosuid`, `nodev` and `noexec`. It mounts at `/mnt/retrodb-retronas` and reconnects after reboot.

## Run the inventory

```bash
sudo bash server/retronas.sh scan
```

The inventory reports the exact mount and platform paths, then breaks results down by platform, top-level media folder (for example PS2 `cd` and `dvd`) and file format. Skipped extensions are itemised. Counts are explicitly files rather than games, because a PS1 BIN/CUE pair is two files representing one disc.\n\nIt stores relative path, filename, extension, size, modification time, platform, last-seen time and missing state. It recognises common PS1/PS2 image formats and does not alter or upload collection files.

Other operations:

```bash
sudo bash server/retronas.sh status
sudo bash server/retronas.sh unmount
sudo bash server/retronas.sh mount
```

## Next identification stage

A later scanner stage will calculate the platform-specific RetroAchievements hashes and compare them with the cached provider catalogue. Whole-file SHA/MD5 values are not a substitute for RetroAchievements disc hashing, so this inventory deliberately does not claim compatibility yet.
