const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// Linux desktop glue, free of Electron imports so it is unit-tested with plain
// `node --test` and temporary directories:
//   - startup switches (X11/XWayland overlay, speech-dispatcher voices);
//   - XDG autostart (Electron's login items do nothing on Linux);
//   - AppImage menu integration (a .desktop file and an icon for the app menu).
// Everything is a no-op off Linux and never throws: a read-only home or a
// missing folder must not stop the launcher.

const APP_NAME = "Wardly";
const DESKTOP_FILE = "wardly.desktop";
const ICON_NAME = "wardly";
// Must match the window class the app gets (the product name).
const WM_CLASS = "Wardly";

const COMMENT_EN = "A local Dota 2 coach: advice over the game and match reviews";
const COMMENT_UK = "Локальний тренер Dota 2: підказки поверх гри та розбір матчів";

function isLinux(platform = process.platform) {
  return platform === "linux";
}

/**
 * Chromium switches that must be set before the app is ready.
 *  - The overlay is a transparent always-on-top window. Native Wayland gives
 *    no always-on-top over other windows, and Dota itself runs on XWayland, so
 *    Electron is started on X11/XWayland unless WARDLY_WAYLAND=1 (or the user
 *    passed --ozone-platform themselves). Without any X display (a pure
 *    Wayland session) forcing X11 would make Electron abort, so Wayland stays.
 *  - speech-dispatcher gives speechSynthesis the system voices.
 * Returns what was chosen, for the log.
 */
function applyStartupSwitches({ commandLine, platform = process.platform, env = process.env } = {}) {
  if (!isLinux(platform) || !commandLine) {
    return null;
  }
  let display;
  if (commandLine.hasSwitch("ozone-platform")) {
    display = `${commandLine.getSwitchValue("ozone-platform") || "custom"} (--ozone-platform)`;
  } else if (env.WARDLY_WAYLAND === "1") {
    commandLine.appendSwitch("ozone-platform-hint", "auto");
    display = "auto (WARDLY_WAYLAND=1)";
  } else if (!env.DISPLAY && env.WAYLAND_DISPLAY) {
    display = "wayland (no X display for XWayland)";
  } else {
    commandLine.appendSwitch("ozone-platform", "x11");
    display = "x11";
  }
  commandLine.appendSwitch("enable-speech-dispatcher");
  return { display, session: env.XDG_SESSION_TYPE || "" };
}

