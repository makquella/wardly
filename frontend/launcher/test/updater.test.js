const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const {
  RELEASES_URL,
  compareVersions,
  createUpdater,
  fetchLatestRelease,
  IDLE_INSTALL_AFTER_MS,
  UPDATE_STATUS,
  updateModeFor
} = require("../updater");

function fakeAutoUpdater() {
  const updater = new EventEmitter();
  updater.checks = 0;
  updater.installs = [];
  updater.checkForUpdates = async () => {
    updater.checks += 1;
  };
  updater.quitAndInstall = (...args) => updater.installs.push(args);
  return updater;
}

function started(options = {}) {
  const fake = fakeAutoUpdater();
  let clock = 1000;
  const updater = createUpdater({
    currentVersion: "0.1.0",
    supported: true,
    loadAutoUpdater: () => fake,
    now: () => clock,
    ...options
  });
  updater.start();
  updater.stop();
  return { updater, fake, advance: (ms) => (clock += ms) };
}

test("unsupported builds never load electron-updater", () => {
  let loaded = false;
  const updater = createUpdater({ supported: false, loadAutoUpdater: () => (loaded = true) });
  updater.start();
  updater.stop();
  assert.equal(loaded, false);
  assert.equal(updater.getState().status, UPDATE_STATUS.DISABLED);
});

test("a missing electron-updater module disables updates instead of crashing", () => {
  const updater = createUpdater({
    supported: true,
    loadAutoUpdater: () => {
      throw new Error("Cannot find module 'electron-updater'");
    }
  });
  updater.start();
  updater.stop();
  assert.equal(updater.getState().status, UPDATE_STATUS.DISABLED);
  assert.equal(updater.getState().supported, false);
});

test("events move the state from checking to ready", async () => {
  const { updater, fake } = started();
  assert.equal(fake.autoDownload, true);
  assert.equal(fake.autoInstallOnAppQuit, true);
  assert.equal(fake.disableWebInstaller, true);
  const states = [];
  updater.on("change", (state) => states.push(state.status));

  await updater.check();
  assert.equal(fake.checks, 1);
  fake.emit("checking-for-update");
  fake.emit("update-available", { version: "0.2.0" });
  fake.emit("download-progress", { percent: 41.6 });
  assert.equal(updater.getState().percent, 42);
  fake.emit("update-downloaded", { version: "0.2.0" });

  assert.deepEqual(states, ["checking", "downloading", "downloading", "ready"]);
  assert.equal(updater.getState().version, "0.2.0");
  // While an update is downloaded, further checks do nothing.
  await updater.check();
  assert.equal(fake.checks, 1);
});

test("an error after download keeps the ready update", () => {
  const { updater, fake } = started();
  fake.emit("update-downloaded", { version: "0.2.0" });
  fake.emit("error", new Error("net::ERR_INTERNET_DISCONNECTED"));
  assert.equal(updater.getState().status, UPDATE_STATUS.READY);
});

test("check errors are reported, not thrown", async () => {
  const { updater, fake } = started();
  fake.checkForUpdates = async () => {
    throw new Error("HttpError: 404");
  };
  const state = await updater.check();
  assert.equal(state.status, UPDATE_STATUS.ERROR);
  assert.match(state.error, /404/);
});

test("install runs only when an update is ready, silently and relaunching", () => {
  const seen = [];
  const { updater, fake } = started({ beforeInstall: (info) => seen.push(info) });
  assert.equal(updater.install(), false);
  fake.emit("update-downloaded", { version: "0.2.0" });
  assert.equal(updater.install(), true);
  assert.deepEqual(fake.installs, [[true, true]]);
  assert.deepEqual(seen, [{ unattended: false }]);
  assert.equal(updater.install(), false);
});

test("unattended install waits until Dota has been closed for a while", () => {
  let idle = false;
  const seen = [];
  const { updater, fake, advance } = started({
    canInstallNow: () => idle,
    beforeInstall: (info) => seen.push(info)
  });
  fake.emit("update-downloaded", { version: "0.2.0" });

  updater.idleTick();
  advance(IDLE_INSTALL_AFTER_MS * 2);
  updater.idleTick();
  assert.equal(fake.installs.length, 0, "never while Dota runs");

  idle = true;
  updater.idleTick();
  advance(IDLE_INSTALL_AFTER_MS - 1);
  updater.idleTick();
  assert.equal(fake.installs.length, 0);

  idle = false;
  updater.idleTick();
  idle = true;
  updater.idleTick();
  advance(IDLE_INSTALL_AFTER_MS);
  updater.idleTick();
  assert.equal(fake.installs.length, 1);
  assert.deepEqual(seen, [{ unattended: true }]);
});

test("no install while Dota runs, manual or unattended", () => {
  let gameRunning = true;
  const { updater, fake, advance } = started({ isGameRunning: () => gameRunning, canInstallNow: () => true });
  fake.emit("update-downloaded", { version: "0.2.0" });

  assert.equal(updater.install(), false, "manual install is refused mid-game");
  updater.idleTick();
  advance(IDLE_INSTALL_AFTER_MS * 2);
  updater.idleTick();
  assert.equal(fake.installs.length, 0);

  gameRunning = false;
  assert.equal(updater.install(), true);
  assert.equal(fake.installs.length, 1);
});

// --- Linux: AppImage updates itself, pacman/deb only notify -------------------

