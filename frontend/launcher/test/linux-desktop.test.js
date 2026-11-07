const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  applyStartupSwitches,
  appMenuContent,
  autostartContent,
  createXdgAutostart,
  ensureAppImageIntegration,
  execLine,
  launcherPath,
  parseDesktopEntry,
  quoteExecArg
} = require("../linux-desktop");

function tempHome(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-home-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function fakeCommandLine(initial = {}) {
  const switches = { ...initial };
  return {
    switches,
    hasSwitch: (name) => name in switches,
    getSwitchValue: (name) => switches[name] || "",
    appendSwitch: (name, value = "") => {
      switches[name] = value;
    }
  };
}

test("startup switches: X11 by default, speech-dispatcher always, Linux only", () => {
  const commandLine = fakeCommandLine();
  const chosen = applyStartupSwitches({ commandLine, platform: "linux", env: { DISPLAY: ":0", XDG_SESSION_TYPE: "wayland" } });
  assert.equal(commandLine.switches["ozone-platform"], "x11");
  assert.ok("enable-speech-dispatcher" in commandLine.switches);
  assert.deepEqual(chosen, { display: "x11", session: "wayland" });

  const win = fakeCommandLine();
  assert.equal(applyStartupSwitches({ commandLine: win, platform: "win32", env: {} }), null);
  assert.deepEqual(win.switches, {});
});

test("startup switches: WARDLY_WAYLAND=1, a user's --ozone-platform and a Wayland-only session are respected", () => {
  const wayland = fakeCommandLine();
  applyStartupSwitches({ commandLine: wayland, platform: "linux", env: { DISPLAY: ":0", WARDLY_WAYLAND: "1" } });
  assert.equal("ozone-platform" in wayland.switches, false);
  assert.equal(wayland.switches["ozone-platform-hint"], "auto");

  const own = fakeCommandLine({ "ozone-platform": "wayland" });
  const chosen = applyStartupSwitches({ commandLine: own, platform: "linux", env: { DISPLAY: ":0" } });
  assert.equal(own.switches["ozone-platform"], "wayland");
  assert.match(chosen.display, /wayland/);

  const pure = fakeCommandLine();
  applyStartupSwitches({ commandLine: pure, platform: "linux", env: { WAYLAND_DISPLAY: "wayland-0" } });
  assert.equal("ozone-platform" in pure.switches, false, "forcing X11 without an X display would abort Electron");
});

test("Exec arguments are quoted per the Desktop Entry specification", () => {
  assert.equal(quoteExecArg("/opt/Wardly/wardly"), "/opt/Wardly/wardly");
  assert.equal(quoteExecArg("--hidden"), "--hidden");
  assert.equal(quoteExecArg("/home/user/My Apps/Wardly.AppImage"), '"/home/user/My Apps/Wardly.AppImage"');
  // $ gets a backslash, which the file format doubles: "a\\$b" on disk.
  assert.equal(quoteExecArg("a$b"), '"a\\\\$b"');
  assert.equal(quoteExecArg("100%"), "100%%");
  assert.equal(quoteExecArg(""), '""');
  assert.equal(execLine(["/a b/x", "--hidden"]), '"/a b/x" --hidden');
});

test("the quoting round-trips through the spec's two unescape layers", () => {
  // File-level unescape (\\ -> \), then Exec-level: inside quotes \" \` \$ \\ -> the character.
  function unquote(value) {
    const file = value.replace(/\\\\/g, "\\");
    const match = file.match(/^"(.*)"$/s);
    const body = match ? match[1] : file;
    return body.replace(/\\(["`$\\])/g, "$1").replace(/%%/g, "%");
  }
  for (const arg of ['/p/Wardly Beta.AppImage', 'a"b', "a`b", "a$b", "a\\b", "a b\\\"$`%", "(x)&y;z"]) {
    assert.equal(unquote(quoteExecArg(arg)), arg, arg);
  }
});

test("the launcher path is the AppImage file when there is one, else the executable", () => {
  assert.equal(launcherPath({ env: { APPIMAGE: "/h/Wardly.AppImage" }, execPath: "/tmp/.mount_x/wardly" }), "/h/Wardly.AppImage");
  assert.equal(launcherPath({ env: {}, execPath: "/opt/Wardly/wardly" }), "/opt/Wardly/wardly");
});

test("autostart: enable writes the entry with --hidden, disable removes it, state is read back", (t) => {
  const home = tempHome(t);
  const env = { HOME: home, APPIMAGE: path.join(home, "Apps dir", "Wardly.AppImage") };
  const autostart = createXdgAutostart({ platform: "linux", env, execPath: "/tmp/.mount_x/wardly" });
  assert.equal(autostart.file, path.join(home, ".config", "autostart", "wardly.desktop"));
  assert.equal(autostart.isEnabled(), false);

  assert.equal(autostart.set(true), true);
  const entry = parseDesktopEntry(fs.readFileSync(autostart.file, "utf8"));
  assert.equal(entry.Name, "Wardly");
  assert.equal(entry.Exec, `"${env.APPIMAGE}" --hidden`);
  assert.equal(entry.Terminal, "false");
  assert.equal(autostart.isEnabled(), true);

  assert.equal(autostart.set(false), false);
  assert.equal(fs.existsSync(autostart.file), false);
  assert.equal(autostart.set(false), false, "turning off twice is fine");
});

test("autostart: XDG_CONFIG_HOME, the desktop's own off switches and execPath without an AppImage", (t) => {
  const home = tempHome(t);
  const config = path.join(home, "cfg");
  const autostart = createXdgAutostart({ platform: "linux", env: { HOME: home, XDG_CONFIG_HOME: config }, execPath: "/opt/Wardly/wardly" });
  assert.equal(autostart.file, path.join(config, "autostart", "wardly.desktop"));
  autostart.set(true);
  assert.equal(parseDesktopEntry(fs.readFileSync(autostart.file, "utf8")).Exec, "/opt/Wardly/wardly --hidden");

  const on = autostartContent({ command: "/opt/Wardly/wardly" });
  fs.writeFileSync(autostart.file, on.replace("X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-enabled=false"));
  assert.equal(autostart.isEnabled(), false, "switched off in GNOME settings");
  fs.writeFileSync(autostart.file, on.replace("Terminal=false", "Terminal=false\nHidden=true"));
  assert.equal(autostart.isEnabled(), false, "Hidden=true, as KDE writes it");
  fs.writeFileSync(autostart.file, on);
  assert.equal(autostart.isEnabled(), true);
});

test("autostart: refresh repoints an enabled entry when the AppImage moved, and leaves a disabled one alone", (t) => {
  const home = tempHome(t);
  const first = createXdgAutostart({ platform: "linux", env: { HOME: home, APPIMAGE: "/old/Wardly.AppImage" } });
  first.set(true);
  const moved = createXdgAutostart({ platform: "linux", env: { HOME: home, APPIMAGE: "/new/Wardly.AppImage" } });
  assert.equal(moved.refresh(), true);
  assert.equal(parseDesktopEntry(fs.readFileSync(moved.file, "utf8")).Exec, "/new/Wardly.AppImage --hidden");
  assert.equal(moved.refresh(), false, "already current");
  moved.set(false);
  assert.equal(moved.refresh(), false);
  assert.equal(fs.existsSync(moved.file), false);
});

test("autostart: off Linux nothing is touched, and a read-only home is logged, not thrown", (t) => {
  const home = tempHome(t);
  const win = createXdgAutostart({ platform: "win32", env: { HOME: home } });
  assert.equal(win.supported, false);
  assert.equal(win.set(true), false);
  assert.equal(fs.existsSync(path.join(home, ".config")), false);

  const logs = [];
  const broken = createXdgAutostart({
    platform: "linux",
    env: { HOME: home },
    log: (message) => logs.push(message),
    fsImpl: {
      ...fs,
      mkdirSync: () => {
        throw new Error("EROFS");
      }
    }
  });
  assert.equal(broken.set(true), false);
  assert.match(logs[0], /EROFS/);
});

test("AppImage integration writes the menu entry and icon, idempotently, and follows a moved file", (t) => {
  const home = tempHome(t);
  const icon = path.join(home, "icon-src.png");
  fs.writeFileSync(icon, Buffer.from([137, 80, 78, 71, 1, 2, 3]));
  const env = { HOME: home, APPIMAGE: "/home/u/Apps/Wardly-0.65.0-x86_64.AppImage" };
  const desktop = path.join(home, ".local", "share", "applications", "wardly.desktop");
  const iconFile = path.join(home, ".local", "share", "icons", "hicolor", "256x256", "apps", "wardly.png");

  assert.deepEqual(ensureAppImageIntegration({ platform: "linux", env, iconSource: icon }), { desktop: true, icon: true });
  const entry = parseDesktopEntry(fs.readFileSync(desktop, "utf8"));
  assert.equal(entry.Name, "Wardly");
  assert.equal(entry.Exec, env.APPIMAGE);
  assert.equal(entry.TryExec, env.APPIMAGE);
  assert.equal(entry.Icon, "wardly");
  assert.equal(entry.Categories, "Game;");
  assert.equal(entry.StartupWMClass, "wardly");
  assert.deepEqual(fs.readFileSync(iconFile), fs.readFileSync(icon));

  assert.deepEqual(ensureAppImageIntegration({ platform: "linux", env, iconSource: icon }), { desktop: false, icon: false });

  const moved = { ...env, APPIMAGE: "/home/u/New Place/Wardly.AppImage" };
  assert.deepEqual(ensureAppImageIntegration({ platform: "linux", env: moved, iconSource: icon }), { desktop: true, icon: false });
  assert.equal(parseDesktopEntry(fs.readFileSync(desktop, "utf8")).Exec, '"/home/u/New Place/Wardly.AppImage"');
  assert.equal(fs.readdirSync(path.dirname(desktop)).filter((name) => name.endsWith(".tmp")).length, 0);
});

test("AppImage integration is skipped for package installs, other systems, and honours XDG_DATA_HOME", (t) => {
  const home = tempHome(t);
  const none = { desktop: false, icon: false };
  assert.deepEqual(ensureAppImageIntegration({ platform: "linux", env: { HOME: home } }), none, "pacman/deb: no APPIMAGE");
  assert.deepEqual(ensureAppImageIntegration({ platform: "win32", env: { HOME: home, APPIMAGE: "/x" } }), none);
  assert.equal(fs.existsSync(path.join(home, ".local")), false);

  const data = path.join(home, "xdg-data");
  ensureAppImageIntegration({ platform: "linux", env: { HOME: home, APPIMAGE: "/x/W.AppImage", XDG_DATA_HOME: data } });
  assert.equal(fs.existsSync(path.join(data, "applications", "wardly.desktop")), true);
});

test("AppImage integration survives a missing icon and an unwritable folder", (t) => {
  const home = tempHome(t);
  const logs = [];
  const result = ensureAppImageIntegration({
    platform: "linux",
    env: { HOME: home, APPIMAGE: "/x/W.AppImage" },
    iconSource: path.join(home, "missing.png"),
    log: (message) => logs.push(message)
  });
  assert.equal(result.icon, false);
  assert.ok(logs.some((line) => line.includes("icon")));
  assert.match(appMenuContent({ appImage: "/x/W.AppImage" }), /^\[Desktop Entry\]/);
});
