# Linux Packaging

Wardly ships on Linux (x86_64) as the same desktop app as on Windows: an Electron launcher with the bundled PyInstaller backend, an always-on-top overlay, a tray icon and voice advice. Target: Arch / CachyOS (KDE Plasma), but the formats run on any mainstream distro.

| Format | File | For | Updates |
|---|---|---|---|
| AppImage | `Wardly-<v>-x86_64.AppImage` | any distro | in place (electron-updater, `latest-linux.yml`) |
| pacman | `Wardly-<v>-x86_64.pacman` | Arch, CachyOS, Manjaro | the app only tells that a new version exists and opens the release page |
| deb | `Wardly_<v>_amd64.deb` | Debian, Ubuntu, Mint | same as pacman |

The website downloads go through the counted redirect `https://api.luhovyimvp.dev/d/<source>?os=linux` (also `linux-pacman`, `linux-deb`; Windows without `os`), which sends to the asset of the latest release, or to the releases page while that release has no Linux packages yet.

## Install

- **Arch / CachyOS:** `sudo pacman -U Wardly-<v>-x86_64.pacman`. Optional: `speech-dispatcher espeak-ng` (voices), `xorg-xprop xorg-xwininfo` (Dota window tracking), `libayatana-appindicator` (tray on GNOME).
- **Debian / Ubuntu / Mint:** `sudo apt install ./Wardly_<v>_amd64.deb` (recommends `speech-dispatcher`, `x11-utils`, `libayatana-appindicator3-1`).
- **AppImage:** `chmod +x Wardly-<v>-x86_64.AppImage && ./Wardly-<v>-x86_64.AppImage`. The AppImage runtime electron-builder 26 uses by default (legacy toolset) needs **FUSE 2** on the host: Arch/CachyOS `sudo pacman -S fuse2`, Ubuntu 22.04 `libfuse2`, Ubuntu 24.04 `libfuse2t64`. Without it run `./Wardly-….AppImage --appimage-extract-and-run`. (electron-builder also has a beta static-runtime toolset, `toolsets.appimage` 1.0.3, that does not need libfuse2; it is not used here yet.)
- **Ubuntu 24.04 and AppArmor:** the kernel blocks unprivileged user namespaces for unknown apps, so Chromium's sandbox cannot start. The AppImage launcher detects this and adds `--no-sandbox` by itself; the deb ships an AppArmor profile (electron-builder's default). Nothing to do.

Inside Dota 2 use **borderless window** mode (Settings → Video), as on Windows: Dota runs on XWayland and an overlay cannot sit over exclusive fullscreen.

## Wayland, X11 and the overlay

The launcher starts Electron with `--ozone-platform=x11` unless `WARDLY_WAYLAND=1` is set: native Wayland windows cannot stay on top of other windows, and Dota itself runs through XWayland. On a Wayland session (KDE default) the overlay therefore runs under XWayland. Transparent windows need a compositor (KDE, GNOME and most others have one).

Focus and position of the Dota window come from `xprop` and `xwininfo`. Without them the app still works (Dota is found by its process) but cannot hide the overlay when Dota loses focus. Arch: `xorg-xprop xorg-xwininfo`; Debian/Ubuntu: `x11-utils`.

## Voice

Spoken advice uses Chromium's speech synthesis through `speech-dispatcher`. Install it with a voice: Arch `speech-dispatcher espeak-ng`, Debian/Ubuntu `speech-dispatcher espeak-ng`. Ukrainian needs an extra voice such as RHVoice. Without a voice the settings show a hint.

## Tray

KDE Plasma and most desktops show the tray icon. GNOME needs the *AppIndicator and KStatusNotifierItem Support* extension. Closing the window hides the app to the tray.

## Where data lives

```text
~/.config/DotaAICoach/            <- $XDG_CONFIG_HOME/DotaAICoach, owner-only (0700): backend data, logs, recordings
~/.config/DotaAICoach/player_data/coach.sqlite3   <- owner-only (0600)
~/.config/autostart/wardly.desktop                <- only when "start with the system" is on
```

This is the same folder the source checkout fallback always used, so nothing moves. The launcher keeps its settings in Electron's user data folder (also under `$XDG_CONFIG_HOME`).

## Secrets are not sealed by the OS

Windows seals the AI-coach and OpenDota keys with DPAPI. Linux has no equivalent for a plain desktop app, so the backend keeps its keys unsealed (`SecretBox.kind == "none"`; protection is the owner-only folder and database file). The launcher seals its own secret settings only when Electron's `safeStorage` uses a real keyring (libsecret/kwallet); the `basic_text` fallback (no keyring running) counts as "not available" and nothing claims sealing. The privacy page says so.

## Build

Build on the oldest glibc you want to support; CI and releases use `ubuntu-22.04`, so the PyInstaller backend runs on older distros too.

Prerequisites: Python 3.11+, Node.js 22.12+, `bsdtar` and `zstd` (Ubuntu/Debian `libarchive-tools zstd`, Arch `libarchive zstd`; for the pacman target), `xvfb` for the smoke test, `dpkg-deb`. electron-builder downloads its tools (fpm, AppImage runtime) from GitHub on first use.

```bash
scripts/build-linux.sh            # backend (PyInstaller), npm ci, AppImage + pacman + deb
scripts/build-linux.sh --skip-backend --targets "AppImage"   # frontend-only rebuild
scripts/smoke-linux.sh
```

Output in `frontend/launcher/dist/`: the three packages, `latest-linux.yml` (AppImage feed; the blockmap is embedded in the AppImage) and `linux-unpacked/wardly`. The pacman package is compressed with zstd (needs pacman 5.2+).

`scripts/smoke-linux.sh` checks: the backend alone (`/health`, auth, session records under a throw-away `XDG_CONFIG_HOME`, 0700/0600 permissions, graceful stdin shutdown, exit 0); `linux-unpacked/wardly --smoke-test` and the AppImage (`--appimage-extract-and-run`, no FUSE needed) under `xvfb-run`, with no backend left behind; `latest-linux.yml` and `app-update.yml`; and the pacman/deb contents and metadata. It does not cover a real desktop, the overlay over Dota, the tray or Dota's GSI.

CI (`linux-build` in `ci.yml`, same scope rule as Windows) builds and smokes on every desktop-relevant change; `release.yml` job `linux` builds again and adds `latest-linux.yml`, the AppImage, the pacman and the deb to the release the Windows job created.

## Limits

- x86_64 only; no code signing; no Flatpak/Snap/rpm yet.
- pacman and deb packages get no in-place update.
- Only verified in headless builds (Xvfb); real Dota, tray and overlay behaviour on KDE/GNOME still needs a manual check.
