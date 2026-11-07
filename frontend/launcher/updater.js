const { EventEmitter } = require("node:events");

// Auto-update from GitHub Releases through electron-updater (the packaged
// Windows NSIS build and the Linux AppImage; dev runs and the portable exe are
// never updated).
//
// Linux pacman/deb installs cannot be replaced in place by an unprivileged
// app, so they run in "notify" mode: the newest GitHub release is looked up
// and, when it is newer, the panel and tray offer "Open download page". Nothing
// is downloaded or installed.
//
// Flow: check at start and every few hours -> download in the background ->
// "ready". A ready update is installed
//   - when the user picks "Restart and update" (tray or control panel),
//   - when the app quits (electron-updater autoInstallOnAppQuit),
//   - or by itself once Dota is not running and the control panel is not open
//     (canInstallNow), so an "open and forget" tray app does not stay on an
//     old version for weeks. The app then comes back hidden in the tray.
// Nothing is ever installed while Dota is running.

const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000;
const FIRST_CHECK_DELAY_MS = 15 * 1000;
const IDLE_INSTALL_POLL_MS = 60 * 1000;
// Dota must have been closed this long before an unattended install.
const IDLE_INSTALL_AFTER_MS = 5 * 60 * 1000;

const STATUS = {
  DISABLED: "disabled",
  IDLE: "idle",
  CHECKING: "checking",
  UP_TO_DATE: "up-to-date",
  AVAILABLE: "available", // notify mode: a newer release exists, install it by hand
  DOWNLOADING: "downloading",
  READY: "ready",
  ERROR: "error"
};

function defaultLoadAutoUpdater() {
  return require("electron-updater").autoUpdater;
}

const RELEASES_REPO = "makquella/wardly";
const RELEASES_URL = `https://github.com/${RELEASES_REPO}/releases/latest`;

/**
 * "off" (never updated), "auto" (electron-updater downloads and installs) or
 * "notify" (tell the player, who installs by hand).
 */
function updateModeFor({ platform = process.platform, env = process.env, isPackaged = false, isSmokeTest = false } = {}) {
  if (!isPackaged || isSmokeTest) {
    return "off";
  }
  if (platform === "win32") {
    return env.PORTABLE_EXECUTABLE_DIR ? "off" : "auto";
  }
  if (platform === "linux") {
    // electron-updater replaces the AppImage file itself; a package manager
    // owns every other Linux install.
    return env.APPIMAGE ? "auto" : "notify";
  }
  return "off";
}

// 1 when a is newer than b, -1 when older, 0 when equal (numeric x.y.z, a
// pre-release suffix sorts below the release).
function compareVersions(a, b) {
  const parse = (value) => {
    const [core, pre = ""] = String(value || "").replace(/^v/i, "").split("-", 2);
    return { numbers: core.split(".").map((part) => Number.parseInt(part, 10) || 0), pre };
  };
  const left = parse(a);
  const right = parse(b);
  for (let i = 0; i < Math.max(left.numbers.length, right.numbers.length); i += 1) {
    const diff = (left.numbers[i] || 0) - (right.numbers[i] || 0);
    if (diff !== 0) {
      return diff > 0 ? 1 : -1;
    }
  }
  if (left.pre === right.pre) {
    return 0;
  }
  return left.pre ? -1 : 1;
}