test("the update mode per platform and install kind", () => {
  const base = { isPackaged: true, env: {} };
  assert.equal(updateModeFor({ ...base, platform: "win32" }), "auto");
  assert.equal(updateModeFor({ ...base, platform: "win32", env: { PORTABLE_EXECUTABLE_DIR: "C:\\x" } }), "off");
  assert.equal(updateModeFor({ ...base, platform: "linux", env: { APPIMAGE: "/home/u/Wardly.AppImage" } }), "auto");
  assert.equal(updateModeFor({ ...base, platform: "linux" }), "notify", "pacman, deb, unpacked");
  assert.equal(updateModeFor({ ...base, platform: "darwin" }), "off");
  assert.equal(updateModeFor({ ...base, platform: "linux", isSmokeTest: true }), "off");
  assert.equal(updateModeFor({ platform: "linux", env: { APPIMAGE: "/x" }, isPackaged: false }), "off", "dev runs");
});

test("versions compare numerically, a pre-release is older than its release", () => {
  assert.equal(compareVersions("0.65.0", "0.64.9"), 1);
  assert.equal(compareVersions("0.64.10", "0.64.9"), 1);
  assert.equal(compareVersions("v0.64.0", "0.64.0"), 0);
  assert.equal(compareVersions("0.64", "0.64.0"), 0);
  assert.equal(compareVersions("0.63.9", "0.64.0"), -1);
  assert.equal(compareVersions("0.65.0-beta.1", "0.65.0"), -1);
});

function notifier(options = {}) {
  let latest = { version: "0.65.0", url: "https://github.com/makquella/wardly/releases/tag/v0.65.0" };
  const fake = fakeAutoUpdater();
  const updater = createUpdater({
    currentVersion: "0.64.0",
    supported: true,
    mode: "notify",
    loadAutoUpdater: () => {
      throw new Error("notify mode must not load electron-updater");
    },
    checkLatest: async () => {
      if (latest instanceof Error) throw latest;
      return latest;
    },
    ...options
  });
  return { updater, fake, set: (value) => (latest = value) };
}

test("notify mode offers the download page of a newer release and never installs", async () => {
  const { updater } = notifier();
  updater.start();
  updater.stop();
  assert.equal(updater.getState().mode, "notify");
  const state = await updater.check();
  assert.equal(state.status, UPDATE_STATUS.AVAILABLE);
  assert.equal(state.version, "0.65.0");
  assert.match(state.url, /^https:\/\/github\.com\/makquella\/wardly\//);
  assert.equal(updater.install(), false);
  const opened = [];
  assert.equal(updater.openDownload((url) => opened.push(url)), true);
  assert.deepEqual(opened, [state.url]);
});

test("notify mode: up to date, a failed lookup, and a lookup that fails after one succeeded", async () => {
  const { updater, set } = notifier();
  set({ version: "0.64.0", url: RELEASES_URL });
  assert.equal((await updater.check()).status, UPDATE_STATUS.UP_TO_DATE);
  assert.equal(updater.openDownload(() => assert.fail("nothing to open")), false);

  set(new Error("offline"));
  const failed = await updater.check();
  assert.equal(failed.status, UPDATE_STATUS.ERROR);
  assert.match(failed.error, /offline/);

  set({ version: "0.66.0", url: RELEASES_URL });
  assert.equal((await updater.check()).status, UPDATE_STATUS.AVAILABLE);
  set(new Error("offline"));
  const kept = await updater.check();
  assert.equal(kept.status, UPDATE_STATUS.AVAILABLE, "a known newer version is not hidden");
  assert.equal(kept.version, "0.66.0");
});

test("notify mode: the download page is not opened while Dota runs, and scheduled checks wait", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  let running = true;
  let lookups = 0;
  const { updater } = notifier({
    isGameRunning: () => running,
    checkLatest: async () => {
      lookups += 1;
      return { version: "0.65.0", url: RELEASES_URL };
    }
  });
  updater.start();
  t.after(() => updater.stop());
  t.mock.timers.tick(15 * 1000);
  await Promise.resolve();
  assert.equal(lookups, 0, "no scheduled lookup mid-game");
  await updater.check(); // a manual one is fine
  assert.equal(lookups, 1);
  assert.equal(updater.openDownload(() => assert.fail("not mid-game")), false);
  running = false;
  assert.equal(updater.openDownload(() => {}), true);
});

test("the GitHub lookup reads the tag and keeps only links into the repository", async () => {
  const reply = (body, ok = true, status = 200) => async () => ({ ok, status, json: async () => body });
  assert.deepEqual(
    await fetchLatestRelease({ fetchImpl: reply({ tag_name: "v0.65.1", html_url: "https://github.com/makquella/wardly/releases/tag/v0.65.1" }) }),
    { version: "0.65.1", url: "https://github.com/makquella/wardly/releases/tag/v0.65.1" }
  );
  assert.equal(
    (await fetchLatestRelease({ fetchImpl: reply({ tag_name: "0.65.1", html_url: "https://evil.example/x" }) })).url,
    RELEASES_URL
  );
  await assert.rejects(fetchLatestRelease({ fetchImpl: reply({}, false, 403) }), /403/);
  await assert.rejects(fetchLatestRelease({ fetchImpl: reply({ tag_name: "nightly" }) }), /version tag/);
});