// --- Desktop Entry quoting ---------------------------------------------------
// https://specifications.freedesktop.org/desktop-entry-spec/latest/exec-variables.html
// An argument with a reserved character is wrapped in double quotes; inside
// them " ` $ \ get a backslash. The file format then reads backslashes as
// escapes again, so each one is doubled once more. A literal % is %%.
const RESERVED = /[\s"'\\<>~|&;$*?#()`]/;

function quoteExecArg(arg) {
  const text = String(arg).replace(/%/g, "%%");
  if (text !== "" && !RESERVED.test(text)) {
    return text;
  }
  const escaped = text.replace(/(["`$\\])/g, "\\$1");
  return `"${escaped.replace(/\\/g, "\\\\")}"`;
}

function execLine(argv) {
  return argv.map(quoteExecArg).join(" ");
}

/** What starts this app: the AppImage file itself, else the executable. */
function launcherPath({ env = process.env, execPath = process.execPath } = {}) {
  return env.APPIMAGE ? env.APPIMAGE : execPath;
}

function homeOf(env) {
  return env.HOME || os.homedir();
}

function configHome(env) {
  return env.XDG_CONFIG_HOME && path.isAbsolute(env.XDG_CONFIG_HOME)
    ? env.XDG_CONFIG_HOME
    : path.join(homeOf(env), ".config");
}

function dataHome(env) {
  return env.XDG_DATA_HOME && path.isAbsolute(env.XDG_DATA_HOME)
    ? env.XDG_DATA_HOME
    : path.join(homeOf(env), ".local", "share");
}

function writeAtomic(fsImpl, file, content, mode = 0o644) {
  fsImpl.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  try {
    fsImpl.writeFileSync(temp, content, { mode });
    fsImpl.renameSync(temp, file);
  } catch (error) {
    try {
      fsImpl.rmSync(temp, { force: true });
    } catch {
      // Nothing left to clean.
    }
    throw error;
  }
}

function readText(fsImpl, file) {
  try {
    return fsImpl.readFileSync(file, "utf8");
  } catch {
    return null;
  }
}

/** Key=value pairs of the [Desktop Entry] group (first occurrence wins). */
function parseDesktopEntry(text) {
  const values = {};
  let inEntry = false;
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    if (line.startsWith("[")) {
      inEntry = line === "[Desktop Entry]";
      continue;
    }
    const at = line.indexOf("=");
    if (inEntry && at > 0) {
      const key = line.slice(0, at).trim();
      if (!(key in values)) {
        values[key] = line.slice(at + 1).trim();
      }
    }
  }
  return values;
}

// --- XDG autostart -----------------------------------------------------------

function autostartFile(env = process.env) {
  return path.join(configHome(env), "autostart", DESKTOP_FILE);
}

function autostartContent({ command }) {
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Version=1.0",
    `Name=${APP_NAME}`,
    `Comment=${COMMENT_EN}`,
    `Comment[uk]=${COMMENT_UK}`,
    `Exec=${execLine([command, "--hidden"])}`,
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    ""
  ].join("\n");
}

/**
 * Start with the system through ~/.config/autostart/wardly.desktop.
 * "Enabled" means the file exists and the desktop's own switches (Hidden=true,
 * X-GNOME-Autostart-enabled=false, set by the system settings) do not turn it
 * off. Turning it off removes the file.
 */
function createXdgAutostart({
  platform = process.platform,
  env = process.env,
  execPath = process.execPath,
  fsImpl = fs,
  log = () => {}
} = {}) {
  const file = autostartFile(env);
  const supported = isLinux(platform);

  function isEnabled() {
    if (!supported) {
      return false;
    }
    const text = readText(fsImpl, file);
    if (text === null) {
      return false;
    }
    const entry = parseDesktopEntry(text);
    return (
      String(entry.Hidden || "").toLowerCase() !== "true" &&
      String(entry["X-GNOME-Autostart-enabled"] || "").toLowerCase() !== "false"
    );
  }

  function expected() {
    return autostartContent({ command: launcherPath({ env, execPath }) });
  }

  function set(enabled) {
    if (!supported) {
      return false;
    }
    try {
      if (enabled) {
        writeAtomic(fsImpl, file, expected());
      } else {
        fsImpl.rmSync(file, { force: true });
      }
    } catch (error) {
      log(`Autostart could not be ${enabled ? "enabled" : "disabled"}: ${error.message}`);
    }
    return isEnabled();
  }

  /** The AppImage moved or was replaced: point an enabled entry at the new path. */
  function refresh() {
    if (!supported || !isEnabled()) {
      return false;
    }
    if (readText(fsImpl, file) === expected()) {
      return false;
    }
    try {
      writeAtomic(fsImpl, file, expected());
      log(`Autostart entry now starts ${launcherPath({ env, execPath })}.`);
      return true;
    } catch (error) {
      log(`Autostart entry could not be refreshed: ${error.message}`);
      return false;
    }
  }

  return { file, supported, isEnabled, set, refresh };
}

// --- AppImage menu integration -----------------------------------------------

function appMenuContent({ appImage }) {
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Version=1.0",
    `Name=${APP_NAME}`,
    "GenericName=Dota 2 coach",
    `Comment=${COMMENT_EN}`,
    `Comment[uk]=${COMMENT_UK}`,
    `Exec=${execLine([appImage])}`,
    `TryExec=${appImage}`,
    `Icon=${ICON_NAME}`,
    "Terminal=false",
    "Categories=Game;",
    `StartupWMClass=${WM_CLASS}`,
    ""
  ].join("\n");
}

/**
 * A pacman/deb install ships its own .desktop file; an AppImage does not, so it
 * would be missing from the app menu. When running as an AppImage (APPIMAGE is
 * set) write ~/.local/share/applications/wardly.desktop and the 256 px icon,
 * and rewrite them when the AppImage was moved or replaced. Idempotent: files
 * that already match are left alone. Returns what was written.
 */
function ensureAppImageIntegration({
  platform = process.platform,
  env = process.env,
  iconSource,
  fsImpl = fs,
  log = () => {}
} = {}) {
  const written = { desktop: false, icon: false };
  if (!isLinux(platform) || !env.APPIMAGE) {
    return written;
  }
  const data = dataHome(env);
  const desktopPath = path.join(data, "applications", DESKTOP_FILE);
  const iconPath = path.join(data, "icons", "hicolor", "256x256", "apps", `${ICON_NAME}.png`);
  try {
    const content = appMenuContent({ appImage: env.APPIMAGE });
    if (readText(fsImpl, desktopPath) !== content) {
      writeAtomic(fsImpl, desktopPath, content);
      written.desktop = true;
    }
  } catch (error) {
    log(`App menu entry could not be written: ${error.message}`);
  }
  try {
    if (iconSource) {
      const icon = fsImpl.readFileSync(iconSource);
      let current = null;
      try {
        current = fsImpl.readFileSync(iconPath);
      } catch {
        // Not there yet.
      }
      if (!current || !current.equals(icon)) {
        writeAtomic(fsImpl, iconPath, icon);
        written.icon = true;
      }
    }
  } catch (error) {
    log(`App icon could not be written: ${error.message}`);
  }
  if (written.desktop || written.icon) {
    log(`App menu integration updated (${Object.keys(written).filter((key) => written[key]).join(", ")}).`);
  }
  return written;
}

module.exports = {
  DESKTOP_FILE,
  applyStartupSwitches,
  appMenuContent,
  autostartContent,
  autostartFile,
  createXdgAutostart,
  ensureAppImageIntegration,
  execLine,
  launcherPath,
  parseDesktopEntry,
  quoteExecArg
};