/** The newest published GitHub release: { version, url }, or throws. */
async function fetchLatestRelease({ fetchImpl = globalThis.fetch, repo = RELEASES_REPO, timeoutMs = 10000 } = {}) {
  const response = await fetchImpl(`https://api.github.com/repos/${repo}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "Wardly-update-check" },
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!response.ok) {
    throw new Error(`GitHub answered ${response.status}`);
  }
  const data = await response.json();
  const version = String((data && data.tag_name) || "").replace(/^v/i, "");
  if (!/^\d+\.\d+\.\d+/.test(version)) {
    throw new Error("the latest release has no version tag");
  }
  const url = typeof data.html_url === "string" && data.html_url.startsWith(`https://github.com/${repo}/`) ? data.html_url : RELEASES_URL;
  return { version, url };
}

/**
 * @param {object} options
 * @param {string}   options.currentVersion  app.getVersion()
 * @param {boolean}  options.supported       packaged NSIS build on Windows, or a Linux AppImage / package
 * @param {string}   options.mode            "auto" (default) or "notify": only look for a newer release
 * @param {Function} options.checkLatest     () => Promise<{ version, url }>; the notify-mode lookup (injectable)
 * @param {Function} options.isGameRunning   () => boolean; blocks every install, manual ones too
 * @param {Function} options.canInstallNow   () => boolean; extra condition for the unattended install (panel hidden…)
 * @param {Function} options.beforeInstall   ({ unattended }) => void; e.g. remember to restart hidden
 * @param {Function} options.loadAutoUpdater () => electron-updater autoUpdater (injectable for tests)
 */
function createUpdater({
  currentVersion = "0.0.0",
  supported = false,
  mode = "auto",
  checkLatest = fetchLatestRelease,
  isGameRunning = () => false,
  canInstallNow = () => false,
  beforeInstall = () => {},
  loadAutoUpdater = defaultLoadAutoUpdater,
  log = () => {},
  now = () => Date.now()
} = {}) {
  const emitter = new EventEmitter();
  let autoUpdater = null;
  let checkTimer = null;
  let idleTimer = null;
  let firstCheckTimer = null;
  let idleSince = null;
  let installing = false;
  let state = {
    supported,
    status: supported ? STATUS.IDLE : STATUS.DISABLED,
    currentVersion,
    mode,
    version: "",
    url: "",
    percent: 0,
    error: "",
    checkedAt: null
  };

  function update(patch) {
    const next = { ...state, ...patch };
    const changed = Object.keys(next).some((key) => next[key] !== state[key]);
    state = next;
    if (changed) {
      emitter.emit("change", emitter.getState());
    }
  }

  function wire(updater) {
    updater.autoDownload = true;
    updater.autoInstallOnAppQuit = true;
    updater.allowPrerelease = false;
    updater.allowDowngrade = false;
    updater.disableWebInstaller = true; // the full NSIS installer, never a web one
    updater.logger = {
      info: (message) => log(String(message)),
      warn: (message) => log(`warn: ${message}`),
      error: (message) => log(`error: ${message}`),
      debug: () => {}
    };
    updater.on("checking-for-update", () => {
      if (state.status !== STATUS.READY && state.status !== STATUS.DOWNLOADING) {
        update({ status: STATUS.CHECKING, error: "" });
      }
    });
    updater.on("update-available", (info) => {
      log(`Update ${info?.version || "?"} is available; downloading.`);
      update({ status: STATUS.DOWNLOADING, version: String(info?.version || ""), percent: 0, error: "" });
    });
    updater.on("update-not-available", () => {
      update({ status: STATUS.UP_TO_DATE, checkedAt: now(), error: "" });
    });
    updater.on("download-progress", (progress) => {
      const percent = Math.max(0, Math.min(100, Math.round(Number(progress?.percent) || 0)));
      update({ status: STATUS.DOWNLOADING, percent });
    });
    updater.on("update-downloaded", (info) => {
      log(`Update ${info?.version || state.version} downloaded; it installs on restart.`);
      update({ status: STATUS.READY, version: String(info?.version || state.version), percent: 100, checkedAt: now() });
    });
    updater.on("error", (error) => {
      log(`Update error: ${error?.message || error}`);
      // A failed check must not hide an update that is already downloaded.
      if (state.status !== STATUS.READY) {
        update({ status: STATUS.ERROR, error: String(error?.message || error || "unknown error"), checkedAt: now() });
      }
    });
  }

  // Notify mode: no electron-updater, just "is the newest release newer?".
  async function checkNotify() {
    if (state.status === STATUS.CHECKING) {
      return emitter.getState();
    }
    const previous = state.status;
    update({ status: STATUS.CHECKING, error: "" });
    try {
      const latest = await checkLatest();
      if (compareVersions(latest.version, currentVersion) > 0) {
        log(`Version ${latest.version} is available (notify only).`);
        update({ status: STATUS.AVAILABLE, version: latest.version, url: latest.url || RELEASES_URL, checkedAt: now(), error: "" });
      } else {
        update({ status: STATUS.UP_TO_DATE, version: "", url: "", checkedAt: now(), error: "" });
      }
    } catch (error) {
      log(`Update check failed: ${error.message}`);
      // A known newer version stays offered if the lookup fails later.
      update({
        status: previous === STATUS.AVAILABLE ? STATUS.AVAILABLE : STATUS.ERROR,
        error: previous === STATUS.AVAILABLE ? "" : String(error.message || error),
        checkedAt: now()
      });
    }
    return emitter.getState();
  }

  async function check() {
    if (mode === "notify") {
      return checkNotify();
    }
    if (!autoUpdater || installing) {
      return emitter.getState();
    }
    if (state.status === STATUS.DOWNLOADING || state.status === STATUS.READY) {
      return emitter.getState();
    }
    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      // Also reported through the "error" event; keep the promise quiet.
      if (state.status !== STATUS.ERROR && state.status !== STATUS.READY) {
        update({ status: STATUS.ERROR, error: String(error?.message || error), checkedAt: now() });
      }
    }
    return emitter.getState();
  }

  function install({ unattended = false } = {}) {
    if (!autoUpdater || state.status !== STATUS.READY || installing) {
      return false;
    }
    if (isGameRunning()) {
      // Installing restarts the app and stops the overlay: never mid-game.
      log("Update install postponed: Dota is running.");
      return false;
    }
    installing = true;
    log(`Installing update ${state.version}${unattended ? " (Dota is closed, installing in the background)" : ""}.`);
    try {
      beforeInstall({ unattended });
    } catch (error) {
      log(`beforeInstall failed: ${error.message}`);
    }
    // isSilent: no installer UI; isForceRunAfter: start the app again.
    autoUpdater.quitAndInstall(true, true);
    return true;
  }

  function idleTick() {
    if (state.status !== STATUS.READY || installing) {
      idleSince = null;
      return;
    }
    if (isGameRunning() || !canInstallNow()) {
      idleSince = null;
      return;
    }
    if (idleSince === null) {
      idleSince = now();
      return;
    }
    if (now() - idleSince >= IDLE_INSTALL_AFTER_MS) {
      install({ unattended: true });
    }
  }

  // The scheduled lookups stay quiet while Dota runs; a manual one does not.
  function scheduledCheck() {
    if (mode === "notify" && isGameRunning()) {
      return undefined;
    }
    return check();
  }

  // The page of the newer release; never while Dota runs (a browser over the game).
  function openDownload(open) {
    if (state.status !== STATUS.AVAILABLE || !state.url) {
      return false;
    }
    if (isGameRunning()) {
      log("Download page postponed: Dota is running.");
      return false;
    }
    open(state.url);
    return true;
  }

  emitter.start = () => {
    if (supported && mode === "notify") {
      if (!firstCheckTimer) {
        firstCheckTimer = setTimeout(scheduledCheck, FIRST_CHECK_DELAY_MS);
        checkTimer = setInterval(scheduledCheck, CHECK_INTERVAL_MS);
        for (const timer of [firstCheckTimer, checkTimer]) {
          timer.unref?.();
        }
      }
      return;
    }
    if (!supported || autoUpdater) {
      return;
    }
    try {
      autoUpdater = loadAutoUpdater();
    } catch (error) {
      log(`Auto-update is unavailable: ${error.message}`);
      update({ supported: false, status: STATUS.DISABLED, error: error.message });
      return;
    }
    wire(autoUpdater);
    firstCheckTimer = setTimeout(check, FIRST_CHECK_DELAY_MS);
    checkTimer = setInterval(check, CHECK_INTERVAL_MS);
    idleTimer = setInterval(idleTick, IDLE_INSTALL_POLL_MS);
    for (const timer of [firstCheckTimer, checkTimer, idleTimer]) {
      timer.unref?.();
    }
  };

  emitter.stop = () => {
    clearTimeout(firstCheckTimer);
    clearInterval(checkTimer);
    clearInterval(idleTimer);
  };

  emitter.check = check;
  emitter.install = install;
  emitter.openDownload = openDownload;
  emitter.idleTick = idleTick;
  emitter.getState = () => ({ ...state });
  return emitter;
}

module.exports = {
  createUpdater,
  UPDATE_STATUS: STATUS,
  RELEASES_URL,
  IDLE_INSTALL_AFTER_MS,
  compareVersions,
  fetchLatestRelease,
  updateModeFor
};
