const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  clipboard,
  dialog,
  ipcMain,
  nativeImage,
  net: electronNet,
  Notification,
  protocol,
  safeStorage,
  screen,
  shell
} = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const { SCHEME: DOTA_ASSET_SCHEME, createAssetHandler } = require("./dota-assets");
const {createHistoryTransfer} = require("./history-transfer");
const discordPresence = require("./discord-presence");
const discordWeekly = require("./discord-weekly");
const adviceStats = require("./advice-stats");
const friends = require("./friends");
const { createSecretCodec } = require("./secret-codec");
const { createDotaWatcher } = require("./dota-watcher");
const { createOverlayController, OVERLAY_DEFAULTS } = require("./overlay-window");
const { createSkillArrowController } = require("./skill-arrow-window");
const {
  PRIVACY_URL,
  apiUrl,
  buildReport,
  isRetryable,
  outboxOverflow,
  reportFileName,
  uploadPayload,
  withNote
} = require("./problem-report");
const { parseConfig, pruneSent, rememberSent, sendRecording, uploadOffered } = require("./match-upload");
const { DOTA_STATUS, dotaStatus, overlayVisibility } = require("./overlay-visibility");
const OverlayVoice = require("./overlay/voice");
// Voice lines in the launcher log per session (overlay:voice-event).
const VOICE_LOG_LIMIT = 30;
const { createSettingsStore } = require("./settings");
const { loadLocalApiAuth, controlHeaders, renderGsiConfig } = require("./local-api");
const { trustedHandlers, protectWindow } = require("./renderer-security");
const {
  DOTA_STEAM_URL,
  GSI_LAUNCH_OPTION,
  checkLaunchOptions,
  dotaDirFromExecutable,
  gsiDirForDotaDir,
  locateDota
} = require("./steam-locator");
const { createUpdater, fetchLatestRelease, updateModeFor, UPDATE_STATUS } = require("./updater");
const linuxDesktop = require("./linux-desktop");

const APP_ID = "com.dotaai.coach";
const APP_NAME = "Wardly";
// Shared with the frozen backend (backend/app/config.py -> %APPDATA%\DotaAICoach).
const APP_DATA_DIR_NAME = "DotaAICoach";

// Linux: the overlay needs X11/XWayland (see linux-desktop.js); before "ready".
const linuxStartup = linuxDesktop.applyStartupSwitches({ commandLine: app.commandLine });

app.setName(APP_NAME);
app.setPath("userData", path.join(app.getPath("appData"), APP_DATA_DIR_NAME));
app.setPath("sessionData", path.join(app.getPath("userData"), "electron"));

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const IS_PACKAGED = app.isPackaged;
const RESOURCES_ROOT = IS_PACKAGED ? process.resourcesPath : REPO_ROOT;
const BACKEND_DIR = path.join(REPO_ROOT, "backend");
const USER_DATA_DIR = app.getPath("userData");
let apiAuth = null;

function localApiAuth() {
  if (!apiAuth) apiAuth = loadLocalApiAuth(path.join(USER_DATA_DIR, "local-api-gsi.json"));
  return apiAuth;
}
// Mirrors WRITABLE_DIR in backend/app/config.py.
const WRITABLE_DIR = IS_PACKAGED ? USER_DATA_DIR : BACKEND_DIR;
const LOGS_DIR = path.join(WRITABLE_DIR, "logs");
const SESSION_RECORDS_DIR = path.join(WRITABLE_DIR, "session_records");
const SIMULATION_RESULTS_DIR = path.join(WRITABLE_DIR, "simulation_results");
const LAUNCHER_LOG_PATH = path.join(USER_DATA_DIR, "logs", "launcher.log");
const README_PATH = path.join(RESOURCES_ROOT, "README.md");
const ICON_DIR = path.join(__dirname, "assets");

const BACKEND_HOST = "127.0.0.1";
const PREFERRED_BACKEND_PORT = 8000;
const BACKEND_HEALTH_TIMEOUT_MS = 45000;
const BACKEND_GRACEFUL_STOP_MS = 8000;
// Linux/macOS: time for SIGTERM to work before SIGKILL.
const SIGTERM_GRACE_MS = 3000;
const BACKEND_MAX_RESTARTS = 3;
const BACKEND_RESTART_WINDOW_MS = 2 * 60 * 1000;
const GSI_STATUS_POLL_MS = 1000;
const GSI_CONFIG_NAME = "gamestate_integration_dota_ai_coach.cfg";
// --bg in assets/ui/tokens.css
const WINDOW_BACKGROUND = "#0b0b0c";

const START_HIDDEN = process.argv.includes("--hidden");
const SMOKE_TEST_RESULT = argValue("--smoke-test");
const IS_SMOKE_TEST = SMOKE_TEST_RESULT !== null;
// Functional history fixtures must never enter the installed/developer store.
const SMOKE_PLAYER_DATA_DIR = IS_SMOKE_TEST ? fs.mkdtempSync(path.join(os.tmpdir(), "wardly-player-smoke-")) : null;

const DEMO_PRESETS = {
  plMacro: {
    label: "Phantom Lancer 20-30 macro",
    fileName: "replay_gsi_like_match_8843382732_pl_20_30.jsonl"
  },
  juggSafety: {
    label: "Juggernaut 10-20 safety",
    fileName: "replay_gsi_like_match_8843471434_jugg_10_20.jsonl"
  }
};

const settings = createSettingsStore(path.join(USER_DATA_DIR, "settings.json"), {
  backendPort: null,
  gsiConfigPath: "",
  gsiAutoInstalled: false,
  trayHintShown: false,
  // "The overlay is visible for me" on the exclusive-fullscreen warning.
  fullscreenWarningDismissed: false,
  // Set before an update installs so the relaunched app returns the way it was.
  startHiddenOnce: false,
  updatedFrom: "",
  // First-run checklist on Home: the first GSI data seen, and "hide" pressed.
  gsiSeenAt: "",
  setupDismissed: false,
  // Version whose "What's new" card is still to be shown (set by an update).
  whatsNewPending: "",
  // The version the last update came from: the card lists what every
  // skipped version brought too.
  whatsNewFrom: "",
  // Matches played with the app and reviewed (the invite card on Home shows from
  // the third), and whether the card was answered (copied or «not now»).
  liveReviews: 0,
  inviteDone: false,
  // The first-run tour of the panel was shown (finished or skipped).
  tourDone: false,
  // The Home card asking to share anonymous statistics was answered (yes or no);
  // the answer itself is `shareStats`, changeable in Settings → App.
  statsAsked: false,
  // Opt-in statistics (advice-stats.js): launches and crashes per local day (last
  // 10 days), the advice-mark totals already sent, and the first-run facts the
  // checklist cannot see itself: when the app was installed, the first live
  // advice, the sample card shown. `sessionOpen` stays true while the app runs,
  // so a start that finds it set counts the last exit as unclean.
  statsDaily: {},
  statsMarksSent: null,
  installedAt: 0,
  firstAdviceAt: "",
  overlayPreviewed: false,
  sessionOpen: false,
  // «Підсумок вечора»: the sitting whose card was closed, and the one the tray told about.
  sessionSeen: "",
  sessionNotified: "",
  // How often coaching advice may appear: calm | normal | active (backend scheduler).
  adviceFrequency: "normal",
  // Position for map timers and role tips (auto = from the lane), and the timers switch.
  adviceRole: "auto",
  mapHints: true,
  // «Друзі» (friends.js): the published profile card (id = friend code, the
  // token only this launcher has) and the friends' codes; off until the player
  // shows the profile.
  friendsProfile: { enabled: false, id: "", token: "", showMmr: true, url: "", hash: "", at: 0 },
  friends: [],
  // A week of match recordings on this computer (backend match_records.py), off by default.
  matchRecords: false,
  // Recordings sent to the developer by consent: {local id: {id: "S-XXXXXX", sentAt}},
  // forgotten after the 60 days the server keeps them (match-upload.js).
  sentRecords: {},
  // Rich Presence on the player's Discord profile («Матч на Juggernaut · з тренером Wardly»).
  discordPresence: true,
  // The week in Discord: the player's channel webhook link (discord-weekly.js),
  // the end (ms) of the last calendar week handled, and the last post's result.
  discordWebhook: "",
  discordWeeklyLast: 0,
  discordWeeklyStatus: null,
  // Opt-in anonymous statistics (advice-stats.js): off by default; the end (ms) of
  // the last local day sent, when it was sent, and the day Dota ran in exclusive fullscreen.
  shareStats: false,
  statsLastDay: 0,
  // Nothing before this moment (ms) is counted: switching on, or a server delete.
  statsSince: 0,
  statsSentAt: "",
  fullscreenSeenDay: "",
  // UI language: auto (system) | uk | en.
  language: "auto",
  overlay: { ...OVERLAY_DEFAULTS }
}, {
  // Delete tokens, the profile token and the webhook: sealed on disk (DPAPI).
  secretKeys: ["shares", "friendsProfile", "discordWebhook", "deviceKey"],
  codec: createSecretCodec(safeStorage)
});
// Versions before 0.54 offered Russian («ru»); a player who picked it gets Ukrainian.
const LEGACY_CYRILLIC_LANGUAGE = "ru";
if (settings.get("language") === LEGACY_CYRILLIC_LANGUAGE) {
  settings.set("language", "uk");
}

let mainWindow = null;
let splashWindow = null;
let splashFinishing = false;
let tray = null;
let isQuitting = false;
let shutdownPromise = null;
let shutdownComplete = false;

const processes = {
  backend: null,
  demo: null
};
const processStatus = {
  backend: "stopped",
  demo: "stopped"
};
const lastExit = {};
const stoppingProcesses = new Set();
const backend = {
  port: null,
  startPromise: null,
  restarts: []
};
let mode = "Live GSI";
let gsiStatus = { status: "unknown", path: "" };
let logs = "";
let logMode = "clean";
let hiddenBackendAccessLogs = 0;
let currentDemoPreset = "";
let recordingStatus = "stopped";
let launcherLogStream = null;
let dotaInstall = { steamRoots: [], libraries: [], dotaDir: "", gsiDir: "", source: "not searched" };
// Does Dota start with -gamestateintegration (read from Steam's saved settings)?
let launchOptions = { state: "unknown", accountId: null };
let dotaInstallLogged = false;
let dotaLocatePromise = null;
let autoInstallRunning = false;
const live = {
  inMatch: false,
  postGame: false,
  pollTimer: null,
  polling: false,
  details: emptyLiveDetails(),
  recentAdvice: [],
  polls: 0,
  player: null
};
// Match id of the last "review ready" balloon; a click on it opens that review.
// What a click on the latest tray balloon opens: {type: "open-match", matchId},
// {type: "open-home"} or null (just the panel). Every balloon sets it anew.
let balloonAction = null;
const presence = { status: DOTA_STATUS.NOT_FOUND, visible: false, reason: "", code: "" };
let autostartEnabled = false;
// Problem reports waiting in the outbox (sent again later).
let outboxCount = 0;
let fullscreenBalloonShown = false;
let fullscreenWarningShown = false;

const BACKEND_NOISE_PATTERNS = [
  /GET\s+\/overlay\/recommendation\b/,
  /POST\s+\/demo\/replay-state\b/,
  /POST\s+\/gsi\b/
];

const overlay = createOverlayController({
  settings,
  getBackend: backendInfo,
  getLocale: () => uiLocale(),
  getDotaRect: () => dotaWatcher.getState().windowRect,
  onChange: () => {
    refreshPresence();
    updateStatus();
    refreshTray();
  },
  log: (message) => appendLog("overlay", message, { force: true })
});

// The arrow over the ability to level, on Dota's own ability bar (0.43).
const skillArrows = createSkillArrowController({
  settings,
  getDotaRect: () => dotaWatcher.getState().windowRect,
  getLocale: () => uiLocale(),
  log: (message) => appendLog("overlay", message, { force: true })
});

const dotaWatcher = createDotaWatcher({
  log: (message) => appendLog("dota", message, { force: true })
});
let dotaWasRunning = false;
let sessionTimer = null;
const SESSION_NOTICE_DELAY_MS = 3 * 60 * 1000;
dotaWatcher.on("change", (state) => {
  appendLog(
    "dota",
    state.running ? `dota2 running, ${state.focused ? "focused" : "in background"}` : "dota2 not running"
  );
  if (state.running && !dotaWasRunning) {
    // The player may have just added the launch option in Steam.
    refreshLaunchOptions();
    clearTimeout(sessionTimer);
  }
  if (!state.running && dotaWasRunning) {
    // Dota closed: once the last review had time to be written, tell about the evening.
    clearTimeout(sessionTimer);
    sessionTimer = setTimeout(() => notifySession().catch(() => {}), SESSION_NOTICE_DELAY_MS);
  }
  dotaWasRunning = state.running;
  if (state.running && !dotaInstall.dotaDir && dotaDirFromExecutable(state.exePath)) {
    // The running game tells us where it is installed, even outside known libraries.
    autoInstallGsiOnce().catch((error) => appendLog("gsi", error.message, { force: true }));
  }
  // Follow Dota to its monitor / window (no-op when nothing moved).
  overlay.refreshPlacement();
  noteExclusiveFullscreen(state);
  refreshPresence();
  // The status screen shows the process/focus state itself, so push it even
  // when overlay visibility and the tray status did not change.
  updateStatus();
  if (fullscreenWarningActive() !== fullscreenWarningShown) {
    fullscreenWarningShown = fullscreenWarningActive();
    refreshTray();
  }
});

const UPDATE_MODE = updateModeFor({ isPackaged: IS_PACKAGED, isSmokeTest: IS_SMOKE_TEST });
const updater = createUpdater({
  currentVersion: app.getVersion(),
  // Windows NSIS build and the Linux AppImage update themselves; Linux
  // pacman/deb installs only announce a newer release. The portable exe and dev
  // runs are not updated.
  supported: UPDATE_MODE !== "off",
  mode: UPDATE_MODE === "notify" ? "notify" : "auto",
  checkLatest: () => fetchLatestRelease({ fetchImpl: (...args) => electronNet.fetch(...args) }),
  // Never while Dota runs or a match feeds GSI (manual installs included).
  isGameRunning,
  // The unattended install also waits for the demo and a hidden panel.
  canInstallNow: () =>
    processStatus.demo !== "running" && !(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible()),
  beforeInstall: ({ unattended }) => {
    const panelOpen = Boolean(mainWindow && !mainWindow.isDestroyed() && mainWindow.isVisible());
    settings.set("startHiddenOnce", unattended || !panelOpen);
    settings.set("updatedFrom", app.getVersion());
  },
  log: (message) => appendLog("update", message, { force: true })
});
updater.on("change", () => {
  updateStatus();
  refreshTray();
});

// ---------------------------------------------------------------------------
// Tray texts (Ukrainian or English, by system locale)
// ---------------------------------------------------------------------------

const TRAY_TEXT = {
  en: {
    open: "Open",
    overlay: "Advice over the game",
    autostartWindows: "Start with Windows",
    autostartSystem: "Start with the system",
    autostartLogin: "Start at login",
    quit: "Quit",
    backend: "Coach",
    backendStates: { running: "running", starting: "starting…", stopping: "stopping…", stopped: "stopped" },
    [DOTA_STATUS.NOT_FOUND]: "Dota not found",
    [DOTA_STATUS.WAITING]: "Waiting for game",
    [DOTA_STATUS.IN_GAME]: "In game",
    gsiInstalled: "Wardly is connected to Dota 2.",
    restartDota: "Restart Dota 2 to connect.",
    fullscreenMenu: "Advice hidden by exclusive fullscreen",
    fullscreenBalloon:
      "Dota runs in exclusive fullscreen, so advice cannot be drawn over it. In Dota: Settings → Video → Display mode → Borderless window. Or turn on spoken advice in the app.",
    updateDownloading: (version, percent) => `Downloading update ${version}… ${percent}%`,
    updateReady: (version) => `Restart and update to ${version}`,
    updateAvailable: (version) => `Version ${version} is out: open the download page`,
    trayHint:
      "Still running in the tray. Right-click the icon to toggle the overlay or quit. No tray icon (GNOME)? Install the AppIndicator extension, or start Wardly again to open the window.",
    fullscreenBalloonLinux:
      "Dota runs in fullscreen, and the window manager draws it above every other window, so advice cannot be drawn over it. In Dota: Settings → Video → Display mode → Borderless window. Or turn on spoken advice in the app.",
    updateAfterGame: (version) => `Update ${version} installs after you close Dota`,
    updated: (version) => `Updated to ${version}.`,
    reviewReady: (score, focusMet) =>
      `Post-match review is ready${score ? `: score${score}` : ""}.${focusMet === true ? " Your focus: done." : focusMet === false ? " Your focus: it happened again." : ""} Click to open it.`,
    sessionReady: (games, wins, losses, score) =>
      `Your evening: ${games} matches, ${wins}–${losses}${score !== null && score !== undefined ? `, average score ${score}` : ""}. Click to see it and copy it for friends.`,
    problemReport: "Save a problem report",
    lastReview: (score) => `Latest match review${score !== null && score !== undefined ? ` · ${score}/100` : ""}`,
    reportSentLater: (id) => `Your problem report was sent. Number: ${id}.`,
    voice: "Voice",
    voice_off: "Off",
    voice_urgent: "Urgent advice",
    voice_all: "All advice"
  },
  uk: {
    open: "Відкрити",
    overlay: "Підказки поверх гри",
    autostartWindows: "Автозапуск із Windows",
    autostartSystem: "Автозапуск із системою",
    autostartLogin: "Автозапуск під час входу",
    quit: "Вихід",
    backend: "Тренер",
    backendStates: { running: "працює", starting: "запускається…", stopping: "зупиняється…", stopped: "зупинено" },
    [DOTA_STATUS.NOT_FOUND]: "Доту не знайдено",
    [DOTA_STATUS.WAITING]: "Чекаємо на гру",
    [DOTA_STATUS.IN_GAME]: "У грі",
    gsiInstalled: "Wardly підключено до Dota 2.",
    restartDota: "Перезапустіть Dota 2.",
    fullscreenMenu: "Підказок не видно: повноекранний режим",
    fullscreenBalloon:
      "Дота запущена в ексклюзивному повноекранному режимі — поверх нього підказки не малюються. У Доті: Налаштування → Відео → режим екрана «Вікно без рамки» (Borderless window). Або ввімкніть озвучення порад у застосунку.",
    updateDownloading: (version, percent) => `Завантажується оновлення ${version}… ${percent}%`,
    updateReady: (version) => `Перезапустити й оновити до ${version}`,
    updateAvailable: (version) => `Вийшла версія ${version}: відкрити сторінку завантаження`,
    trayHint:
      "Працює в треї. Клацніть правою кнопкою на значку, щоб вимкнути підказки або вийти. Немає значка в треї (GNOME)? Встановіть розширення AppIndicator або запустіть Wardly ще раз, щоб відкрити вікно.",
    fullscreenBalloonLinux:
      "Дота запущена в повноекранному режимі, і менеджер вікон малює її над усіма іншими вікнами, тому підказки поверх неї не видно. У Доті: Налаштування → Відео → режим екрана «Вікно без рамки» (Borderless window). Або ввімкніть озвучення порад у застосунку.",
    updateAfterGame: (version) => `Оновлення ${version} встановиться після виходу з Доти`,
    updated: (version) => `Оновлено до версії ${version}.`,
    reviewReady: (score, focusMet) =>
      `Розбір матчу готовий${score ? `: оцінка${score}` : ""}.${focusMet === true ? " Фокус: вдалося." : focusMet === false ? " Фокус: знову повторилося." : ""} Натисніть, щоб відкрити.`,
    sessionReady: (games, wins, losses, score) =>
      `Підсумок вечора: ${games} ${games % 10 >= 2 && games % 10 <= 4 && (games % 100 < 12 || games % 100 > 14) ? "матчі" : games % 10 === 1 && games % 100 !== 11 ? "матч" : "матчів"}, ${wins}–${losses}${score !== null && score !== undefined ? `, середня оцінка ${score}` : ""}. Натисніть, щоб подивитися й скопіювати для друзів.`,
    problemReport: "Зберегти звіт про проблему",
    lastReview: (score) => `Розбір останнього матчу${score !== null && score !== undefined ? ` · ${score}/100` : ""}`,
    reportSentLater: (id) => `Звіт про проблему надіслано. Номер: ${id}.`,
    voice: "Голос",
    voice_off: "Вимкнено",
    voice_urgent: "Термінові поради",
    voice_all: "Усі поради"
  }
};

function t(key, ...args) {
  const locale = uiLocale();
  const value = TRAY_TEXT[locale][key] || TRAY_TEXT.en[key] || key;
  return typeof value === "function" ? value(...args) : value;
}

function argValue(name) {
  for (const arg of process.argv) {
    if (arg === name) {
      return "";
    }
    if (arg.startsWith(`${name}=`)) {
      return arg.slice(name.length + 1);
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

function openLauncherLog() {
  try {
    fs.mkdirSync(path.dirname(LAUNCHER_LOG_PATH), { recursive: true });
    if (fs.existsSync(LAUNCHER_LOG_PATH) && fs.statSync(LAUNCHER_LOG_PATH).size > 2 * 1024 * 1024) {
      fs.renameSync(LAUNCHER_LOG_PATH, `${LAUNCHER_LOG_PATH}.old`);
    }
    launcherLogStream = fs.createWriteStream(LAUNCHER_LOG_PATH, { flags: "a" });
    launcherLogStream.on("error", () => {
      launcherLogStream = null;
    });
  } catch {
    launcherLogStream = null;
  }
}

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

// Every way out says why in the log: a problem report from a match played
// without the app (closed from the tray right after the horn) only showed a
// clean "Stopping backend".
function quitApp(reason) {
  const during = live.inMatch ? " during a match" : dotaWatcher.getState().running ? " while Dota was running" : "";
  appendLog("launcher", `Quit: ${reason}${during}.`, { force: true });
  app.quit();
}

function appendLog(scope, text, options = {}) {
  const clean = String(text || "").replace(/\r/g, "").trimEnd();
  if (!clean) {
    return;
  }
  const lineParts = [];
  for (const part of clean.split("\n")) {
    const stamped = `[${new Date().toLocaleTimeString()}] [${scope}] ${part}`;
    if (launcherLogStream) {
      launcherLogStream.write(`${new Date().toISOString()} [${scope}] ${part}\n`);
    }
    if (!options.force && isHiddenLogLine(scope, part)) {
      hiddenBackendAccessLogs += 1;
      if (hiddenBackendAccessLogs % 25 === 0) {
        lineParts.push(
          `[${new Date().toLocaleTimeString()}] [launcher] clean logs hidden: backend=${hiddenBackendAccessLogs}`
        );
      }
      continue;
    }
    lineParts.push(stamped);
  }
  if (IS_SMOKE_TEST) {
    process.stdout.write(`${lineParts.join("\n")}\n`);
  }
  if (!lineParts.length) {
    return;
  }
  logs = `${logs}${lineParts.join("\n")}\n`;
  if (logs.length > 80000) {
    logs = logs.slice(-80000);
  }
  send("launcher:logs", logs);
}

function isHiddenLogLine(scope, line) {
  return logMode === "clean" && scope === "backend" && BACKEND_NOISE_PATTERNS.some((pattern) => pattern.test(line));
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

function backendUrl() {
  return backend.port ? `http://${BACKEND_HOST}:${backend.port}` : "";
}

function backendInfo() {
  return { status: processStatus.backend, port: backend.port, url: backendUrl() };
}

function gsiEndpoint() {
  const port = backend.port || Number(settings.get("backendPort")) || PREFERRED_BACKEND_PORT;
  return `http://${BACKEND_HOST}:${port}/gsi`;
}

function emptyLiveDetails() {
  return { connected: false, inMatch: false, postGame: false, hero: null, coverage: null, role: null, clockTime: null, secondsSinceLastGsi: null, stage: "unknown" };
}

// "auto" follows the system language; the player can pick one in Settings.
// Ukrainian on a Ukrainian, Russian or Belarusian Windows, English elsewhere.
const CYRILLIC_SYSTEM_LOCALE = /^(uk|ru|be)(-|$)/i;
function uiLocale() {
  const chosen = settings.get("language");
  if (chosen === "uk" || chosen === "en") {
    return chosen;
  }
  try {
    return CYRILLIC_SYSTEM_LOCALE.test(app.getLocale()) ? "uk" : "en";
  } catch {
    return "en";
  }
}

// «Розмір інтерфейсу»: the control panel's zoom, kept in settings.uiScale.
// Ctrl + plus / minus / 0 and Ctrl + the mouse wheel step through the same
// sizes (the default menu's zoom keys would change the page and forget it).
const UI_SCALES = [0.9, 1, 1.1, 1.25];

function uiScale() {
  const value = Number(settings.get("uiScale"));
  return UI_SCALES.includes(value) ? value : 1;
}

function applyUiScale() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.setZoomFactor(uiScale());
  }
}

function setUiScale(value) {
  const scale = Number(value);
  settings.set("uiScale", UI_SCALES.includes(scale) ? scale : 1);
  applyUiScale();
  updateStatus();
  return publicStatus();
}

// direction: 1 bigger, -1 smaller, 0 back to 100 %. The panel names the new
// size for a moment (its toast), since nothing else on the page says it.
function stepUiScale(direction) {
  const index = UI_SCALES.indexOf(uiScale());
  const next = direction === 0 ? 1 : UI_SCALES[Math.max(0, Math.min(UI_SCALES.length - 1, index + direction))];
  if (next !== uiScale()) {
    setUiScale(next);
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("launcher:ui-scale", next);
  }
}

// The zoom keys of the panel: Ctrl/Cmd with plus, minus or 0 (main keyboard or
// numpad); null for any other key.
function uiScaleKey(input) {
  if (input.type !== "keyDown" || !(input.control || input.meta) || input.alt) {
    return null;
  }
  if (input.key === "+" || input.key === "=" || input.code === "NumpadAdd") {
    return 1;
  }
  if (input.key === "-" || input.key === "_" || input.code === "NumpadSubtract") {
    return -1;
  }
  if (input.key === "0" || input.code === "Numpad0") {
    return 0;
  }
  return null;
}

function setLanguage(value) {
  settings.set("language", ["uk", "en"].includes(value) ? value : "auto");
  overlay.notifyBackendChanged(); // re-sends the overlay config with the new locale
  refreshTray();
  updateStatus();
  return publicStatus();
}

/** «Підсумок вечора» in the tray once per sitting, after Dota is closed (2+ games). */
async function notifySession() {
  if (dotaWatcher.getState().running) {
    return;
  }
  const result = await playerRequest("session");
  const session = result.ok && result.data ? result.data.session : null;
  if (!session || !session.id || settings.get("sessionNotified") === session.id || settings.get("sessionSeen") === session.id) {
    return;
  }
  settings.set("sessionNotified", session.id);
  appendLog("player", `Evening summary: ${session.games} matches.`, { force: true });
  showTrayBalloon(t("sessionReady", session.games, session.wins, session.losses, session.avg_score), { type: "open-home" });
}

const INVITE_AFTER_REVIEWS = 3;

/** The site link a player sends to a friend: their language, tagged for the source count. */
function inviteUrl() {
  return `https://luhovyimvp.dev/${uiLocale() === "uk" ? "" : "en/"}?ref=invite`;
}

function inviteDue() {
  return !settings.get("inviteDone") && (Number(settings.get("liveReviews")) || 0) >= INVITE_AFTER_REVIEWS;
}

/** The first-run tour: once, on a fresh install (a player who already has game data or hid the checklist knows the app). */
function tourDue() {
  return !settings.get("tourDone") && !settings.get("gsiSeenAt") && !settings.get("setupDismissed") && !IS_SMOKE_TEST;
}

function publicStatus() {
  const dota = dotaWatcher.getState();
  return {
    locale: uiLocale(),
    language: settings.get("language") || "auto",
    uiScale: uiScale(),
    live: { ...live.details },
    recentAdvice: live.recentAdvice,
    overlayPosition: overlay.position(),
    overlayVoice: overlay.voice(),
    overlayDisplay: overlay.display(),
    skillArrows: skillArrows.state(),
    overlaySize: overlay.size(),
    adviceFrequency: adviceFrequency(),
    adviceRole: adviceRole(),
    mapHints: mapHintsEnabled(),
    matchRecords: Boolean(settings.get("matchRecords")),
    discordPresence: settings.get("discordPresence") !== false,
    discordState: discord.getState(),
    discordWeekly: discordWeeklyState(),
    shareStats: Boolean(settings.get("shareStats")),
    statsSentAt: settings.get("statsSentAt") || "",
    overlayLocked: !overlay.isUnlocked(),
    dotaRunning: dota.running,
    dotaFocused: dota.focused,
    dotaFullscreen: fullscreenWarningActive(),
    appVersion: app.getVersion(),
    update: { ...updater.getState(), blockedByGame: isGameRunning() },
    player: live.player,
    setup: {
      gsiSeen: Boolean(settings.get("gsiSeenAt")),
      dismissed: Boolean(settings.get("setupDismissed")),
      previewed: Boolean(settings.get("overlayPreviewed"))
    },
    report: { last: settings.get("lastReport") || null, queued: outboxCount },
    whatsNew: settings.get("whatsNewPending") === app.getVersion() ? app.getVersion() : "",
    whatsNewFrom: settings.get("whatsNewFrom") || "",
    invite: inviteDue() ? inviteUrl() : "",
    tour: tourDue(),
    statsAsk: !settings.get("statsAsked") && !settings.get("shareStats") && !IS_SMOKE_TEST,
    sessionSeen: settings.get("sessionSeen") || "",
    overlayReasonCode: presence.code,
    backend: processStatus.backend,
    backendPort: backend.port,
    backendUrl: backendUrl(),
    gsiEndpoint: gsiEndpoint(),
    overlay: overlay.isEnabled() ? "running" : "stopped",
    overlayVisible: presence.visible,
    overlayReason: presence.reason,
    dota: presence.status,
    dotaDir: dotaInstall.dotaDir,
    launchOption: launchOptions.state,
    demo: processStatus.demo,
    demoPreset: processStatus.demo !== "stopped" ? currentDemoPreset : "",
    recording: recordingStatus,
    gsiConfig: gsiStatus.status,
    gsiPath: gsiStatus.path,
    mode,
    llm: "off",
    logMode,
    autostart: autostartEnabled,
    autostartSupported: isAutostartSupported(),
    platform: process.platform
  };
}

function updateStatus() {
  send("launcher:status", publicStatus());
}

function isGameRunning() {
  return Boolean(dotaWatcher.getState().running || live.inMatch);
}

// Exclusive fullscreen: Windows does not draw other windows over the game, so
// the overlay is "shown" but invisible. Tell the user once per Dota run (tray
// balloon) and keep a warning on the status screen and in the tray menu. The
// user can dismiss it if the overlay is visible for them anyway.
function fullscreenWarningActive() {
  const dota = dotaWatcher.getState();
  return Boolean(
    dota.running && dota.exclusiveFullscreen && overlay.isEnabled() && !settings.get("fullscreenWarningDismissed")
  );
}

function noteExclusiveFullscreen(state) {
  if (!state.running) {
    fullscreenBalloonShown = false;
    return;
  }
  if (state.exclusiveFullscreen) {
    settings.set("fullscreenSeenDay", adviceStats.localDay(adviceStats.dayStart(Date.now())));
  }
  if (!state.exclusiveFullscreen || fullscreenBalloonShown) {
    return;
  }
  fullscreenBalloonShown = true;
  appendLog("overlay", "Dota runs in exclusive fullscreen; the overlay cannot be drawn over it.", { force: true });
  if (fullscreenWarningActive()) {
    showTrayBalloon(t(process.platform === "linux" ? "fullscreenBalloonLinux" : "fullscreenBalloon"));
  }
}

// ---------------------------------------------------------------------------
// Dota presence: overlay visibility + tray status
// ---------------------------------------------------------------------------

function refreshPresence() {
  const dota = dotaWatcher.getState();
  const decision = overlayVisibility({
    enabled: overlay.isEnabled(),
    unlocked: overlay.isUnlocked(),
    demoRunning: processStatus.demo === "running",
    dota,
    inMatch: live.inMatch,
    postGame: live.postGame
  });
  overlay.setVisible(decision.visible);
  skillArrows.setOverlayVisible(decision.visible);
  refreshDiscord();
  const status = dotaStatus({ dota, inMatch: live.inMatch });
  const visibilityChanged = decision.visible !== presence.visible || decision.reason !== presence.reason;
  const statusChanged = status !== presence.status;
  presence.visible = decision.visible;
  presence.reason = decision.reason;
  presence.code = decision.code;
  presence.status = status;
  if (visibilityChanged) {
    appendLog("overlay", `${decision.visible ? "Shown" : "Hidden"}: ${decision.reason}`);
  }
  if (statusChanged) {
    appendLog("dota", `Status: ${TRAY_TEXT.en[status]}`, { force: true });
  }
  if (visibilityChanged || statusChanged) {
    updateStatus();
    refreshTray();
  }
}

// ---------------------------------------------------------------------------
// Discord Rich Presence (discord-presence.js): Dota running → «У меню Dota 2»,
// a match → «Матч на <герой>» with the time since the horn; nothing without Dota.
// ---------------------------------------------------------------------------

const discord = discordPresence.createDiscordPresence({
  log: (message) => appendLog("discord", message, { force: true }),
  // Shown under «Статус у Discord»: Discord not found, refused, or shown.
  onState: () => updateStatus()
});
let discordMatch = { hero: null, startedAt: null };

function refreshDiscord() {
  if (IS_SMOKE_TEST || settings.get("discordPresence") === false) {
    discord.update(null);
    return;
  }
  const dota = dotaWatcher.getState();
  const hero = live.inMatch ? live.details.hero : null;
  discordMatch = discordPresence.trackMatchStart(discordMatch, {
    inMatch: live.inMatch,
    hero,
    clock: live.details.clockTime,
    now: Date.now()
  });
  discord.update(
    discordPresence.buildActivity({
      dotaRunning: Boolean(dota.running),
      inMatch: live.inMatch,
      hero,
      startedAt: discordMatch.startedAt,
      lang: uiLocale()
    })
  );
}

function setDiscordPresence(enabled) {
  settings.set("discordPresence", Boolean(enabled));
  refreshDiscord();
  return publicStatus();
}

// ---------------------------------------------------------------------------
// Opt-in anonymous statistics (advice-stats.js): yesterday's advice counts and
// a few settings to services/api once a day, only while the switch is on.
// ---------------------------------------------------------------------------

const STATS_FIRST_CHECK_MS = 2 * 60 * 1000;
const STATS_CHECK_MS = 30 * 60 * 1000;
const STATS_TIMEOUT_MS = 20_000;
let statsTimer = null;
let statsBusy = false;

/** One more launch, crash or unclean exit today (advice-stats.js, kept even while the statistics are off). */
function countApp(key) {
  const today = adviceStats.localDay(adviceStats.dayStart(Date.now()));
  settings.set("statsDaily", adviceStats.bumpDaily(settings.get("statsDaily"), today, key));
}

/** The first-run steps reached so far, as the Home checklist sees them (null: cannot tell). */
function setupState() {
  const gsiSeen = Boolean(settings.get("gsiSeenAt"));
  const player = live.player || {};
  return {
    dota: Boolean(dotaInstall.dotaDir) || gsiSeen,
    gsi: gsiStatus.status === "installed" || gsiSeen,
    launch: launchOptions.state === "ok" || gsiSeen ? true : launchOptions.state === "missing" ? false : null,
    data: gsiSeen,
    preview: Boolean(settings.get("overlayPreviewed")),
    account: Boolean(player.linked),
    advice: Boolean(settings.get("firstAdviceAt")),
    review: (Number(settings.get("liveReviews")) || 0) > 0 || Boolean(player.lastReview),
    ai: Boolean(player.aiConfigured)
  };
}

async function statsParts(period) {
  const payload = await requestBackendJson(adviceStats.usageQuery(period), "GET", undefined, 15000);
  let syncError = null;
  try {
    const player = await requestBackendJson("/player", "GET", undefined, 5000);
    syncError = (player.sync && player.sync.error_code) || null;
  } catch {
    // The day's counts matter; the sync state is optional.
  }
  let feedback = null;
  try {
    feedback = await requestBackendJson("/player/advice-feedback", "GET", undefined, 5000);
  } catch {
    // No marks this time; they are counted at the next upload.
  }
  const delta = adviceStats.marksDelta(feedback, settings.get("statsMarksSent"));
  const body = adviceStats.buildStats({
    installId: installId(),
    day: period.day,
    version: app.getVersion(),
    platform: process.platform,
    lang: uiLocale(),
    usage: payload.usage,
    settings: {
      overlay: overlay.isEnabled(),
      voice: overlay.voice().mode,
      frequency: adviceFrequency(),
      role: adviceRole(),
      mapHints: mapHintsEnabled(),
      discord: settings.get("discordPresence") !== false
    },
    ai: Boolean(live.player && live.player.aiConfigured),
    opendotaKey: Boolean(live.player && live.player.opendotaKey),
    fullscreen: settings.get("fullscreenSeenDay") === period.day,
    syncError,
    app: adviceStats.appCounts(settings.get("statsDaily"), period.day),
    marks: delta.marks,
    noisy: delta.noisy,
    setup: setupState(),
    age: adviceStats.ageBucket(Date.now(), settings.get("installedAt"))
  });
  return { body, marksSnapshot: delta.snapshot };
}

async function statsBody(period) {
  return (await statsParts(period)).body;
}

async function postStats(body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), STATS_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/stats`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    let answer = {};
    try {
      answer = await response.json();
    } catch {
      // Not JSON: the status decides.
    }
    return { ok: response.ok, status: response.status, code: answer.code || "" };
  } catch (error) {
    return { ok: false, code: "offline", error: error.message };
  } finally {
    clearTimeout(timer);
  }
}

async function checkAdviceStats() {
  if (IS_SMOKE_TEST || statsBusy || !settings.get("shareStats") || processStatus.backend !== "running") {
    return;
  }
  const due = adviceStats.dueDay(Date.now(), settings.get("statsLastDay"), settings.get("statsSince"));
  if (!due) {
    return;
  }
  statsBusy = true;
  try {
    const parts = await statsParts(due);
    const result = await postStats(parts.body);
    if (adviceStats.uploadOutcome(result).done) {
      settings.set("statsLastDay", due.end);
      // The marks of this upload are handled either way (stored or refused for good).
      settings.set("statsMarksSent", parts.marksSnapshot);
      if (result.ok) {
        settings.set("statsSentAt", new Date().toISOString());
      }
      appendLog("launcher", `Anonymous statistics for ${due.day}: ${result.ok ? "sent" : result.code}.`, { force: true });
      updateStatus();
    }
  } catch (error) {
    appendLog("launcher", `Anonymous statistics not sent: ${error.message}`, { force: true });
  } finally {
    statsBusy = false;
  }
}

function startAdviceStats() {
  if (IS_SMOKE_TEST || statsTimer) {
    return;
  }
  setTimeout(() => checkAdviceStats().catch(() => {}), STATS_FIRST_CHECK_MS).unref?.();
  statsTimer = setInterval(() => checkAdviceStats().catch(() => {}), STATS_CHECK_MS);
  statsTimer.unref?.();
}

function restartStatsCount() {
  const schedule = adviceStats.startFrom(Date.now());
  settings.set("statsLastDay", schedule.statsLastDay);
  settings.set("statsSince", schedule.statsSince);
  // Launches and crashes before this moment are never sent: today's counters start again.
  settings.set("statsDaily", {});
  // Nor marks given before it: the totals now are where the next upload counts from.
  settings.set("statsMarksSent", null);
  baselineMarks().catch(() => {});
}

/** The advice-mark totals at the consent; unreadable (backend down), the first upload takes them instead. */
async function baselineMarks() {
  if (processStatus.backend !== "running") {
    return;
  }
  const feedback = await requestBackendJson("/player/advice-feedback", "GET", undefined, 5000);
  settings.set("statsMarksSent", adviceStats.marksDelta(feedback, null).snapshot);
}

// On: counting starts now (the first upload tomorrow is what happened after this), never earlier.
function setShareStats(enabled) {
  settings.set("shareStats", Boolean(enabled));
  if (enabled) {
    restartStatsCount();
  }
  appendLog("launcher", `Anonymous statistics ${enabled ? "on" : "off"}.`, { force: true });
  return publicStatus();
}

// «Видалити мої дані на сервері»: every report, match recording, shared link,
// transfer and statistics row of this installation (DELETE /v1/device/<install id>).
async function deleteServerData() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), STATS_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/device/${encodeURIComponent(installId())}`, {
      method: "DELETE",
      headers: deviceHeaders(),
      signal: controller.signal
    });
    if (!response.ok) {
      return { ok: false, code: `http_${response.status}`, status: publicStatus() };
    }
    // The shared links are gone with it, and what was counted before is never sent again.
    settings.set("shares", {});
    // The recordings sent are deleted too: the list no longer says «Sent».
    settings.set("sentRecords", {});
    // The profile card went with it: hidden until the player shows it again.
    settings.set("friendsProfile", { ...friendsProfile(), enabled: false, hash: "" });
    restartStatsCount();
    appendLog("launcher", "Server data of this installation deleted.", { force: true });
    return { ok: true, status: publicStatus() };
  } catch {
    return { ok: false, code: "offline", status: publicStatus() };
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// «Друзі» (0.35): the profile card the player shows friends, and the friends'
// cards by code. The card is built by the backend (/player/profile/public) and
// published to services/api under a random id with a token only this launcher
// keeps; friends are a list of codes on this computer, nothing more.
// ---------------------------------------------------------------------------

const FRIENDS_TIMEOUT_MS = 15000;
const PROFILE_REPUBLISH_MS = 10 * 60 * 1000;

function friendsProfile() {
  const value = settings.get("friendsProfile");
  return value && typeof value === "object" ? value : { enabled: false };
}

async function apiRequest(path, { method = "GET", headers = {}, body } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FRIENDS_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${apiUrl()}${path}`, {
      method,
      headers: { "content-type": "application/json", ...deviceHeaders(), ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    });
    let answer = {};
    try {
      answer = await response.json();
    } catch {
      // Not JSON: the status decides.
    }
    return { status: response.status, ok: response.ok, answer };
  } finally {
    clearTimeout(timer);
  }
}

/** Publishes the card when it changed (or every 10 min); the own card back. */
async function publishProfile({ force = false } = {}) {
  let own = friendsProfile();
  const mmr = own.showMmr !== false ? "true" : "false";
  const { card } = await requestBackendJson(`/player/profile/public?lang=${uiLocale()}&mmr=${mmr}`, "GET", undefined, 15000);
  if (!own.enabled) {
    return { card, own };
  }
  if (!friends.isProfileId(own.id) || !/^[0-9a-f]{32}$/.test(String(own.token || ""))) {
    own = { ...own, id: friends.newProfileId(crypto.randomBytes), token: friends.newToken(crypto.randomBytes) };
    settings.set("friendsProfile", own);
  }
  const hash = crypto.createHash("sha256").update(JSON.stringify(card)).digest("hex").slice(0, 16);
  if (!force && own.hash === hash && Date.now() - (Number(own.at) || 0) < PROFILE_REPUBLISH_MS) {
    return { card, own };
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const result = await apiRequest(`/v1/profile/${own.id}`, {
      method: "PUT",
      headers: { "x-profile-token": own.token },
      body: { install_id: installId(), version: app.getVersion(), profile: card }
    });
    if (result.status === 409) {
      // Someone else has that code: a new one (it was never shown to anyone).
      own = { ...own, id: friends.newProfileId(crypto.randomBytes), token: friends.newToken(crypto.randomBytes) };
      continue;
    }
    if (!result.ok) {
      throw Object.assign(new Error(result.answer.code || `http_${result.status}`), { code: result.answer.code || `http_${result.status}` });
    }
    own = { ...own, url: String(result.answer.url || ""), hash, at: Date.now() };
    settings.set("friendsProfile", own);
    return { card, own };
  }
  throw Object.assign(new Error("taken"), { code: "taken" });
}

async function friendsStatus({ force = false } = {}) {
  // Profile UI smoke reads a real local card without publishing the fixture or
  // using the installed player's friend codes or consent settings.
  if (IS_SMOKE_TEST) {
    const { card } = await requestBackendJson(`/player/profile/public?lang=${uiLocale()}&mmr=true`, "GET", undefined, 15000);
    return {
      ok: true, enabled: false, code: "", url: "", showMmr: true,
      rows: friends.leaderboard(card ? [{ id: "me", me: true, card }] : []),
      missing: [], error: ""
    };
  }
  let own = friendsProfile();
  let card = null;
  let error = "";
  try {
    ({ card, own } = await publishProfile({ force }));
  } catch (failure) {
    error = failure.code || (failure.status ? "backend_down" : "offline");
  }
  const list = (settings.get("friends") || []).filter(friends.isProfileId);
  let cards = {};
  if (list.length) {
    try {
      const result = await apiRequest("/v1/profiles", { method: "POST", body: { ids: list } });
      cards = result.ok && result.answer.profiles ? result.answer.profiles : {};
      if (!result.ok) {
        error = error || result.answer.code || `http_${result.status}`;
      }
    } catch {
      error = error || "offline";
    }
  }
  const rows = friends.leaderboard([
    ...(card ? [{ id: own.id || "me", me: true, card }] : []),
    ...list.map((id) => ({ id, card: cards[id] || null }))
  ]);
  return {
    ok: true,
    enabled: Boolean(own.enabled),
    code: own.enabled && friends.isProfileId(own.id) ? friends.friendCode(own.id) : "",
    url: own.enabled ? own.url || "" : "",
    showMmr: own.showMmr !== false,
    rows,
    missing: list.filter((id) => !cards[id]).map(friends.friendCode),
    error
  };
}

async function friendsAction(request) {
  const own = friendsProfile();
  const action = request && typeof request === "object" ? request : { op: String(request || "status") };
  try {
    if (action.op === "enable") {
      settings.set("friendsProfile", { ...own, enabled: true });
      appendLog("launcher", "Profile card shown to friends.", { force: true });
      return await friendsStatus({ force: true });
    }
    if (action.op === "disable") {
      if (friends.isProfileId(own.id) && own.token) {
        await apiRequest(`/v1/profile/${own.id}`, { method: "DELETE", headers: { "x-profile-token": own.token } }).catch(() => null);
      }
      // The same code comes back when the player shows the profile again.
      settings.set("friendsProfile", { ...own, enabled: false, hash: "", url: "" });
      appendLog("launcher", "Profile card hidden.", { force: true });
      return await friendsStatus();
    }
    if (action.op === "showMmr") {
      settings.set("friendsProfile", { ...own, showMmr: Boolean(action.value) });
      return await friendsStatus({ force: true });
    }
    if (action.op === "add") {
      const result = friends.addFriend(settings.get("friends"), action.code, own.enabled ? own.id : null);
      if (!result.ok) {
        return { ...(await friendsStatus()), addError: result.code };
      }
      settings.set("friends", result.list);
      return await friendsStatus();
    }
    if (action.op === "remove") {
      settings.set("friends", friends.removeFriend(settings.get("friends"), friends.normalizeCode(action.code)));
      return await friendsStatus();
    }
    if (action.op === "copy" && own.enabled && friends.isProfileId(own.id)) {
      clipboard.writeText(action.what === "link" && own.url ? own.url : friends.friendCode(own.id));
      return { ok: true };
    }
    if (action.op === "open" && own.enabled && /^https:\/\//.test(String(own.url || ""))) {
      shell.openExternal(own.url);
      return { ok: true };
    }
    return await friendsStatus();
  } catch (error) {
    return { ok: false, code: error.code || "failed" };
  }
}

// «Що буде надіслано»: the body for today so far, exactly as it would go.
async function statsPreview() {
  const day = adviceStats.dayStart(Date.now());
  const start = Math.max(day, Number(settings.get("statsSince")) || 0);
  try {
    const body = await statsBody({ start, end: Date.now(), day: adviceStats.localDay(day) });
    return { ok: true, text: JSON.stringify(body, null, 2) };
  } catch {
    return { ok: false, code: "backend_down" };
  }
}

// ---------------------------------------------------------------------------
// The week in Discord (discord-weekly.js): every Monday the calendar week that
// ended goes to the player's channel webhook, straight from this computer.
// ---------------------------------------------------------------------------

const DISCORD_WEEKLY_FIRST_CHECK_MS = 90 * 1000;
const DISCORD_WEEKLY_CHECK_MS = 30 * 60 * 1000;
const DISCORD_POST_TIMEOUT_MS = 20_000;
let discordWeeklyTimer = null;
let discordWeeklyBusy = false;

function discordWeeklyState() {
  const url = settings.get("discordWebhook") || "";
  return {
    configured: Boolean(url),
    hint: discordWeekly.webhookHint(url),
    last: settings.get("discordWeeklyStatus") || null
  };
}

// One post: the week from the backend, the message, the webhook. `period` in ms.
async function postWeekToDiscord(period) {
  const url = settings.get("discordWebhook");
  if (!url) {
    return { ok: false, code: "not_configured" };
  }
  const lang = uiLocale();
  let week;
  try {
    const payload = await requestBackendJson(discordWeekly.weekQuery(period, lang), "GET", undefined, 15000);
    week = payload.week;
  } catch {
    return { ok: false, code: "backend_down" };
  }
  const message = discordWeekly.buildWeeklyMessage(week, { lang, period });
  if (!message) {
    return { ok: true, sent: false, code: "no_matches" };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DISCORD_POST_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${url}?wait=true`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(message),
      signal: controller.signal
    });
    if (response.ok) {
      return { ok: true, sent: true, games: week.games };
    }
    // 401/404: the webhook was deleted in Discord; 429: Discord's rate limit.
    const code = [401, 403, 404].includes(response.status) ? "webhook_gone" : response.status === 429 ? "rate_limited" : `http_${response.status}`;
    return { ok: false, code };
  } catch {
    return { ok: false, code: "offline" };
  } finally {
    clearTimeout(timer);
  }
}

function noteDiscordWeekly(result, manual) {
  if (discordWeekly.postOutcome(result).disconnect) {
    // Deleted in Discord: stop posting; the panel says so and asks for a new link.
    settings.set("discordWebhook", "");
  }
  settings.set("discordWeeklyStatus", {
    at: new Date().toISOString(),
    ok: Boolean(result.ok),
    sent: Boolean(result.sent),
    code: result.code || "",
    manual: Boolean(manual)
  });
  appendLog(
    "discord",
    result.ok ? (result.sent ? `Week posted to Discord (${result.games} matches).` : "No matches this week: nothing posted.") : `Week not posted: ${result.code}.`,
    { force: true }
  );
}

// Scheduled: the week that ended on Monday, once. Offline or a busy backend
// tries again at the next check; a deleted webhook is noted and not retried.
async function checkDiscordWeekly() {
  if (IS_SMOKE_TEST || discordWeeklyBusy || !settings.get("discordWebhook") || processStatus.backend !== "running") {
    return;
  }
  const due = discordWeekly.dueWeek(Date.now(), settings.get("discordWeeklyLast"));
  if (!due) {
    return;
  }
  discordWeeklyBusy = true;
  try {
    const result = await postWeekToDiscord(due);
    if (discordWeekly.postOutcome(result).done) {
      settings.set("discordWeeklyLast", due.end);
      noteDiscordWeekly(result, false);
      updateStatus();
    }
  } finally {
    discordWeeklyBusy = false;
  }
}

function startDiscordWeekly() {
  if (IS_SMOKE_TEST || discordWeeklyTimer) {
    return;
  }
  setTimeout(() => checkDiscordWeekly().catch(() => {}), DISCORD_WEEKLY_FIRST_CHECK_MS).unref?.();
  discordWeeklyTimer = setInterval(() => checkDiscordWeekly().catch(() => {}), DISCORD_WEEKLY_CHECK_MS);
  discordWeeklyTimer.unref?.();
}

// The panel: connect a link (the first post comes next Monday), send the last
// seven days now (a check), or disconnect.
async function discordWeeklyAction(request) {
  const action = request && request.action;
  if (action === "set") {
    const url = discordWeekly.parseWebhookUrl(request.url);
    if (!url) {
      return { ok: false, code: "bad_url", status: publicStatus() };
    }
    settings.set("discordWebhook", url);
    settings.set("discordWeeklyLast", discordWeekly.weekStart(Date.now()));
    settings.set("discordWeeklyStatus", null);
    appendLog("discord", "Weekly post connected to a Discord webhook.", { force: true });
    return { ok: true, status: publicStatus() };
  }
  if (action === "clear") {
    settings.set("discordWebhook", "");
    settings.set("discordWeeklyStatus", null);
    appendLog("discord", "Weekly post disconnected.", { force: true });
    return { ok: true, status: publicStatus() };
  }
  if (action === "send") {
    if (discordWeeklyBusy) {
      return { ok: false, code: "busy", status: publicStatus() };
    }
    discordWeeklyBusy = true;
    try {
      const now = Date.now();
      const result = await postWeekToDiscord({ start: now - 7 * 24 * 3600 * 1000, end: now });
      if (discordWeekly.postOutcome(result).done) {
        noteDiscordWeekly(result, true);
      }
      return { ...result, status: publicStatus() };
    } finally {
      discordWeeklyBusy = false;
    }
  }
  return { ok: false, code: "bad_request", status: publicStatus() };
}

// The backend decides whether GSI is fresh and comes from a match
// (/gsi/status -> in_match); poll it so the overlay hides within ~1 s.
function startGsiPolling() {
  if (live.pollTimer) {
    return;
  }
  live.pollTimer = setInterval(pollGsiStatus, GSI_STATUS_POLL_MS);
  live.pollTimer.unref?.();
}

function stopGsiPolling() {
  clearInterval(live.pollTimer);
  live.pollTimer = null;
}

async function pollGsiStatus() {
  if (live.polling) {
    return;
  }
  live.polling = true;
  let details = emptyLiveDetails();
  try {
    if (processStatus.backend === "running") {
      const status = await requestBackendJson("/gsi/status");
      details = {
        connected: Boolean(status.gsi_connected),
        inMatch: Boolean(status.in_match),
        postGame: Boolean(status.post_game),
        hero: status.hero && status.hero !== "Unknown" ? String(status.hero) : null,
        // "full" carry advisor or "safety" (survival advice only) for this hero.
        coverage: status.hero_coverage || null,
        // Position for timers and role tips: { role, source: setting|lane|history|hero }.
        role: status.live_role && status.live_role.role
          ? {
              role: String(status.live_role.role),
              source: String(status.live_role.source || ""),
              // The lane read contradicts the role chosen in the settings.
              mismatch: status.live_role.mismatch ? String(status.live_role.mismatch) : null
            }
          : null,
        clockTime: Number.isFinite(status.clock_time) ? status.clock_time : null,
        secondsSinceLastGsi: Number.isFinite(status.seconds_since_last_gsi) ? status.seconds_since_last_gsi : null,
        stage: status.stage || "unknown"
      };
      // Advice is evaluated when someone asks for /overlay/recommendation. The
      // overlay window does that every second; when it is switched off, ask
      // here so advice keeps being produced for the "Recent advice" card.
      if (!overlay.isOpen()) {
        await fetchOverlayRecommendation();
      }
    }
  } catch {
    details = emptyLiveDetails();
  } finally {
    live.polling = false;
  }
  // Recent advice changes rarely; every third poll is enough.
  live.polls += 1;
  if (processStatus.backend === "running" && live.polls % 5 === 2) {
    pollPlayerStatus().catch(() => {});
    maybeAutoBackup();
  }
  let recentChanged = false;
  if (processStatus.backend === "running" && live.polls % 3 === 1) {
    try {
      const recent = await requestBackendJson(`/advice/recent?limit=5&lang=${uiLocale()}`);
      const items = Array.isArray(recent.items) ? recent.items : [];
      recentChanged = JSON.stringify(items) !== JSON.stringify(live.recentAdvice);
      live.recentAdvice = items;
      if (items.length && !settings.get("firstAdviceAt")) {
        settings.set("firstAdviceAt", new Date().toISOString());
      }
    } catch {
      // Keep the last list; the backend may be restarting.
    }
  }
  if (details.connected && !settings.get("gsiSeenAt")) {
    settings.set("gsiSeenAt", new Date().toISOString());
  }
  const detailsChanged = recentChanged || JSON.stringify(details) !== JSON.stringify(live.details);
  live.details = details;
  if (details.inMatch !== live.inMatch || details.postGame !== live.postGame) {
    live.inMatch = details.inMatch;
    live.postGame = details.postGame;
    refreshPresence();
  }
  if (detailsChanged) {
    // Hero and match clock on the status screen.
    updateStatus();
    refreshDiscord();
  }
}

function setBackendStatus(status) {
  processStatus.backend = status;
  if (status !== "starting") {
    // Running, or it could not start: either way the panel takes over from the splash.
    finishSplash();
  }
  if (status !== "running") {
    live.inMatch = false;
    live.postGame = false;
    live.details = emptyLiveDetails();
    live.recentAdvice = [];
    refreshPresence();
  }
  updateStatus();
  overlay.notifyBackendChanged();
  refreshTray();
}

// ---------------------------------------------------------------------------
// Child processes
// ---------------------------------------------------------------------------

function pythonExecutable() {
  const candidates = process.platform === "win32"
    ? [
        path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe"),
        path.join(BACKEND_DIR, "venv", "Scripts", "python.exe"),
        "python"
      ]
    : [
        path.join(BACKEND_DIR, ".venv", "bin", "python"),
        path.join(BACKEND_DIR, "venv", "bin", "python"),
        "python3",
        "python"
      ];
  for (const candidate of candidates) {
    if (candidate.includes(path.sep) && !fs.existsSync(candidate)) {
      continue;
    }
    return candidate;
  }
  return "python";
}

function packagedExecutable(baseName) {
  const executable = process.platform === "win32" ? `${baseName}.exe` : baseName;
  return path.join(RESOURCES_ROOT, "backend", executable);
}

function demoFileForPreset(preset) {
  return path.join(RESOURCES_ROOT, "data", "match_simulations", preset.fileName);
}

function ensureExecutableExists(name, executablePath) {
  if (fs.existsSync(executablePath)) {
    return true;
  }
  appendLog("launcher", `${name} executable was not found: ${executablePath}`, { force: true });
  return false;
}

function normalizeEnv(env = {}) {
  const normalized = {};
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined || value === null) {
      continue;
    }
    normalized[key] = String(value);
  }
  return normalized;
}

function spawnManaged(name, command, args, options = {}) {
  if (processes[name]) {
    appendLog("launcher", `${name} is already running.`);
    return null;
  }

  const cwd = options.cwd || REPO_ROOT;
  const safeArgs = (Array.isArray(args) ? args : []).filter((arg) => arg !== undefined && arg !== null).map(String);
  const commandLine = `${command} ${safeArgs.join(" ")}`.trim();
  if (!fs.existsSync(cwd)) {
    appendLog("launcher", `Cannot start ${name}: cwd does not exist: ${cwd}; command=${commandLine}`, { force: true });
    return null;
  }
  appendLog("launcher", `Starting ${name}: ${commandLine} (cwd: ${cwd})`, { force: true });

  let child = null;
  try {
    child = spawn(command, safeArgs, {
      cwd,
      env: normalizeEnv({ ...process.env, ...(options.env || {}) }),
      stdio: [options.stdinControl ? "pipe" : "ignore", "pipe", "pipe"],
      windowsHide: true
    });
  } catch (error) {
    appendLog(name, `Failed to start: ${error.message}; command=${commandLine}; cwd=${cwd}`, { force: true });
    return null;
  }
  processes[name] = child;
  delete lastExit[name];

  child.on("spawn", () => {
    appendLog("launcher", `${name} process started with pid ${child.pid}.`, { force: true });
  });
  child.stdout.on("data", (chunk) => appendLog(name, chunk.toString()));
  child.stderr.on("data", (chunk) => appendLog(name, chunk.toString()));
  if (child.stdin) {
    // The backend may exit before we write to it; a broken pipe is not an error here.
    child.stdin.on("error", () => {});
  }
  const finalize = (code, signal) => {
    if (processes[name] !== child) {
      return;
    }
    const wasStopping = stoppingProcesses.delete(name);
    lastExit[name] = { code, signal };
    processes[name] = null;
    appendLog(name, `Exited with code ${code ?? "null"} signal ${signal ?? "null"}.`, { force: true });
    if (typeof options.onExit === "function") {
      options.onExit({ code, signal, wasStopping });
    }
  };
  child.on("error", (error) => {
    appendLog(name, `Failed to start: ${error.message}; command=${commandLine}; cwd=${cwd}`, { force: true });
    if (!child.pid) {
      // Spawn failed; "exit" will not follow.
      finalize(null, null);
    }
  });
  // Registered before any waitForExit() listener, so bookkeeping runs first.
  child.on("exit", finalize);

  return child;
}

function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const onExit = () => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      child.off("exit", onExit);
      resolve(false);
    }, timeoutMs);
    child.once("exit", onExit);
  });
}

// Returns "graceful", "forced" or "" when nothing was running.
async function stopManaged(name, { timeoutMs = 5000 } = {}) {
  const child = processes[name];
  if (!child) {
    appendLog("launcher", `${name} is not running.`);
    return "";
  }
  appendLog("launcher", `Stopping ${name}...`, { force: true });
  stoppingProcesses.add(name);
  const exited = waitForExit(child, timeoutMs);

  if (child.stdin && child.stdin.writable) {
    // Backend protocol (backend/packaging/backend_server.py): "shutdown" on
    // stdin, then EOF. Uvicorn finishes in-flight requests and exits by itself.
    child.stdin.write("shutdown\n");
    child.stdin.end();
  } else {
    try {
      child.kill("SIGTERM");
    } catch (error) {
      appendLog("launcher", `Stop signal failed for ${name}: ${error.message}`, { force: true });
    }
  }

  if (await exited) {
    return "graceful";
  }
  if (process.platform !== "win32") {
    // Still up: ask once more the POSIX way (uvicorn handles SIGTERM) before the kill.
    appendLog("launcher", `${name} did not exit within ${timeoutMs / 1000}s; sending SIGTERM.`, { force: true });
    try {
      child.kill("SIGTERM");
    } catch (error) {
      appendLog("launcher", `Stop signal failed for ${name}: ${error.message}`, { force: true });
    }
    if (await waitForExit(child, SIGTERM_GRACE_MS)) {
      return "forced";
    }
  }
  appendLog("launcher", `${name} did not exit within ${timeoutMs / 1000}s; forcing it to stop.`, { force: true });
  try {
    child.kill("SIGKILL");
  } catch (error) {
    appendLog("launcher", `Force stop failed for ${name}: ${error.message}`, { force: true });
  }
  await waitForExit(child, 3000);
  return "forced";
}

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------

function isValidPort(value) {
  const port = Number(value);
  return Number.isInteger(port) && port > 0 && port < 65536;
}

function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen({ port, host: BACKEND_HOST, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

function ephemeralPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen({ port: 0, host: BACKEND_HOST, exclusive: true }, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

// The last used port is preferred so the Dota GSI config stays valid between
// launches; any free port is used when it is taken.
async function pickBackendPort() {
  const override = process.env.DOTA_AI_BACKEND_PORT;
  if (isValidPort(override)) {
    return Number(override);
  }
  const candidates = [settings.get("backendPort"), PREFERRED_BACKEND_PORT].filter(isValidPort).map(Number);
  for (const candidate of new Set(candidates)) {
    if (await isPortFree(candidate)) {
      return candidate;
    }
    appendLog("launcher", `Port ${candidate} is busy; looking for another one.`, { force: true });
  }
  return ephemeralPort();
}

function startBackend() {
  if (processes.backend) {
    return Promise.resolve(true);
  }
  if (!backend.startPromise) {
    backend.startPromise = launchBackend().finally(() => {
      backend.startPromise = null;
    });
  }
  return backend.startPromise;
}

async function launchBackend() {
  setBackendStatus("starting");
  let auth;
  try {
    auth = localApiAuth();
  } catch {
    appendLog("backend", "Local API credentials could not be initialized. Check the app data folder.", { force: true });
    setBackendStatus("stopped");
    return false;
  }
  const port = await pickBackendPort();
  backend.port = port;
  if (!isValidPort(process.env.DOTA_AI_BACKEND_PORT)) {
    settings.set("backendPort", port);
  }
  if (!IS_SMOKE_TEST) {
    autoInstallGsiOnce().catch((error) => appendLog("gsi", error.message, { force: true }));
  }

  const env = {
    USE_LLM: "false",
    SIMULATION_USE_LLM: "false",
    LIVE_CONSERVATIVE_MODE: "true",
    DOTA_AI_ADVICE_FREQUENCY: adviceFrequency(),
    DOTA_AI_ROLE: adviceRole(),
    DOTA_AI_MAP_HINTS: mapHintsEnabled() ? "true" : "false",
    DOTA_AI_MATCH_RECORDS: settings.get("matchRecords") ? "true" : "false",
    PYTHONUNBUFFERED: "1",
    DOTA_AI_BACKEND_HOST: BACKEND_HOST,
    DOTA_AI_BACKEND_PORT: String(port),
    DOTA_AI_BACKEND_LOG_LEVEL: "info",
    DOTA_AI_BACKEND_STDIN_CONTROL: "1",
    DOTA_AI_CONTROL_TOKEN: auth.control,
    DOTA_AI_GSI_TOKEN: auth.gsi,
    SESSION_RECORDS_DIR
  };
  if (IS_SMOKE_TEST) {
    env.PLAYER_DATA_DIR = SMOKE_PLAYER_DATA_DIR;
    env.OPENDOTA_ENABLED = "false";
  }
  let command = pythonExecutable();
  let args = ["-u", path.join("packaging", "backend_server.py")];
  let cwd = BACKEND_DIR;
  if (IS_PACKAGED) {
    command = packagedExecutable("dota-ai-coach-backend");
    args = [];
    cwd = path.dirname(command);
    if (!ensureExecutableExists("Backend", command)) {
      setBackendStatus("stopped");
      return false;
    }
  }

  const child = spawnManaged("backend", command, args, {
    cwd,
    env,
    stdinControl: true,
    onExit: handleBackendExit
  });
  if (!child) {
    setBackendStatus("stopped");
    return false;
  }

  const healthy = await waitForBackendHealth(child, BACKEND_HEALTH_TIMEOUT_MS);
  if (processes.backend !== child) {
    return false;
  }
  if (!healthy) {
    appendLog(
      "launcher",
      `Backend did not answer ${backendUrl()}/health within ${BACKEND_HEALTH_TIMEOUT_MS / 1000}s; stopping it. Check the backend log lines above.`,
      { force: true }
    );
    // Do not leave an unhealthy process holding the port and blocking Start/Restart.
    await stopBackend();
    return false;
  }
  appendLog("launcher", `Backend is ready: ${backendUrl()}`, { force: true });
  setBackendStatus("running");
  return true;
}

function handleBackendExit({ code, wasStopping }) {
  // Recording lives in the backend process; a new backend starts with it off.
  recordingStatus = "stopped";
  setBackendStatus("stopped");
  if (wasStopping || isQuitting || IS_SMOKE_TEST) {
    return;
  }
  appendLog("launcher", `Backend stopped unexpectedly (code ${code ?? "null"}).`, { force: true });
  countApp("backend_crashes");
  const now = Date.now();
  backend.restarts = backend.restarts.filter((timestamp) => now - timestamp < BACKEND_RESTART_WINDOW_MS);
  if (backend.restarts.length >= BACKEND_MAX_RESTARTS) {
    appendLog("launcher", "Backend keeps crashing; automatic restart is paused. Use Start Backend to retry.", {
      force: true
    });
    return;
  }
  backend.restarts.push(now);
  const timer = setTimeout(() => {
    if (!isQuitting && !processes.backend) {
      appendLog("launcher", "Restarting backend...", { force: true });
      startBackend();
    }
  }, 2000);
  timer.unref?.();
}

async function stopBackend() {
  const outcome = await stopManaged("backend", { timeoutMs: BACKEND_GRACEFUL_STOP_MS });
  setBackendStatus("stopped");
  return outcome;
}

async function restartBackend() {
  await stopBackend();
  backend.restarts = [];
  return startBackend();
}

async function waitForBackendHealth(child, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (processes.backend !== child) {
      return false;
    }
    if (await isBackendReady()) {
      return true;
    }
    await delay(400);
  }
  return false;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isBackendReady() {
  if (!backend.port) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const request = http.get(`${backendUrl()}/health`, { timeout: 1200 }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 300);
    });
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function requestBackendJson(endpointPath, method = "GET", body = undefined, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    if (processStatus.backend !== "running") {
      reject(new Error("Backend is not running."));
      return;
    }
    const url = new URL(endpointPath, backendUrl());
    const request = http.request(
      url,
      {
        method,
        timeout: timeoutMs,
        headers: controlHeaders(url, backendUrl(), localApiAuth().control)
      },
      (response) => {
        let responseBody = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          responseBody += chunk;
        });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) {
            const error = new Error(`Backend returned HTTP ${response.statusCode}: ${responseBody}`);
            error.status = response.statusCode;
            try {
              error.payload = JSON.parse(responseBody);
            } catch {
              error.payload = null;
            }
            reject(error);
            return;
          }
          try {
            resolve(responseBody ? JSON.parse(responseBody) : {});
          } catch (error) {
            reject(new Error(`Backend returned invalid JSON: ${error.message}`));
          }
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("Backend request timed out."));
    });
    request.on("error", reject);
    request.end(body === undefined ? undefined : JSON.stringify(body));
  });
}

// ---------------------------------------------------------------------------
// Player: linked Steam account, match history, post-match reviews
// ---------------------------------------------------------------------------

// The renderer asks by operation name; only these paths are ever requested.
const PLAYER_OPS = {
  status: () => ["GET", "/player"],
  link: (args) => ["POST", "/player/link", { steam: String(args.steam || "").slice(0, 200) }],
  linkDetected: () => ["POST", "/player/link-detected"],
  unlink: () => ["DELETE", "/player"],
  sync: () => ["POST", "/player/sync"],
  matches: (args) => [
    "GET",
    `/player/matches?limit=${clampInt(args.limit, 1, 200, 30)}&offset=${clampInt(args.offset, 0, 100000, 0)}` +
      (/^\d{1,4}$/.test(String(args.heroId ?? "")) ? `&hero_id=${args.heroId}` : "") +
      (["win", "loss"].includes(args.result) ? `&result=${args.result}` : "") +
      (["score", "gpm", "lh_10", "duration", "kda"].includes(args.sort) ? `&sort=${args.sort}` : "") +
      (args.order === "asc" ? "&order=asc" : "")
  ],
  // Reviews may be rebuilt on read after an update (new analysis version): allow time.
  match: (args) => ["GET", `/player/matches/${matchIdArg(args)}?lang=${uiLocale()}`, undefined, 15000],
  refreshMatch: (args) => ["POST", `/player/matches/${matchIdArg(args)}/refresh`],
  addMatch: (args) => ["POST", `/player/matches/${matchIdArg(args)}/add`],
  // «Нотатка»: the player's own line on a match (200 characters at most).
  setNote: (args) => ["POST", `/player/matches/${matchIdArg(args)}/note`, { note: String(args.note || "").slice(0, 200) }],
  addMatchStatus: (args) => ["GET", `/player/matches/${matchIdArg(args)}/add`],
  week: () => ["GET", `/player/week?lang=${uiLocale()}`],
  profile: () => ["GET", `/player/profile?lang=${uiLocale()}`],
  profileMmr: (args) => ["POST", `/player/profile/mmr?lang=${uiLocale()}`, { mmr: clampInt(args.mmr, 0, 15000, 0) }],
  profileMmrClear: () => ["DELETE", `/player/profile/mmr?lang=${uiLocale()}`],
  shopBuy: (args) => ["POST", `/player/shop/buy?lang=${uiLocale()}`, { id: shopIdArg(args) }],
  shopEquip: (args) => ["POST", `/player/shop/equip?lang=${uiLocale()}`, { id: shopIdArg(args) }],
  session: () => ["GET", `/player/session?lang=${uiLocale()}`],
  summary: () => ["GET", `/player/summary?lang=${uiLocale()}`],
  // Compare with a friend (their public OpenDota matches, fetched by the backend).
  friend: (args) => ["GET", `/player/friend?lang=${uiLocale()}&group=${friendGroupArg(args)}`],
  friendSet: (args) => ["POST", `/player/friend?lang=${uiLocale()}`, { steam: String(args.steam || "").slice(0, 200) }],
  friendRefresh: () => ["POST", `/player/friend/refresh?lang=${uiLocale()}`],
  friendRemove: () => ["DELETE", "/player/friend"],
  career: (args) => [
    "GET",
    `/player/career?lang=${uiLocale()}` + (/^\d{1,4}$/.test(String(args.heroId ?? "")) ? `&hero_id=${args.heroId}` : ""),
    undefined,
    15000
  ],
  // AI coach (optional; the key is kept by the backend and never sent back).
  coachMatch: (args) => ["POST", `/player/matches/${matchIdArg(args)}/coach?lang=${uiLocale()}`],
  // A free question about a match: the model answers synchronously, and a failed fact
  // check asks once more (2 x 60 s in the backend): allow two and a half minutes.
  // The renderer's request id lets a retry after a lost answer join the same run
  // (backend ask_runs.py) instead of paying for a second one; askStatus reads it.
  ask: (args) => [
    "POST",
    `/player/matches/${matchIdArg(args)}/ask?lang=${uiLocale()}`,
    askBody(args),
    150000
  ],
  askStatus: (args) => ["GET", `/player/asks/${askRequestIdArg(args)}`, undefined, 10000],
  // The player's verdict on one live advice card (backend advice_feedback.py).
  adviceFeedback: (args) => [
    "POST",
    `/player/matches/${matchIdArg(args)}/advice-feedback`,
    {
      key: String(args.key || "").slice(0, 80),
      verdict: ["useful", "irrelevant", "repeated"].includes(args.verdict) ? args.verdict : null
    }
  ],
  // Automatic local copies (backend auto_backup.py); a copy of a long history
  // takes a few seconds, a preview reads it whole.
  backups: () => ["GET", "/player/backups"],
  backupMake: () => ["POST", "/player/backups", undefined, 120000],
  backupSettings: (args) => ["POST", "/player/backups/settings", { enabled: Boolean(args.enabled) }],
  backupPreview: (args) => ["GET", `/player/backups/${backupIdArg(args)}/preview`, undefined, 120000],
  backupRestore: (args) => ["POST", `/player/backups/${backupIdArg(args)}/restore`, undefined, 180000],
  coachCareer: () => ["POST", `/player/career/coach?lang=${uiLocale()}`],
  // A free question about the recent matches (same fact check, one retry).
  askCareer: (args) => [
    "POST",
    `/player/career/ask?lang=${uiLocale()}`,
    askBody(args),
    150000
  ],
  aiStatus: () => ["GET", "/player/ai"],
  aiSave: (args) => [
    "POST",
    "/player/ai",
    {
      provider: aiProviderArg(args),
      api_key: String(args.apiKey || "").trim().slice(0, 300),
      // Optional model id (e.g. stealth/space-bunny-alpha); empty = the service default.
      model: /^[\w./:-]{1,100}$/.test(String(args.model || "")) ? String(args.model) : null
    }
  ],
  aiClear: () => ["DELETE", "/player/ai"],
  // Optional OpenDota key (faster sync, higher limits); never sent back either.
  odStatus: () => ["GET", "/player/opendota"],
  odSave: (args) => ["POST", "/player/opendota", { api_key: String(args.apiKey || "").trim().slice(0, 100) }],
  odClear: () => ["DELETE", "/player/opendota"],
  // The one recurring problem the player works on (checked in every next match).
  focusSet: (args) => [
    "POST",
    `/player/focus?lang=${uiLocale()}`,
    { finding_id: /^[a-z0-9_]{1,60}$/.test(String(args.findingId || "")) ? String(args.findingId) : "" }
  ],
  focusClear: () => ["DELETE", "/player/focus"],
  // One real request to the provider: allow it time.
  aiCheck: () => ["POST", "/player/ai/check", undefined, 45000]
};

function friendGroupArg(args) {
  return ["all", "core", "support"].includes(args.group) ? args.group : "all";
}

// Where a player gets a free key (opened in the browser).
const AI_KEY_PAGES = {
  gemini: "https://aistudio.google.com/apikey",
  groq: "https://console.groq.com/keys",
  openrouter: "https://openrouter.ai/settings/keys"
};

function aiProviderArg(args) {
  const provider = String(args.provider || "");
  if (!Object.hasOwn(AI_KEY_PAGES, provider)) {
    throw new Error("Unknown AI provider.");
  }
  return provider;
}

function shopIdArg(args) {
  const id = String(args.id || "");
  return /^[a-z0-9_]{1,40}$/.test(id) ? id : "";
}

function clampInt(value, min, max, fallback) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
}

const BACKUP_ID = /^wardly-backup-\d{8}T\d{6}Z-(weekly|update|manual)\.json\.gz$/;

function backupIdArg(args) {
  const id = String(args.backupId || "");
  if (!BACKUP_ID.test(id)) {
    throw new Error("Invalid backup id.");
  }
  return id;
}

const ASK_REQUEST_ID = /^[A-Za-z0-9_-]{8,64}$/;

function askRequestIdArg(args) {
  const id = String(args.requestId || "");
  if (!ASK_REQUEST_ID.test(id)) {
    throw new Error("Invalid request id.");
  }
  return id;
}

function askBody(args) {
  const body = { question: String(args.question || "").slice(0, 300) };
  if (ASK_REQUEST_ID.test(String(args.requestId || ""))) {
    body.request_id = String(args.requestId);
  }
  return body;
}

function matchIdArg(args) {
  const id = String(args.matchId || "");
  if (!/^\d{1,20}$/.test(id)) {
    throw new Error("Invalid match id.");
  }
  return id;
}

async function playerRequest(op, args = {}) {
  const build = PLAYER_OPS[op];
  if (!build) {
    return { ok: false, code: "unknown_op" };
  }
  try {
    const [method, endpoint, body, timeoutMs] = build(args || {});
    return { ok: true, data: await requestBackendJson(endpoint, method, body, timeoutMs) };
  } catch (error) {
    const payload = error.payload || {};
    return {
      ok: false,
      status: error.status || 0,
      code: payload.code || (processStatus.backend !== "running" ? "backend_down" : "request_failed"),
      detail: payload.detail || error.message
    };
  }
}

// Every ~5 s: account + "a new post-match review is ready" (tray balloon).
// «Автоматичні копії»: ask the backend two minutes after it starts and then
// once a day; it decides whether a weekly or an update copy is due. Never
// during a match (a long history takes a few seconds to pack).
const AUTO_BACKUP_FIRST_MS = 2 * 60_000;
const AUTO_BACKUP_EVERY_MS = 24 * 3_600_000;
let autoBackupAt = 0;
let autoBackupBusy = false;

function maybeAutoBackup(now = Date.now()) {
  if (IS_SMOKE_TEST || autoBackupBusy || processStatus.backend !== "running" || live.inMatch) {
    return;
  }
  if (!autoBackupAt) {
    autoBackupAt = now + AUTO_BACKUP_FIRST_MS;
    return;
  }
  if (now < autoBackupAt) {
    return;
  }
  autoBackupBusy = true;
  autoBackupAt = now + AUTO_BACKUP_EVERY_MS;
  requestBackendJson("/player/backups/auto", "POST", undefined, 120000)
    .then((result) => {
      if (result && result.made) {
        appendLog("launcher", `History copy saved (${result.reason}).`, { force: true });
      }
    })
    .catch((error) => appendLog("launcher", `History copy failed: ${error.message}`, { force: true }))
    .finally(() => {
      autoBackupBusy = false;
    });
}

async function pollPlayerStatus() {
  const result = await playerRequest("status");
  if (!result.ok) {
    return;
  }
  const status = result.data || {};
  const review = status.last_review || null;
  const reviewKey = review ? `${review.match_id}|${review.at}` : "";
  const first = live.player === null;
  const previousKey = live.player ? live.player.reviewKey : "";
  const previousAccount = live.player ? live.player.accountId : null;
  // An account linked from GSI proves Dota already sent data (users updating
  // from a version without the first-run checklist).
  if (status.source === "gsi" && !settings.get("gsiSeenAt")) {
    settings.set("gsiSeenAt", new Date().toISOString());
  }
  live.player = {
    linked: Boolean(status.linked),
    name: status.player ? status.player.persona_name || null : null,
    avatar: status.player ? status.player.avatar_url || null : null,
    accountId: status.account_id || null,
    lastReview: review,
    reviewKey,
    aiConfigured: Boolean(status.ai && status.ai.configured),
    opendotaKey: Boolean(status.opendota_key),
    liveMatch: status.live_match || null,
    today: status.today || null,
    goals: Array.isArray(status.goals) ? status.goals : [],
    tilt: status.tilt || null
  };
  if (live.player.accountId !== previousAccount) {
    // Launch options are per Steam account: check the linked one.
    refreshLaunchOptions();
  }
  if (reviewKey !== previousKey) {
    // The tray's «latest match review» item follows the newest review.
    refreshTray();
  }
  if (!first && reviewKey && reviewKey !== previousKey) {
    const reviewsBefore = Number(settings.get("liveReviews")) || 0;
    settings.set("liveReviews", reviewsBefore + 1);
    const score = review.score !== null && review.score !== undefined ? ` ${review.score}/100` : "";
    appendLog("player", `Post-match review ready for match ${review.match_id}${score}.`, { force: true });
    showTrayBalloon(t("reviewReady", score, review.focus_met), { type: "open-match", matchId: review.match_id });
    send("launcher:player-event", { type: "review-ready", matchId: review.match_id, score: review.score });
    if (reviewsBefore === 0 && !(mainWindow && !mainWindow.isDestroyed() && mainWindow.isFocused())) {
      // The very first review: the panel turns to it (never pulled over the game),
      // so it is the first thing the player sees when they open the app.
      send("launcher:player-event", { type: "open-match", matchId: review.match_id });
    }
  }
  updateStatus();
}

async function fetchOverlayRecommendation() {
  try {
    const data = await requestBackendJson(`/overlay/recommendation?lang=${uiLocale()}`);
    skillArrows.update(data);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

// ---------------------------------------------------------------------------
// Replay demo
// ---------------------------------------------------------------------------

async function runDemo(presetName = "plMacro", includeDeepReview = false) {
  if (processes.demo) {
    appendLog("launcher", "Demo is already running. Stop Demo before starting another preset.", { force: true });
    return false;
  }
  if (processStatus.backend !== "running" || !(await isBackendReady())) {
    appendLog("launcher", "Backend is not ready yet. Wait for Backend: running, then retry.", { force: true });
    return false;
  }

  const preset = DEMO_PRESETS[presetName] || DEMO_PRESETS.plMacro;
  const args = [
    "--simulation-file",
    demoFileForPreset(preset),
    "--backend-url",
    backendUrl(),
    "--speed",
    "5",
    "--advice-hold-seconds",
    "8"
  ];
  if (includeDeepReview) {
    const slug = presetName === "juggSafety" ? "jugg_10_20" : "pl_20_30";
    args.push(
      "--export-deep-review",
      path.join(SIMULATION_RESULTS_DIR, `deep_review_${slug}.md`),
      "--export-deep-review-json",
      path.join(SIMULATION_RESULTS_DIR, `deep_review_${slug}.json`)
    );
  }

  const command = IS_PACKAGED ? packagedExecutable("dota-ai-coach-demo-playback") : pythonExecutable();
  const commandArgs = IS_PACKAGED ? args : ["-u", path.join("scripts", "run_overlay_demo.py"), ...args];
  if (IS_PACKAGED && !ensureExecutableExists("Demo playback", command)) {
    return false;
  }
  if (!overlay.isEnabled()) {
    overlay.setEnabled(true);
  }
  const child = spawnManaged("demo", command, commandArgs, {
    cwd: IS_PACKAGED ? WRITABLE_DIR : BACKEND_DIR,
    env: {
      PYTHONUNBUFFERED: "1",
      SIMULATION_USE_LLM: "false",
      USE_LLM: "false",
      DOTA_AI_CONTROL_TOKEN: localApiAuth().control,
      DOTA_AI_GSI_TOKEN: localApiAuth().gsi,
      DOTA_AI_BACKEND_PORT: String(backend.port)
    },
    onExit: () => {
      processStatus.demo = "stopped";
      mode = "Live GSI";
      currentDemoPreset = "";
      appendLog("launcher", "Demo stopped.", { force: true });
      refreshPresence();
      updateStatus();
    }
  });
  if (!child) {
    return false;
  }
  processStatus.demo = "running";
  currentDemoPreset = preset.label;
  mode = "Replay Demo";
  refreshPresence();
  appendLog("launcher", `Demo started: ${preset.label}`, { force: true });
  updateStatus();
  return true;
}

// ---------------------------------------------------------------------------
// Live GSI helpers
// ---------------------------------------------------------------------------

async function checkLiveGsiStatus() {
  try {
    const status = await requestBackendJson("/gsi/status");
    appendLog("live", formatLiveGsiStatus(status), { force: true });
    return status;
  } catch (error) {
    appendLog("live", `Could not check live GSI: ${error.message}`, { force: true });
    return { error: error.message };
  }
}

// The developer section's «Operations health» (backend operations_health.py).
async function operationsHealth() {
  try {
    return await requestBackendJson("/operations/health", "GET", undefined, 5000);
  } catch (error) {
    return { error: error.message };
  }
}

async function setLiveRecording(active) {
  const verb = active ? "start" : "stop";
  try {
    const status = await requestBackendJson(`/session-recording/${verb}`, "POST");
    recordingStatus = status.active ? "running" : "stopped";
    appendLog("recording", `Recording ${verb === "start" ? "started" : "stopped"}: ${status.session_dir || SESSION_RECORDS_DIR}`, {
      force: true
    });
    updateStatus();
    return status;
  } catch (error) {
    appendLog("recording", `Could not ${verb} recording: ${error.message}`, { force: true });
    updateStatus();
    return { error: error.message };
  }
}

function formatLiveGsiStatus(status) {
  if (status.error) {
    return status.error;
  }
  const connection = status.gsi_connected ? "connected" : "waiting/stale";
  const seconds = status.seconds_since_last_gsi ?? "n/a";
  const hero = status.hero || "unknown hero";
  const time = status.game_time ?? "unknown time";
  const stage = status.stage || "unknown";
  const missing = Array.isArray(status.missing_important_fields) && status.missing_important_fields.length
    ? ` missing=${status.missing_important_fields.join(", ")}`
    : " missing=none";
  return `GSI ${connection}; last=${seconds}s; hero=${hero}; game_time=${time}; stage=${stage}; mode=${status.current_mode};${missing}`;
}

// "heartbeat" keeps a paused match fresh for the backend's staleness check
// (GSI_STALE_SECONDS=5); otherwise the overlay would hide during pauses.
function gsiConfigText() {
  return renderGsiConfig(gsiEndpoint(), localApiAuth().gsi);
}

function refreshLaunchOptions() {
  let next;
  try {
    next = checkLaunchOptions({ steamRoots: dotaInstall.steamRoots, accountId: live.player ? live.player.accountId : null });
  } catch (error) {
    next = { state: "unknown", accountId: null };
    appendLog("gsi", `Launch options check failed: ${error.message}`, { force: true });
  }
  if (next.state !== launchOptions.state) {
    appendLog("gsi", `Dota launch option ${GSI_LAUNCH_OPTION}: ${next.state}`, { force: true });
    launchOptions = next;
    updateStatus();
  }
  launchOptions = next;
}

// Steam registry -> libraryfolders.vdf -> every library; the running
// dota2.exe path (from the watcher) is used as an extra hint.
function refreshDotaInstall() {
  if (!dotaLocatePromise) {
    const extraDotaDirs = [dotaDirFromExecutable(dotaWatcher.getState().exePath)].filter(Boolean);
    dotaLocatePromise = locateDota({ extraDotaDirs })
      .then((result) => {
        const changed = result.dotaDir !== dotaInstall.dotaDir;
        dotaInstall = result;
        refreshLaunchOptions();
        if (changed) {
          updateStatus();
        }
        if (changed || !dotaInstallLogged) {
          dotaInstallLogged = true;
          appendLog(
            "gsi",
            result.dotaDir
              ? `Dota 2 found: ${result.dotaDir}`
              : `Dota 2 not found. Steam libraries checked: ${result.libraries.join(", ") || "none"}`,
            { force: true }
          );
        }
        return result;
      })
      .catch((error) => {
        appendLog("gsi", `Dota 2 search failed: ${error.message}`, { force: true });
        return dotaInstall;
      })
      .finally(() => {
        dotaLocatePromise = null;
      });
  }
  return dotaLocatePromise;
}

function resolveGsiDir(customPath = "") {
  const trimmed = String(customPath || "").trim();
  if (trimmed) {
    return trimmed;
  }
  // A detected install wins over the saved path, which may point at a
  // folder Dota was moved away from.
  if (dotaInstall.gsiDir) {
    return dotaInstall.gsiDir;
  }
  const saved = String(settings.get("gsiConfigPath") || "");
  if (saved && fs.existsSync(path.dirname(saved))) {
    return path.dirname(saved);
  }
  return "";
}

function checkGsiConfig(customPath = "") {
  const dir = resolveGsiDir(customPath);
  if (!dir) {
    gsiStatus = { status: "not found", path: "" };
    updateStatus();
    return gsiStatus;
  }
  const filePath = path.join(dir, GSI_CONFIG_NAME);
  const installed = fs.existsSync(filePath);
  gsiStatus = { status: installed ? "installed" : "not found", path: filePath };
  appendLog("gsi", installed ? `Config found: ${filePath}` : `Config not found in: ${dir}`);
  updateStatus();
  return gsiStatus;
}

function installGsiConfig(customPath = "") {
  const dir = resolveGsiDir(customPath);
  if (!dir) {
    gsiStatus = { status: "not found", path: "" };
    appendLog("gsi", "Dota GSI folder was not found. Enter a custom gamestate_integration path.", { force: true });
    updateStatus();
    return gsiStatus;
  }
  try {
    fs.mkdirSync(dir, { recursive: true });
    const filePath = path.join(dir, GSI_CONFIG_NAME);
    fs.writeFileSync(filePath, gsiConfigText(), { encoding: "utf8", mode: 0o600 });
    fs.chmodSync(filePath, 0o600);
    settings.set("gsiConfigPath", filePath);
    gsiStatus = { status: "installed", path: filePath };
    appendLog("gsi", `Installed config: ${filePath} -> ${gsiEndpoint()}`, { force: true });
  } catch (error) {
    gsiStatus = { status: "error", path: dir };
    appendLog("gsi", `Could not write GSI config: ${error.message}`, { force: true });
  }
  updateStatus();
  return gsiStatus;
}

// The backend port can change between launches (e.g. 8000 taken by another
// program), and the config template can change between versions. Keep an
// installed Dota GSI config identical to what this version would write.
function syncGsiConfig() {
  const status = checkGsiConfig();
  if (status.status !== "installed") {
    return;
  }
  try {
    if (fs.readFileSync(status.path, "utf8") === gsiConfigText()) {
      return;
    }
    fs.writeFileSync(status.path, gsiConfigText(), { encoding: "utf8", mode: 0o600 });
    fs.chmodSync(status.path, 0o600);
    appendLog("gsi", `Updated GSI config (${gsiEndpoint()}). Restart Dota 2 if it is already running.`, {
      force: true
    });
  } catch (error) {
    appendLog("gsi", `Could not update GSI config: ${error.message}`, { force: true });
  }
}

// First run: install the GSI config as soon as Dota 2 is found. Once it has
// been installed (or found installed) the app only keeps it in sync, so a
// user who deletes it on purpose is not overridden.
async function autoInstallGsiOnce() {
  if (autoInstallRunning) {
    return;
  }
  autoInstallRunning = true;
  try {
    await refreshDotaInstall();
    if (settings.get("gsiAutoInstalled")) {
      syncGsiConfig();
      return;
    }
    if (checkGsiConfig().status === "installed") {
      settings.set("gsiAutoInstalled", true);
      syncGsiConfig();
      return;
    }
    if (!resolveGsiDir()) {
      appendLog("gsi", "Dota 2 not found yet; the GSI config will be installed as soon as it is.", {
        force: true
      });
      return;
    }
    if (installGsiConfig().status === "installed") {
      settings.set("gsiAutoInstalled", true);
      const restartHint = dotaWatcher.getState().running ? " Restart Dota 2 to start receiving game data." : "";
      appendLog("gsi", `GSI config installed automatically.${restartHint}`, { force: true });
      showTrayBalloon(t("gsiInstalled") + (restartHint ? ` ${t("restartDota")}` : ""));
    }
  } finally {
    autoInstallRunning = false;
  }
}

async function chooseGsiFolder() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose Dota gamestate_integration folder",
    properties: ["openDirectory", "createDirectory"]
  });
  if (result.canceled || !result.filePaths.length) {
    return "";
  }
  return result.filePaths[0];
}

// "Dota not found" action: let the user point at the Dota 2 folder itself
// (…\dota 2 beta) and install the GSI config inside it.
async function chooseDotaFolderAndInstall() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose the Dota 2 folder (dota 2 beta)",
    properties: ["openDirectory"]
  });
  if (result.canceled || !result.filePaths.length) {
    return { status: gsiStatus.status, path: gsiStatus.path, canceled: true };
  }
  const chosen = result.filePaths[0];
  const candidates = [chosen, path.join(chosen, "steamapps", "common", "dota 2 beta")];
  const dotaDir = candidates.find((dir) => fs.existsSync(path.join(dir, "game", "dota")));
  if (!dotaDir) {
    appendLog("gsi", `No Dota 2 install in ${chosen} (expected a "game\\dota" folder inside).`, { force: true });
    return { status: "not found", path: "", error: "not_dota_folder" };
  }
  dotaInstall = { ...dotaInstall, dotaDir, gsiDir: gsiDirForDotaDir(dotaDir), source: "chosen" };
  const status = installGsiConfig();
  if (status.status === "installed") {
    settings.set("gsiAutoInstalled", true);
  }
  updateStatus();
  return status;
}

function openPath(targetPath) {
  try {
    fs.mkdirSync(targetPath, { recursive: true });
  } catch {
    // openPath below reports the problem.
  }
  shell.openPath(targetPath).then((error) => {
    if (error) {
      appendLog("launcher", `Could not open ${targetPath}: ${error}`, { force: true });
    }
  });
}

// ---------------------------------------------------------------------------
// Problem report: one text file for the developer (keys removed)
// ---------------------------------------------------------------------------

function readLauncherLog() {
  let text = "";
  for (const file of [`${LAUNCHER_LOG_PATH}.old`, LAUNCHER_LOG_PATH]) {
    try {
      text += fs.readFileSync(file, "utf8");
    } catch {
      // Missing log file: nothing to add.
    }
  }
  return text || logs;
}

function reportFolder() {
  for (const name of ["downloads", "desktop", "documents"]) {
    try {
      const folder = app.getPath(name);
      if (folder && fs.existsSync(folder)) {
        return folder;
      }
    } catch {
      // Try the next folder.
    }
  }
  return USER_DATA_DIR;
}

function reportAppInfo() {
  return {
    version: app.getVersion(),
    packaged: IS_PACKAGED,
    electron: process.versions.electron,
    os: `${process.platform} ${os.release()} ${process.arch}`,
    locale: app.getLocale(),
    userData: USER_DATA_DIR
  };
}

async function collectProblemReport() {
  let diagnostics = null;
  let diagnosticsError = "";
  try {
    diagnostics = await requestBackendJson("/diagnostics", "GET", undefined, 5000);
  } catch (error) {
    diagnosticsError = error.message;
  }
  const { recentAdvice, player, ...status } = publicStatus();
  // The nickname stays out of the report (buildReport also removes ids).
  const { name: _name, ...playerState } = player || {};
  return buildReport({
    app: reportAppInfo(),
    status: {
      ...status,
      player: player ? playerState : null,
      recentAdviceCount: Array.isArray(recentAdvice) ? recentAdvice.length : 0
    },
    settings: settings.all(),
    settingsHealth: settings.health(),
    watcher: dotaWatcher.getState(),
    diagnostics,
    diagnosticsError,
    launcherLog: readLauncherLog()
  });
}

// «Зберігати записи матчів»: "list" → the backend's recordings of the week
// (and whether sending one to the developer is offered, with what was sent);
// {save: id} → that recording copied to Downloads; {upload: id} → the
// anonymized copy sent to the developer (the player confirmed it in the panel).
// The ids are checked by the backend, which only serves files of its own list.
async function matchRecordsAction(request) {
  if (request === "list") {
    try {
      const body = await requestBackendJson("/match-records");
      const config = await recordingsConfig();
      return {
        ok: true,
        records: Array.isArray(body.records) ? body.records : [],
        upload: uploadOffered(config, installId()),
        sent: pruneSent(settings.get("sentRecords"))
      };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }
  if (request && typeof request.upload === "string") {
    return uploadMatchRecord(request.upload);
  }
  const id = request && typeof request.save === "string" ? request.save : "";
  if (!/^[0-9A-Za-z_-]{1,64}$/.test(id)) {
    return { ok: false, error: "bad id" };
  }
  const filePath = path.join(reportFolder(), `Wardly-match-${id}.jsonl.gz`);
  try {
    await downloadBackendFile(`/match-records/${encodeURIComponent(id)}`, filePath);
  } catch (error) {
    appendLog("launcher", `Could not save the match recording: ${error.message}`, { force: true });
    return { ok: false, error: error.message };
  }
  appendLog("launcher", `Match recording saved: ${filePath}`, { force: true });
  shell.showItemInFolder(filePath);
  return { ok: true, path: filePath };
}

// /v1/config says whether recordings are on and which share of installations is
// asked. Kept for an hour; a failed read is "not offered" and retried in 5 minutes.
let recordingsConfigCache = { at: 0, ttl: 0, value: parseConfig(null) };

async function recordingsConfig() {
  const now = Date.now();
  if (now - recordingsConfigCache.at < recordingsConfigCache.ttl) {
    return recordingsConfigCache.value;
  }
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/config`, { signal: AbortSignal.timeout(5000) });
    recordingsConfigCache = { at: now, ttl: 3_600_000, value: parseConfig(response.ok ? await response.json() : null) };
  } catch {
    recordingsConfigCache = { at: now, ttl: 300_000, value: parseConfig(null) };
  }
  return recordingsConfigCache.value;
}

// The local backend's anonymized copy of one recording (match_record_upload.py):
// the gzip bytes with the hero and minutes in headers.
function fetchRecordingCopy(localId) {
  return new Promise((resolve) => {
    if (processStatus.backend !== "running") {
      resolve({ ok: false, code: "failed" });
      return;
    }
    const url = new URL(`/match-records/${encodeURIComponent(localId)}/upload`, backendUrl());
    const headers = controlHeaders(url, backendUrl(), localApiAuth().control);
    const request = http.get(url, { timeout: 60000, headers }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("error", () => resolve({ ok: false, code: "failed" }));
      response.on("end", () => {
        const body = Buffer.concat(chunks);
        if (response.statusCode !== 200) {
          let code = "failed";
          try {
            code = JSON.parse(body.toString("utf8")).code || code;
          } catch {
            // Not JSON: a plain failure.
          }
          resolve({ ok: false, code });
          return;
        }
        resolve({
          ok: true,
          body,
          hero: String(response.headers["x-upload-hero"] || ""),
          minutes: Number(response.headers["x-upload-minutes"]) || 0
        });
      });
    });
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", () => resolve({ ok: false, code: "failed" }));
  });
}

async function postRecording(headers, body) {
  const controller = new AbortController();
  // Up to 20 MB over a home connection.
  const timer = setTimeout(() => controller.abort(), 180_000);
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/session`, {
      method: "POST",
      headers,
      body,
      signal: controller.signal
    });
    let answer = {};
    try {
      answer = await response.json();
    } catch {
      // Not JSON (a proxy page): the status decides.
    }
    return response.ok && answer.id
      ? { ok: true, id: String(answer.id) }
      : { ok: false, code: answer.code || `http_${response.status}` };
  } catch {
    return { ok: false, code: "offline" };
  } finally {
    clearTimeout(timer);
  }
}

let recordingUploadActive = false;

async function uploadMatchRecord(localId) {
  if (!/^[0-9A-Za-z_-]{1,64}$/.test(localId)) {
    return { ok: false, code: "failed" };
  }
  // One at a time: two clicks never send the same 20 MB twice.
  if (recordingUploadActive) {
    return { ok: false, code: "busy" };
  }
  recordingUploadActive = true;
  try {
    const result = await sendRecording({
      localId,
      sent: settings.get("sentRecords"),
      installId: installId(),
      version: app.getVersion(),
      device: deviceHeaders(),
      getCopy: fetchRecordingCopy,
      post: postRecording
    });
    if (result.ok && !result.already) {
      settings.set("sentRecords", rememberSent(settings.get("sentRecords"), localId, result.id));
    }
    // No ids of the player's, no keys: only the outcome and the server's number.
    appendLog("launcher", result.ok ? `Match recording sent: ${result.id}` : `Match recording not sent: ${result.code}`, {
      force: true
    });
    return result;
  } finally {
    recordingUploadActive = false;
  }
}

function downloadBackendFile(endpointPath, filePath, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    if (processStatus.backend !== "running") {
      reject(new Error("Backend is not running."));
      return;
    }
    // Like every other local API call, the download carries the control token.
    const url = new URL(endpointPath, backendUrl());
    const headers = controlHeaders(url, backendUrl(), localApiAuth().control);
    const request = http.get(url, { timeout: timeoutMs, headers }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`Backend returned HTTP ${response.statusCode}`));
        return;
      }
      const out = fs.createWriteStream(filePath);
      const fail = (error) => {
        out.destroy();
        fs.rm(filePath, { force: true }, () => reject(error));
      };
      response.pipe(out);
      out.on("finish", () => out.close(() => resolve(filePath)));
      out.on("error", fail);
      response.on("error", fail);
    });
    request.on("timeout", () => request.destroy(new Error("timeout")));
    request.on("error", reject);
  });
}

async function saveProblemReport(text) {
  const body = typeof text === "string" && text ? text : await collectProblemReport();
  const filePath = path.join(reportFolder(), reportFileName());
  try {
    fs.writeFileSync(filePath, body, "utf8");
  } catch (error) {
    appendLog("launcher", `Could not save the problem report: ${error.message}`, { force: true });
    return { ok: false, error: error.message };
  }
  appendLog("launcher", `Problem report saved: ${filePath}`, { force: true });
  shell.showItemInFolder(filePath);
  return { ok: true, path: filePath };
}

// ---------------------------------------------------------------------------
// Sending the report to the developer (services/api, docs/DATA_PLAN.md stage 1).
// Only on the player's request; a report that cannot go out now waits in the
// outbox and is sent again later (on start and every hour).
// ---------------------------------------------------------------------------

const OUTBOX_DIR = path.join(USER_DATA_DIR, "outbox");
const OUTBOX_MAX_AGE_MS = 14 * 24 * 3_600_000;
const REPORT_UPLOAD_TIMEOUT_MS = 30_000;
let outboxTimer = null;
let outboxFlushing = false;

// The device key proves to the server that uploads are this installation's
// (services/api: only its hash is stored); sealed like the other secrets. None
// while its seal is not open yet, so a new key never replaces the sealed one.
function deviceKey() {
  if (settings.isLocked("deviceKey")) {
    return "";
  }
  let key = settings.get("deviceKey");
  if (typeof key !== "string" || !/^[a-f0-9]{64}$/.test(key)) {
    key = crypto.randomBytes(32).toString("hex");
    settings.set("deviceKey", key);
  }
  return key;
}

function deviceHeaders() {
  const key = deviceKey();
  return key ? { "x-device-key": key } : {};
}

function installId() {
  let id = settings.get("installId");
  if (typeof id !== "string" || !/^[a-z0-9-]{8,64}$/.test(id)) {
    id = crypto.randomUUID();
    settings.set("installId", id);
  }
  return id;
}

async function postReport(payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REPORT_UPLOAD_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/report`, {
      method: "POST",
      headers: { "content-type": "application/json", ...deviceHeaders() },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    let answer = {};
    try {
      answer = await response.json();
    } catch {
      // Not JSON (a proxy page): the status decides.
    }
    return response.ok && answer.id
      ? { ok: true, status: response.status, id: String(answer.id) }
      : { ok: false, status: response.status, code: answer.code || `http_${response.status}` };
  } catch (error) {
    return { ok: false, code: "offline", error: error.message };
  } finally {
    clearTimeout(timer);
  }
}

function countOutbox() {
  try {
    outboxCount = fs.readdirSync(OUTBOX_DIR).filter((name) => name.endsWith(".json")).length;
  } catch {
    outboxCount = 0;
  }
}

function rememberSentReport(id) {
  settings.set("lastReport", { id, at: new Date().toISOString() });
}

function queueReport(payload) {
  try {
    fs.mkdirSync(OUTBOX_DIR, { recursive: true });
    const name = `${Date.now()}-${crypto.randomBytes(3).toString("hex")}.json`;
    fs.writeFileSync(path.join(OUTBOX_DIR, name), JSON.stringify(payload), "utf8");
    for (const old of outboxOverflow(fs.readdirSync(OUTBOX_DIR))) {
      fs.rmSync(path.join(OUTBOX_DIR, old), { force: true });
    }
    countOutbox();
    return true;
  } catch (error) {
    appendLog("launcher", `Could not queue the problem report: ${error.message}`, { force: true });
    return false;
  }
}

async function sendProblemReport(note) {
  const text = await collectProblemReport();
  const info = reportAppInfo();
  const payload = uploadPayload({
    text,
    note,
    installId: installId(),
    app: { version: info.version, os: info.os, locale: uiLocale() }
  });
  const result = await postReport(payload);
  if (result.ok) {
    rememberSentReport(result.id);
    appendLog("launcher", `Problem report sent: ${result.id}`, { force: true });
    return { ok: true, id: result.id };
  }
  appendLog("launcher", `Problem report not sent: ${result.code} ${result.error || ""}`.trim(), { force: true });
  if (isRetryable(result) && queueReport(payload)) {
    return { ok: false, queued: true, code: result.code };
  }
  // Refused for good (or the outbox is not writable): keep a file instead.
  const saved = await saveProblemReport(withNote(text, note));
  return { ok: false, queued: false, code: result.code, path: saved.ok ? saved.path : "" };
}

async function flushOutbox() {
  if (outboxFlushing) {
    return;
  }
  outboxFlushing = true;
  try {
    let names = [];
    try {
      names = fs.readdirSync(OUTBOX_DIR).filter((name) => name.endsWith(".json")).sort();
    } catch {
      return;
    }
    for (const name of names) {
      const file = path.join(OUTBOX_DIR, name);
      let payload = null;
      try {
        if (Date.now() - fs.statSync(file).mtimeMs < OUTBOX_MAX_AGE_MS) {
          payload = JSON.parse(fs.readFileSync(file, "utf8"));
        }
      } catch {
        // Unreadable: dropped below.
      }
      if (!payload) {
        fs.rmSync(file, { force: true });
        continue;
      }
      const result = await postReport(payload);
      if (result.ok) {
        rememberSentReport(result.id);
        appendLog("launcher", `Queued problem report sent: ${result.id}`, { force: true });
        showTrayBalloon(t("reportSentLater", result.id));
      } else if (isRetryable(result)) {
        break; // Still offline or busy: try again at the next flush.
      } else {
        appendLog("launcher", `Queued problem report refused: ${result.code}`, { force: true });
      }
      fs.rmSync(file, { force: true });
    }
  } finally {
    outboxFlushing = false;
    countOutbox();
    updateStatus();
  }
}

function startOutbox() {
  countOutbox();
  setTimeout(() => flushOutbox().catch(() => {}), 60_000).unref?.();
  outboxTimer = setInterval(() => flushOutbox().catch(() => {}), 3_600_000);
  outboxTimer.unref?.();
}

// ---------------------------------------------------------------------------
// PDF export of the match review / progress page (light print theme in CSS)
// ---------------------------------------------------------------------------

const PDF_FOOTER = `<div style="width:100%;padding:0 12mm;display:flex;justify-content:space-between;font:8px sans-serif;color:#71717a">
<span>${APP_NAME}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;

async function exportPdf(kind, id) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return { ok: false, error: "no window" };
  }
  const stamp = new Date().toISOString().slice(0, 10);
  const fileName = kind === "match" && /^\d{1,20}$/.test(String(id))
    ? `Wardly-match-${id}.pdf`
    : `Wardly-progress-${stamp}.pdf`;
  const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(reportFolder(), fileName),
    filters: [{ name: "PDF", extensions: ["pdf"] }]
  });
  if (canceled || !filePath) {
    return { ok: false, canceled: true };
  }
  // The page margins are painted with the window background (dark): white while printing.
  mainWindow.setBackgroundColor("#ffffff");
  try {
    const data = await mainWindow.webContents.printToPDF({
      printBackground: true,
      pageSize: "A4",
      margins: { top: 0.4, bottom: 0.5, left: 0.4, right: 0.4 },
      displayHeaderFooter: true,
      headerTemplate: "<span></span>",
      footerTemplate: PDF_FOOTER
    });
    fs.writeFileSync(filePath, data);
  } catch (error) {
    appendLog("launcher", `Could not save the PDF: ${error.message}`, { force: true });
    return { ok: false, error: error.message };
  } finally {
    mainWindow.setBackgroundColor(WINDOW_BACKGROUND);
  }
  appendLog("launcher", `PDF saved: ${filePath}`, { force: true });
  shell.showItemInFolder(filePath);
  return { ok: true, path: filePath };
}

// ---------------------------------------------------------------------------
// Share a review or the Progress page: the public part (backend share_review.py /
// share_progress.py) goes to the API, which answers with a link; the delete
// token stays in settings.shares (keyed by match id, or "progress").
// ---------------------------------------------------------------------------

const SHARE_TIMEOUT_MS = 30_000;

function shareRecords() {
  const stored = settings.get("shares");
  const now = Date.now();
  const records = stored && typeof stored === "object" ? stored : {};
  // Links past their 90 days are gone on the server too.
  return Object.fromEntries(Object.entries(records).filter(([, record]) => record && Number(record.expiresAt) > now));
}

function publicShare(record) {
  return record ? { url: record.url, expiresAt: record.expiresAt, withCoach: Boolean(record.withCoach) } : null;
}

function shareStatus(matchId) {
  return { ok: true, share: publicShare(shareRecords()[matchId]) };
}

// `matchId` "progress": the Progress page (backend share_progress.py) instead of a match.
async function createShare(matchId, withCoach) {
  const progress = matchId === "progress";
  const coach = withCoach ? "true" : "false";
  let content;
  try {
    const payload = await requestBackendJson(
      progress
        ? `/player/career/share?lang=${uiLocale()}&coach=${coach}`
        : `/player/matches/${matchId}/share?lang=${uiLocale()}&coach=${coach}`,
      "GET",
      undefined,
      15000
    );
    content = progress ? { progress: payload.progress } : { review: payload.review };
  } catch (error) {
    return { ok: false, code: (error.payload && error.payload.code) || "backend_down" };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SHARE_TIMEOUT_MS);
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/share`, {
      method: "POST",
      headers: { "content-type": "application/json", ...deviceHeaders() },
      body: JSON.stringify({ install_id: installId(), version: app.getVersion(), ...content }),
      signal: controller.signal
    });
    let answer = {};
    try {
      answer = await response.json();
    } catch {
      // Not JSON: the status decides.
    }
    if (!response.ok || !answer.url || !answer.delete_token) {
      return { ok: false, code: answer.code || `http_${response.status}` };
    }
    const record = {
      id: String(answer.id),
      url: String(answer.url),
      token: String(answer.delete_token),
      expiresAt: Number(answer.expires_at),
      withCoach: Boolean(withCoach)
    };
    settings.set("shares", { ...shareRecords(), [matchId]: record });
    appendLog("launcher", `${progress ? "Progress" : `Review of match ${matchId}`} shared: ${record.url}`, { force: true });
    return { ok: true, share: publicShare(record) };
  } catch (error) {
    return { ok: false, code: "offline", error: error.message };
  } finally {
    clearTimeout(timer);
  }
}

async function deleteShareLink(matchId) {
  const records = shareRecords();
  const record = records[matchId];
  if (!record) {
    return { ok: true, share: null };
  }
  try {
    const response = await electronNet.fetch(`${apiUrl()}/v1/share/${encodeURIComponent(record.id)}`, {
      method: "DELETE",
      headers: { "x-delete-token": record.token }
    });
    // 404: already gone (expired or deleted elsewhere).
    if (!response.ok && response.status !== 404) {
      return { ok: false, code: `http_${response.status}` };
    }
  } catch (error) {
    return { ok: false, code: "offline", error: error.message };
  }
  delete records[matchId];
  settings.set("shares", records);
  appendLog("launcher", `Shared ${matchId === "progress" ? "progress" : `review of match ${matchId}`} deleted.`, { force: true });
  return { ok: true, share: null };
}

function shareMatchArg(value) {
  const text = String(value || "");
  return /^\d{1,20}$/.test(text) || text === "progress" ? text : null;
}

// History orchestration owns file/crypto/import steps; IPC remains trusted here.
const {exportHistory, importHistory, sendHistoryByCode, receiveHistoryByCode} = createHistoryTransfer({
  getWindow: () => mainWindow,
  dialog: IS_SMOKE_TEST ? {
    showSaveDialog: async () => ({canceled:false,filePath:path.join(SMOKE_PLAYER_DATA_DIR, "history-smoke.json.gz")}),
    showOpenDialog: async () => ({canceled:false,filePaths:[path.join(SMOKE_PLAYER_DATA_DIR, "history-smoke.json.gz")]})
  } : dialog,
  reportFolder,
  requestBackendJson,
  appendLog,
  showItemInFolder: file => { if (!IS_SMOKE_TEST) shell.showItemInFolder(file); },
  backendRunning: () => processStatus.backend === "running",
  fetch: (...args) => electronNet.fetch(...args),
  deviceHeaders,
  apiUrl,
  installId
});

// ---------------------------------------------------------------------------
// Advice frequency (sent at backend start and on change)
// ---------------------------------------------------------------------------

const ADVICE_FREQUENCIES = ["calm", "normal", "active"];

function adviceFrequency() {
  const value = settings.get("adviceFrequency");
  return ADVICE_FREQUENCIES.includes(value) ? value : "normal";
}

async function setAdviceFrequency(value) {
  if (!ADVICE_FREQUENCIES.includes(value)) {
    return publicStatus();
  }
  settings.set("adviceFrequency", value);
  try {
    await requestBackendJson("/settings/advice", "POST", { frequency: value });
  } catch (error) {
    // The backend reads the setting from its env at the next start.
    appendLog("launcher", `Advice frequency saved; the service applies it on start (${error.message}).`, { force: true });
  }
  updateStatus();
  return publicStatus();
}

const ADVICE_ROLES = ["auto", "carry", "mid", "offlane", "support"];

function adviceRole() {
  const value = settings.get("adviceRole");
  return ADVICE_ROLES.includes(value) ? value : "auto";
}

function mapHintsEnabled() {
  return settings.get("mapHints") !== false;
}

// Role and map hints: saved, then sent to the running service (or read from the
// env at its next start).
async function setAdvicePreferences(patch = {}) {
  const body = {};
  if (ADVICE_ROLES.includes(patch.role)) {
    settings.set("adviceRole", patch.role);
    body.role = patch.role;
  }
  if (typeof patch.mapHints === "boolean") {
    settings.set("mapHints", patch.mapHints);
    body.map_hints = patch.mapHints;
  }
  if (typeof patch.matchRecords === "boolean") {
    settings.set("matchRecords", patch.matchRecords);
    body.match_records = patch.matchRecords;
    appendLog("launcher", `Match recordings ${patch.matchRecords ? "on" : "off"}.`, { force: true });
  }
  if (Object.keys(body).length) {
    try {
      await requestBackendJson("/settings/advice", "POST", body);
    } catch (error) {
      appendLog("launcher", `Advice preferences saved; the service applies them on start (${error.message}).`, { force: true });
    }
  }
  updateStatus();
  return publicStatus();
}

function setLogMode(nextMode = "clean") {
  logMode = nextMode === "verbose" ? "verbose" : "clean";
  appendLog(
    "launcher",
    `Log mode set to ${logMode}.${hiddenBackendAccessLogs ? ` Hidden clean logs so far: backend=${hiddenBackendAccessLogs}.` : ""}`,
    { force: true }
  );
  updateStatus();
  return publicStatus();
}

// ---------------------------------------------------------------------------
// Windows, tray, autostart
// ---------------------------------------------------------------------------

function appIcon() {
  return nativeImage.createFromPath(path.join(ICON_DIR, process.platform === "win32" ? "icon.ico" : "icon.png"));
}

// The panel opens wide (side navigation, two columns) but never larger than
// 90 % of the screen; the size and "maximized" are remembered between runs.
const MAIN_WINDOW_DEFAULT = { width: 1280, height: 840 };
// A panel created hidden (behind the splash, or --hidden) is maximized when first shown.
let maximizeOnShow = false;

function mainWindowSize() {
  const area = screen.getPrimaryDisplay().workAreaSize;
  const saved = settings.get("mainWindow") || {};
  const pick = (value, fallback, max) => Math.min(Number.isFinite(value) && value >= 560 ? value : fallback, Math.round(max));
  return {
    width: pick(saved.width, MAIN_WINDOW_DEFAULT.width, area.width * 0.9),
    height: pick(saved.height, MAIN_WINDOW_DEFAULT.height, area.height * 0.9),
    maximized: saved.maximized === true
  };
}

function rememberMainWindowSize() {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMinimized()) {
    return;
  }
  const maximized = mainWindow.isMaximized();
  const bounds = maximized ? mainWindow.getNormalBounds() : mainWindow.getBounds();
  settings.set("mainWindow", { width: bounds.width, height: bounds.height, maximized });
}

function createMainWindow({ show = true } = {}) {
  const size = mainWindowSize();
  mainWindow = new BrowserWindow({
    width: size.width,
    height: size.height,
    minWidth: 560,
    minHeight: 560,
    title: APP_NAME,
    icon: appIcon(),
    backgroundColor: WINDOW_BACKGROUND,
    show,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  protectWindow(mainWindow);
  mainWindow.setMenuBarVisibility(false);
  if (size.maximized) {
    if (show) {
      mainWindow.maximize();
    } else {
      maximizeOnShow = true;
    }
  }
  let sizeTimer = null;
  const rememberSoon = () => {
    clearTimeout(sizeTimer);
    sizeTimer = setTimeout(rememberMainWindowSize, 500);
  };
  for (const eventName of ["resize", "maximize", "unmaximize"]) {
    mainWindow.on(eventName, rememberSoon);
  }
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  mainWindow.webContents.on("did-finish-load", applyUiScale);
  mainWindow.webContents.on("before-input-event", (event, input) => {
    const direction = uiScaleKey(input);
    if (direction !== null) {
      event.preventDefault();
      stepUiScale(direction);
    }
  });
  mainWindow.webContents.on("zoom-changed", (_event, direction) => stepUiScale(direction === "in" ? 1 : -1));

  // Closing the window only hides it; the coach keeps running in the tray.
  mainWindow.on("close", (event) => {
    if (isQuitting || IS_SMOKE_TEST) {
      return;
    }
    event.preventDefault();
    mainWindow.hide();
    showTrayHintOnce();
  });
  // Windows logoff/shutdown: let the window close so the session can end.
  mainWindow.on("session-end", () => {
    isQuitting = true;
    quitApp("Windows sign-out or shutdown");
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  return mainWindow;
}

// Start-up splash (splash/): the animated logo while the backend starts. The
// panel is created hidden behind it and shown once the backend runs (or could
// not start), after SPLASH_MAX_MS at the latest.
const SPLASH_MAX_MS = 25_000;
const SPLASH_SLOW_MS = 7_000;

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 280,
    height: 300,
    frame: false,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    center: true,
    show: false,
    title: APP_NAME,
    icon: appIcon(),
    backgroundColor: WINDOW_BACKGROUND,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  protectWindow(splashWindow);
  splashWindow.setMenuBarVisibility(false);
  splashWindow.loadFile(path.join(__dirname, "splash", "splash.html"), { query: { lang: uiLocale() } });
  splashWindow.once("ready-to-show", () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.show();
    }
  });
  const slow = setTimeout(() => splashCall("window.splash && window.splash.status('slow')"), SPLASH_SLOW_MS);
  const limit = setTimeout(() => finishSplash(), SPLASH_MAX_MS);
  splashWindow.on("closed", () => {
    clearTimeout(slow);
    clearTimeout(limit);
    splashWindow = null;
    // Closed by hand (Alt+F4): open the panel right away.
    if (!splashFinishing && !isQuitting) {
      revealMainWindow();
    }
  });
}

function splashCall(code) {
  if (!splashWindow || splashWindow.isDestroyed()) {
    return Promise.resolve(null);
  }
  return splashWindow.webContents.executeJavaScript(code).catch(() => null);
}

async function finishSplash() {
  if (!splashWindow || splashWindow.isDestroyed() || splashFinishing) {
    return;
  }
  splashFinishing = true;
  if (isQuitting) {
    splashWindow.destroy();
    return;
  }
  // The splash answers how long its exit animation needs (at most 2 s).
  const wait = Number(await splashCall("window.splash ? window.splash.done() : 0")) || 0;
  await delay(Math.min(Math.max(wait, 0), 2000));
  revealMainWindow();
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.destroy();
  }
}

function revealMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    return;
  }
  showPanel();
}

function showMainWindow() {
  // While the splash is up, the panel comes after it.
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.focus();
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  showPanel();
}

function showPanel() {
  if (maximizeOnShow) {
    maximizeOnShow = false;
    mainWindow.maximize();
  }
  mainWindow.show();
  mainWindow.focus();
}

function showTrayHintOnce() {
  if (settings.get("trayHintShown") || !tray) {
    return;
  }
  if (process.platform === "win32") {
    settings.set("trayHintShown", true);
    tray.displayBalloon({
      iconType: "info",
      title: APP_NAME,
      content: "Still running in the tray. Right-click the icon to toggle the overlay or quit."
    });
  } else if (process.platform === "linux") {
    // A desktop notification stands in for the tray balloon. Marked as shown
    // only when the desktop could show one, so a missing notification service
    // does not use up the hint.
    if (showDesktopNotification(t("trayHint"))) {
      settings.set("trayHintShown", true);
    }
  }
}

// Linux has no tray balloons: Electron's Notification (libnotify / D-Bus) is used.
let activeNotification = null;
function showDesktopNotification(content) {
  try {
    if (!Notification.isSupported()) {
      return false;
    }
    const notification = new Notification({ title: APP_NAME, body: content, icon: path.join(ICON_DIR, "icon.png") });
    notification.on("click", () => {
      showMainWindow();
      if (balloonAction) {
        send("launcher:player-event", balloonAction);
        balloonAction = null;
      }
    });
    // Held until it is closed, or the garbage collector may drop it before it shows.
    activeNotification = notification;
    notification.on("close", () => {
      if (activeNotification === notification) {
        activeNotification = null;
      }
    });
    notification.show();
    return true;
  } catch (error) {
    appendLog("launcher", `Desktop notification failed: ${error.message}`, { force: true });
    return false;
  }
}

const xdgAutostart = linuxDesktop.createXdgAutostart({
  log: (message) => appendLog("launcher", message, { force: true })
});

// Linux, at every start: say which display backend runs, make an AppImage show
// up in the app menu, and keep an enabled autostart entry pointing at the file
// that is running now (the AppImage may have been moved or updated).
function setUpLinuxDesktop() {
  const log = (message) => appendLog("launcher", message, { force: true });
  if (linuxStartup) {
    log(`Linux display backend: ${linuxStartup.display} (session ${linuxStartup.session || "unknown"}, DISPLAY=${process.env.DISPLAY || "none"}).`);
  }
  if (!IS_PACKAGED) {
    return;
  }
  linuxDesktop.ensureAppImageIntegration({ iconSource: path.join(ICON_DIR, "icon.png"), log });
  xdgAutostart.refresh();
}

function isAutostartSupported() {
  return IS_PACKAGED && (process.platform === "win32" || process.platform === "darwin" || process.platform === "linux");
}

// Before 0.5 the app was DotaAICoach.exe in the same folder. Its Start with
// Windows entry (same registry name: the AppUserModelId) still points at that
// file, which the update removed: point it at this exe. Electron lists only the
// run entries of the path it is asked about, so ask about the old exe.
const OLD_EXECUTABLES = ["DotaAICoach.exe"];

function migrateAutostartPath() {
  if (!isAutostartSupported() || process.platform !== "win32") {
    return;
  }
  try {
    const folder = path.dirname(process.execPath);
    const stale = OLD_EXECUTABLES.some((name) => {
      const old = app.getLoginItemSettings({ path: path.join(folder, name), args: ["--hidden"] });
      return Boolean(old.openAtLogin) || (old.launchItems || []).some((item) => item.enabled !== false);
    });
    if (stale && !isAutostartEnabled()) {
      app.setLoginItemSettings({ ...loginItemOptions(), openAtLogin: true });
      appendLog("launcher", "Start with Windows now starts the renamed app.", { force: true });
    }
  } catch (error) {
    appendLog("launcher", `Start with Windows migration failed: ${error.message}`, { force: true });
  }
}

function loginItemOptions() {
  return { path: process.execPath, args: ["--hidden"] };
}

function isAutostartEnabled() {
  if (!isAutostartSupported()) {
    return false;
  }
  if (process.platform === "linux") {
    return xdgAutostart.isEnabled();
  }
  try {
    return Boolean(app.getLoginItemSettings(loginItemOptions()).openAtLogin);
  } catch {
    return false;
  }
}

function setAutostart(enabled) {
  if (!isAutostartSupported()) {
    appendLog("launcher", "Start with the system is available in the installed build only.", { force: true });
    return false;
  }
  if (process.platform === "linux") {
    xdgAutostart.set(Boolean(enabled));
  } else {
    app.setLoginItemSettings({ ...loginItemOptions(), openAtLogin: Boolean(enabled) });
  }
  appendLog("launcher", `Start with the system: ${enabled ? "on" : "off"}.`, { force: true });
  autostartEnabled = isAutostartEnabled();
  updateStatus();
  refreshTray();
  return autostartEnabled;
}

function createTray() {
  const trayImage = process.platform === "win32"
    ? nativeImage.createFromPath(path.join(ICON_DIR, "icon.ico"))
    : nativeImage.createFromPath(path.join(ICON_DIR, "tray.png"));
  tray = new Tray(trayImage);
  tray.on("click", showMainWindow);
  tray.on("double-click", showMainWindow);
  tray.on("balloon-click", () => {
    showMainWindow();
    if (balloonAction) {
      send("launcher:player-event", balloonAction);
      balloonAction = null;
    }
  });
  refreshTray();
}

function refreshTray() {
  if (!tray || tray.isDestroyed()) {
    return;
  }
  const statusLine = t(presence.status);
  const backendLine = `${t("backend")}: ${(t("backendStates") || {})[processStatus.backend] || processStatus.backend}`;
  const fullscreen = fullscreenWarningActive();
  const update = updater.getState();
  const tooltipLines = [`${APP_NAME} — ${statusLine}`, fullscreen ? t("fullscreenMenu") : "", backendLine];
  tray.setToolTip(tooltipLines.filter(Boolean).join("\n"));
  const topItems = [{ label: statusLine, enabled: false }];
  if (fullscreen) {
    topItems.push({ label: t("fullscreenMenu"), enabled: false });
  }
  if (update.status === UPDATE_STATUS.AVAILABLE && !isGameRunning()) {
    topItems.push({ label: t("updateAvailable", update.version), click: () => updater.openDownload(openExternalUrl) });
  } else if (update.status === UPDATE_STATUS.READY && isGameRunning()) {
    topItems.push({ label: t("updateAfterGame", update.version), enabled: false });
  } else if (update.status === UPDATE_STATUS.READY) {
    topItems.push({ label: t("updateReady", update.version), click: () => updater.install() });
  } else if (update.status === UPDATE_STATUS.DOWNLOADING) {
    topItems.push({ label: t("updateDownloading", update.version, update.percent), enabled: false });
  }
  tray.setContextMenu(
    Menu.buildFromTemplate([
      ...topItems,
      { type: "separator" },
      { label: t("open"), click: showMainWindow },
      // Straight to the newest review (it opens the panel on it).
      ...(live.player && live.player.lastReview
        ? [{
            label: t("lastReview", live.player.lastReview.score),
            click: () => {
              showMainWindow();
              send("launcher:player-event", { type: "open-match", matchId: live.player.lastReview.match_id });
            }
          }]
        : []),
      {
        label: t("overlay"),
        type: "checkbox",
        checked: overlay.isEnabled(),
        click: (item) => overlay.setEnabled(item.checked)
      },
      {
        label: t("voice"),
        submenu: ["off", "urgent", "all"].map((mode) => ({
          label: t(`voice_${mode}`),
          type: "radio",
          checked: overlay.voice().mode === mode,
          // setVoice notifies onChange, which refreshes the tray and the panel.
          click: () => overlay.setVoice(mode)
        }))
      },
      {
        label: t(process.platform === "win32" ? "autostartWindows" : process.platform === "linux" ? "autostartSystem" : "autostartLogin"),
        type: "checkbox",
        checked: autostartEnabled,
        enabled: isAutostartSupported(),
        click: (item) => setAutostart(item.checked)
      },
      { type: "separator" },
      { label: backendLine, enabled: false },
      { label: t("problemReport"), click: () => saveProblemReport() },
      { type: "separator" },
      { label: t("quit"), click: () => quitApp("the tray menu") }
    ])
  );
}

function showTrayBalloon(content, action = null) {
  balloonAction = action;
  if (process.platform === "linux") {
    showDesktopNotification(content);
    return;
  }
  if (!tray || tray.isDestroyed() || process.platform !== "win32") {
    return;
  }
  tray.displayBalloon({ iconType: "info", title: APP_NAME, content });
}

// Only addresses the launcher itself produced (the update check's release link).
function openExternalUrl(url) {
  shell.openExternal(url).catch((error) => appendLog("update", `Could not open ${url}: ${error.message}`, { force: true }));
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

function registerIpc() {
  const handleLauncher = trustedHandlers(ipcMain, () => mainWindow, path.join(__dirname, "renderer", "index.html"));
  const handleOverlay = trustedHandlers(ipcMain, () => overlay.window(), path.join(__dirname, "overlay", "index.html"));
  handleLauncher("launcher:get-status", () => publicStatus());
  handleLauncher("launcher:get-logs", () => logs);
  handleLauncher("launcher:clear-logs", () => {
    logs = "";
    hiddenBackendAccessLogs = 0;
    send("launcher:logs", logs);
    return true;
  });
  handleLauncher("launcher:copy-launch-option", () => {
    clipboard.writeText(GSI_LAUNCH_OPTION);
    return { ok: true, text: GSI_LAUNCH_OPTION };
  });
  // The checklist's «start Dota 2»: Steam starts the game (a fixed URL, nothing from the page).
  handleLauncher("launcher:launch-dota", async () => {
    try {
      await shell.openExternal(DOTA_STEAM_URL);
      appendLog("launcher", "Dota 2 started from the first-run checklist.", { force: true });
      return { ok: true };
    } catch (error) {
      appendLog("launcher", `Could not start Dota 2 through Steam: ${error.message}`, { force: true });
      return { ok: false, code: "steam" };
    }
  });
  // «Watch this moment» in a review: only a replay tick number crosses the
  // bridge, the command text is built here.
  handleLauncher("launcher:copy-replay-tick", (_event, tick) => {
    if (!Number.isInteger(tick) || tick < 0 || tick > 10_000_000) {
      return { ok: false };
    }
    const text = `demo_gototick ${tick}`;
    clipboard.writeText(text);
    return { ok: true, text };
  });
  handleLauncher("launcher:copy-logs", () => {
    clipboard.writeText(logs);
    return true;
  });
  handleLauncher("launcher:start-backend", () => startBackend());
  handleLauncher("launcher:stop-backend", () => stopBackend());
  handleLauncher("launcher:restart-backend", () => restartBackend());
  handleLauncher("launcher:start-overlay", () => overlay.setEnabled(true));
  handleLauncher("launcher:stop-overlay", () => overlay.setEnabled(false));
  handleLauncher("launcher:set-autostart", (_event, enabled) => setAutostart(enabled));
  handleLauncher("launcher:run-demo", (_event, presetName) => runDemo(presetName, false));
  handleLauncher("launcher:run-deep-review", (_event, presetName) => runDemo(presetName, true));
  handleLauncher("launcher:stop-demo", () => stopManaged("demo"));
  handleLauncher("launcher:set-log-mode", (_event, nextMode) => setLogMode(nextMode));
  handleLauncher("launcher:check-live-gsi", () => checkLiveGsiStatus());
  handleLauncher("launcher:operations-health", () => operationsHealth());
  handleLauncher("launcher:start-live-recording", () => setLiveRecording(true));
  handleLauncher("launcher:stop-live-recording", () => setLiveRecording(false));
  handleLauncher("launcher:check-gsi", async (_event, customPath) => {
    await refreshDotaInstall();
    return checkGsiConfig(customPath);
  });
  handleLauncher("launcher:install-gsi", async (_event, customPath) => {
    await refreshDotaInstall();
    return installGsiConfig(customPath);
  });
  handleLauncher("launcher:choose-gsi-folder", () => chooseGsiFolder());
  handleLauncher("launcher:choose-dota-folder", () => chooseDotaFolderAndInstall());
  handleLauncher("launcher:set-overlay-position", (_event, preset) => {
    overlay.setPosition(String(preset || ""));
    return publicStatus();
  });
  handleLauncher("launcher:set-language", (_event, value) => setLanguage(String(value || "")));
  handleLauncher("launcher:set-ui-scale", (_event, value) => setUiScale(value));
  handleLauncher("launcher:set-advice-frequency", (_event, value) => setAdviceFrequency(String(value || "")));
  handleLauncher("launcher:set-discord-presence", (_event, enabled) => setDiscordPresence(Boolean(enabled)));
  handleLauncher("launcher:set-share-stats", (_event, enabled) => setShareStats(Boolean(enabled)));
  handleLauncher("launcher:stats-preview", () => statsPreview());
  handleLauncher("launcher:match-records", (_event, request) => matchRecordsAction(request));
  handleLauncher("launcher:friends", (_event, request) => friendsAction(request));
  handleLauncher("launcher:delete-server-data", () => deleteServerData());
  handleLauncher("launcher:discord-weekly", (_event, request) => discordWeeklyAction(request));
  handleLauncher("launcher:set-advice-preferences", (_event, patch) =>
    setAdvicePreferences(patch && typeof patch === "object" ? patch : {})
  );
  handleLauncher("launcher:set-overlay-size", (_event, name) => {
    overlay.setSize(String(name || ""));
    return publicStatus();
  });
  handleLauncher("launcher:set-overlay-display", (_event, patch) => {
    overlay.setDisplay(patch && typeof patch === "object" ? patch : {});
    return publicStatus();
  });
  handleLauncher("launcher:set-overlay-voice", (_event, mode, volume) => {
    overlay.setVoice(String(mode || ""), volume);
    return publicStatus();
  });
  handleLauncher("launcher:set-overlay-locked", (_event, locked) => {
    overlay.setLocked(Boolean(locked));
    if (!locked && overlay.isEnabled()) {
      // The sample card is on screen (only an enabled overlay shows it): the checklist's «see an advice» step is done.
      settings.set("overlayPreviewed", true);
    }
    return publicStatus();
  });
  handleLauncher("launcher:dismiss-fullscreen-warning", () => {
    settings.set("fullscreenWarningDismissed", true);
    updateStatus();
    refreshTray();
    return publicStatus();
  });
  handleLauncher("launcher:check-updates", async () => {
    await updater.check();
    return publicStatus();
  });
  handleLauncher("launcher:install-update", () => updater.install());
  handleLauncher("launcher:open-update-page", () => updater.openDownload(openExternalUrl));
  handleLauncher("launcher:player", (_event, op, args) => playerRequest(String(op || ""), args || {}));
  handleLauncher("launcher:open-logs", () => openPath(LOGS_DIR));
  handleLauncher("launcher:save-problem-report", () => saveProblemReport());
  handleLauncher("launcher:preview-problem-report", () => collectProblemReport());
  handleLauncher("launcher:send-problem-report", (_event, note) => sendProblemReport(String(note || "")));
  handleLauncher("launcher:open-privacy", () => shell.openExternal(`${PRIVACY_URL}?lang=${uiLocale()}`));
  // Windows Settings → Time & language → Speech, where a Ukrainian voice is added.
  handleLauncher("launcher:open-speech-settings", () =>
    process.platform === "win32" ? shell.openExternal("ms-settings:speech") : false
  );
  // The invite card: «copy the link» puts the site link (tagged ?ref=invite, in
  // the player's language) on the clipboard; either answer hides the card for good.
  handleLauncher("launcher:invite", (_event, action) => {
    if (action === "copy") {
      clipboard.writeText(inviteUrl());
    }
    if (action === "copy" || action === "dismiss") {
      settings.set("inviteDone", true);
    }
    return publicStatus();
  });
  // The Home card «help improve the advice»: «yes» turns the anonymous
  // statistics on (as the switch in Settings does), either answer hides the card.
  handleLauncher("launcher:stats-answer", (_event, answer) => {
    if (answer !== "yes" && answer !== "no") {
      return publicStatus();
    }
    settings.set("statsAsked", true);
    return answer === "yes" ? setShareStats(true) : publicStatus();
  });
  // «Підсумок вечора»: copy its text (built by the backend, re-read here, never taken
  // from the page) or hide the card of that sitting.
  handleLauncher("launcher:session", async (_event, action) => {
    if (action === "copy") {
      const result = await playerRequest("session");
      const session = result.ok && result.data ? result.data.session : null;
      if (!session || typeof session.text !== "string") {
        return { ok: false };
      }
      clipboard.writeText(session.text);
      return { ok: true };
    }
    if (action && typeof action === "object" && typeof action.dismiss === "string" && action.dismiss.length <= 64) {
      settings.set("sessionSeen", action.dismiss);
      return { ok: true, status: publicStatus() };
    }
    return { ok: false };
  });
  handleLauncher("launcher:tour-done", () => {
    settings.set("tourDone", true);
    return publicStatus();
  });
  handleLauncher("launcher:dismiss-whats-new", () => {
    settings.set("whatsNewPending", "");
    settings.set("whatsNewFrom", "");
    return publicStatus();
  });
  handleLauncher("launcher:dismiss-setup", () => {
    settings.set("setupDismissed", true);
    return publicStatus();
  });
  handleLauncher("launcher:share-status", (_event, matchId) =>
    shareMatchArg(matchId) ? shareStatus(shareMatchArg(matchId)) : { ok: false, code: "bad_match" }
  );
  handleLauncher("launcher:share-create", (_event, matchId, withCoach) =>
    shareMatchArg(matchId) ? createShare(shareMatchArg(matchId), Boolean(withCoach)) : { ok: false, code: "bad_match" }
  );
  handleLauncher("launcher:share-delete", (_event, matchId) =>
    shareMatchArg(matchId) ? deleteShareLink(shareMatchArg(matchId)) : { ok: false, code: "bad_match" }
  );
  handleLauncher("launcher:share-copy", (_event, matchId) => {
    const record = shareMatchArg(matchId) ? shareRecords()[shareMatchArg(matchId)] : null;
    if (record) {
      clipboard.writeText(record.url);
    }
    return Boolean(record);
  });
  handleLauncher("launcher:share-open", (_event, matchId) => {
    const record = shareMatchArg(matchId) ? shareRecords()[shareMatchArg(matchId)] : null;
    // Only our own share pages: the API's address or the site's (Workers route).
    const ours = record && [`${apiUrl()}/r/`, "https://luhovyimvp.dev/r/"].some((prefix) => record.url.startsWith(prefix));
    return ours ? shell.openExternal(record.url) : false;
  });
  handleLauncher("launcher:backup-export", () => exportHistory());
  handleLauncher("launcher:backup-import", () => importHistory());
  handleLauncher("launcher:transfer-send", () => sendHistoryByCode());
  handleLauncher("launcher:transfer-receive", (_event, code) => receiveHistoryByCode(String(code || "").slice(0, 40)));
  handleLauncher("launcher:export-pdf", (_event, kind, id) =>
    exportPdf(kind === "match" ? "match" : "career", String(id || ""))
  );
  handleLauncher("launcher:open-simulation-results", () => openPath(SIMULATION_RESULTS_DIR));
  handleLauncher("launcher:open-session-records", () => openPath(SESSION_RECORDS_DIR));
  handleLauncher("launcher:open-readme", () => shell.openPath(README_PATH));
  // A match on the sites players already use: fixed addresses, a numeric id only.
  handleLauncher("launcher:open-match-site", (_event, site, matchId) => {
    const sites = {
      opendota: "https://www.opendota.com/matches/",
      dotabuff: "https://www.dotabuff.com/matches/",
      stratz: "https://stratz.com/matches/"
    };
    const id = String(matchId ?? "");
    return Object.hasOwn(sites, String(site)) && /^\d{1,20}$/.test(id) ? shell.openExternal(sites[String(site)] + id) : false;
  });
  handleLauncher("launcher:open-ai-key-page", (_event, provider) => {
    const pages = { ...AI_KEY_PAGES, opendota: "https://www.opendota.com/api-keys" };
    const url = pages[String(provider)];
    return url && Object.hasOwn(pages, String(provider)) ? shell.openExternal(url) : false;
  });

  handleOverlay("overlay:get-config", () => overlay.publicConfig());
  skillArrows.registerIpc(() => updateStatus());
  handleLauncher("launcher:skill-arrows", (_event, action) => {
    if (action === "calibrate") {
      skillArrows.startCalibration();
    } else if (action === "reset") {
      skillArrows.resetCalibration();
    } else if (action === "on" || action === "off") {
      skillArrows.setEnabled(action === "on");
    }
    return publicStatus();
  });
  handleOverlay("overlay:fetch-recommendation", () => fetchOverlayRecommendation());
  // What the system voice did (overlay/voice.js): each change once, a few per
  // session at most, so a report says why a player hears nothing.
  let voiceLines = 0;
  handleOverlay("overlay:voice-event", (_event, voiceEvent) => {
    const line = OverlayVoice.voiceLogLine(voiceEvent);
    if (line && voiceLines < VOICE_LOG_LIMIT) {
      voiceLines += 1;
      appendLog("voice", line, { force: true });
    }
    return Boolean(line);
  });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

async function shutdownChildren() {
  stopGsiPolling();
  discord.stop();
  dotaWatcher.stop();
  updater.stop();
  overlay.dispose();
  skillArrows.dispose();
  if (processes.demo) {
    await stopManaged("demo");
  }
  if (processes.backend) {
    await stopBackend();
  }
}

function waitForEvent(emitter, eventName, timeoutMs) {
  return new Promise((resolve) => {
    const onEvent = (value) => {
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => {
      emitter.off(eventName, onEvent);
      resolve(null);
    }, timeoutMs);
    emitter.once(eventName, onEvent);
  });
}

function waitForWatcherState(predicate, timeoutMs) {
  return new Promise((resolve) => {
    if (predicate(dotaWatcher.getState())) {
      resolve(dotaWatcher.getState());
      return;
    }
    const onReport = (state) => {
      if (predicate(state)) {
        clearTimeout(timer);
        dotaWatcher.off("report", onReport);
        resolve(state);
      }
    };
    const timer = setTimeout(() => {
      dotaWatcher.off("report", onReport);
      resolve(null);
    }, timeoutMs);
    dotaWatcher.on("report", onReport);
  });
}

function waitForLoad(webContents, timeoutMs = 20000) {
  if (!webContents.isLoading() && webContents.getURL()) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    webContents.once("did-finish-load", () => {
      clearTimeout(timer);
      resolve(true);
    });
    webContents.once("did-fail-load", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });
}

// `--smoke-test=<result.json>`: start the bundled backend exactly like a user
// launch would, check /health, stop it gracefully and exit. Used by CI.
async function runSmokeTest(resultPath) {
  const steps = [];
  const step = (name, ok, detail = "") => {
    steps.push({ name, ok: Boolean(ok), detail: String(detail) });
    appendLog("smoke", `${ok ? "PASS" : "FAIL"} ${name}${detail ? `: ${detail}` : ""}`, { force: true });
  };
  try {
    createMainWindow({ show: false });
    step("main window loaded", await waitForLoad(mainWindow.webContents));
    const overlayWindow = overlay.open();
    step("overlay window loaded", await waitForLoad(overlayWindow.webContents));

    const install = await locateDota();
    step("steam/dota locator", true, install.dotaDir || `Dota 2 not installed; libraries: ${install.libraries.join(", ") || "none"}`);

    if ((process.platform === "win32" || process.platform === "linux") && process.env.DOTA_AI_SMOKE_FAKE_DOTA === "1") {
      // scripts/smoke-windows.ps1 runs a plain window named dota2.exe (Linux: a
      // process called dota2 with an X window): the helper must find its window
      // rect and the overlay must move into it.
      dotaWatcher.start();
      const state = await waitForWatcherState((item) => item.running && item.windowRect, 30000);
      step("dota watcher finds the dota2.exe window", Boolean(state), JSON.stringify(dotaWatcher.getState()));
      step(
        "no exclusive fullscreen for a normal window",
        Boolean(state) && !state.exclusiveFullscreen,
        JSON.stringify(dotaWatcher.getState())
      );
      overlay.refreshPlacement();
      const bounds = overlayWindow.getBounds();
      const rect = state ? state.windowRect : null;
      step(
        "overlay placed inside the Dota window",
        Boolean(rect) &&
          bounds.x >= rect.x &&
          bounds.y >= rect.y &&
          bounds.x + bounds.width <= rect.x + rect.width &&
          bounds.y + bounds.height <= rect.y + rect.height,
        JSON.stringify({ overlay: bounds, dota: rect })
      );
      dotaWatcher.stop();
    } else if (process.platform === "win32") {
      // The real watcher (hidden PowerShell + user32) must report, and with no
      // dota2.exe running the overlay must stay hidden.
      const report = waitForEvent(dotaWatcher, "report", 30000);
      dotaWatcher.start();
      const state = await report;
      step("dota watcher reports", Boolean(state && state.supported), JSON.stringify(state));
      refreshPresence();
      step("overlay hidden without Dota", !overlay.isVisible(), presence.reason);
      dotaWatcher.stop();
    } else if (process.platform === "linux") {
      // The /proc scan (and xprop/xwininfo when installed) must report, and with
      // no dota2 process running the overlay must stay hidden. Without the X
      // tools focus tracking is off by design (the overlay follows its switch),
      // so "supported" is only required when DOTA_AI_SMOKE_REQUIRE_FOCUS_TRACKING=1.
      const report = waitForEvent(dotaWatcher, "report", 30000);
      dotaWatcher.start();
      const state = await report;
      const requireTracking = process.env.DOTA_AI_SMOKE_REQUIRE_FOCUS_TRACKING === "1";
      step(
        "dota watcher reports",
        Boolean(state) && !state.running && (!requireTracking || state.supported),
        JSON.stringify(state)
      );
      refreshPresence();
      step(
        "overlay hidden without Dota",
        !overlay.isVisible() || !state || !state.supported,
        state && state.supported ? presence.reason : "focus tracking unavailable (xprop/xwininfo missing or no X display)"
      );
      dotaWatcher.stop();
    }

    if (IS_PACKAGED && (process.platform === "win32" || process.platform === "linux")) {
      // electron-builder writes app-update.yml only when "publish" is set.
      let updaterDetail = path.join(process.resourcesPath, "app-update.yml");
      let updaterOk = fs.existsSync(updaterDetail);
      try {
        require("electron-updater");
      } catch (error) {
        updaterOk = false;
        updaterDetail = error.message;
      }
      step("auto-update configured", updaterOk, `${updaterDetail} (a real run would use mode ${updateModeFor({ isPackaged: IS_PACKAGED })})`);
    }

    const started = await startBackend();
    step("backend /health", started && (await isBackendReady()), backendUrl());
    const rejected = await fetch(`${backendUrl()}/session/reset`, { method: "POST" });
    step("unauthorized local mutation rejected", rejected.status === 401);
    const foreignOrigin = await fetch(`${backendUrl()}/session/reset`, {
      method: "POST",
      headers: { ...controlHeaders(backendUrl(), backendUrl(), localApiAuth().control), Origin: "https://audit.invalid" },
      body: "{}",
    });
    step("foreign origin rejected", foreignOrigin.status === 403);
    const valveToken = gsiConfigText().match(/"token"\s+"([a-f0-9]{64})"/)?.[1];
    const valve = await fetch(`${backendUrl()}/gsi`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auth: { token: valveToken }, provider: { name: "Dota 2" }, map: { game_state: "DOTA_GAMERULES_STATE_PRE_GAME" } }),
    });
    step("Valve config token accepted", Boolean(valveToken) && valve.status === 200);
    const gsiControl = await fetch(`${backendUrl()}/player`, { headers: { Authorization: `Bearer ${valveToken}` } });
    step("GSI token cannot access player data", gsiControl.status === 401);
    // Both renderers must have drawn their UI from live data (catches script
    // errors that a plain "page loaded" check would miss). Only app.js sets
    // these values: the static HTML has data-state="starting", "—" and an empty action.
    await delay(1500);
    // The port is in the status line's tooltip since 0.44 (a developer's detail).
    const panel = await mainWindow.webContents.executeJavaScript(
      "({ state: document.querySelector('#service')?.dataset.state || '', text: document.querySelector('#service-text')?.textContent || '', title: document.querySelector('#service')?.title || '' })"
    );
    step(
      "control panel rendered",
      panel.state === "running" && Boolean(panel.text.trim()) && panel.title.includes(String(backend.port)),
      `${panel.state}: ${panel.text} (${panel.title})`
    );
    const overlayAction = await overlayWindow.webContents.executeJavaScript(
      "document.querySelector('#action')?.textContent || ''"
    );
    step("overlay card rendered", Boolean(overlayAction.trim()), overlayAction);

    // Player history (SQLite store, match reviews) must work in the bundled backend.
    const player = await playerRequest("status");
    step("player API", player.ok && typeof player.data.linked === "boolean", JSON.stringify(player.ok ? player.data.sync : player));
    step("smoke player store is isolated and initially empty", player.ok && !player.data.linked && player.data.matches === 0 && fs.existsSync(path.join(SMOKE_PLAYER_DATA_DIR, "coach.sqlite3")));

    const recommendation = await fetchOverlayRecommendation();
    step(
      "overlay recommendation",
      recommendation.ok,
      recommendation.ok ? recommendation.data.status : recommendation.error
    );

    await require("./renderer-security-smoke").runRendererSecuritySmoke({ mainWindow, overlayWindow, skillArrows, backendUrl: backendUrl(), requestBackend: requestBackendJson, step });

    const outcome = await stopBackend();
    const exit = lastExit.backend || {};
    step("backend graceful shutdown", outcome === "graceful" && exit.code === 0, `${outcome}, code=${exit.code}`);
  } catch (error) {
    step("unexpected error", false, error.stack || error.message);
  }
  const ok = steps.length > 0 && steps.every((item) => item.ok);
  if (!processes.backend && SMOKE_PLAYER_DATA_DIR) {
    fs.rmSync(SMOKE_PLAYER_DATA_DIR, { recursive: true, force: true });
  }
  const result = { ok, port: backend.port, packaged: IS_PACKAGED, steps, logs: logs.slice(-20000) };
  if (resultPath) {
    fs.mkdirSync(path.dirname(path.resolve(resultPath)), { recursive: true });
    fs.writeFileSync(resultPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  }
  dotaWatcher.stop();
  overlay.dispose();
  skillArrows.dispose();
  app.exit(ok ? 0 : 1);
}

// Hero portraits and item icons (dota-assets.js); must be declared before "ready".
protocol.registerSchemesAsPrivileged([
  { scheme: DOTA_ASSET_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } }
]);

function registerDotaAssets() {
  protocol.handle(
    DOTA_ASSET_SCHEME,
    createAssetHandler({
      root: path.join(USER_DATA_DIR, "dota-assets"),
      fetchImpl: (url) => electronNet.fetch(url),
      log: (message) => appendLog("assets", message)
    })
  );
}

// safeStorage works once the app is ready: open the sealed settings now.
function unlockSettingsSecrets() {
  const state = settings.unlockSecrets();
  appendLog(
    "settings",
    state.sealing ? `Secrets sealed with the OS${state.locked ? `; ${state.locked} could not be opened (default used)` : ""}.` : "Secrets: OS sealing unavailable, kept as before.",
    { force: true }
  );
}

function bootstrap() {
  if (process.platform === "win32") {
    app.setAppUserModelId(APP_ID);
  }
  openLauncherLog();
  registerIpc();

  if (IS_SMOKE_TEST) {
    app.whenReady().then(() => {
      unlockSettingsSecrets();
      registerDotaAssets();
      return runSmokeTest(SMOKE_TEST_RESULT);
    });
    return;
  }

  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return;
  }
  app.on("second-instance", showMainWindow);

  app.whenReady().then(() => {
    settings.onError(error => appendLog("settings", `Persistence ${error.operation} failed (${error.code}).`, {force:true}));
    unlockSettingsSecrets();
    registerDotaAssets();
    appendLog("launcher", `${APP_NAME} ${app.getVersion()} started (${IS_PACKAGED ? "packaged" : "dev"}).`, {
      force: true
    });
    // Counted on this computer even while the statistics are off; sent only if they are on.
    if (settings.get("sessionOpen")) {
      countApp("unclean_exits");
    }
    settings.set("sessionOpen", true);
    countApp("launches");
    if (!settings.get("installedAt")) {
      settings.set("installedAt", Date.parse(settings.get("gsiSeenAt")) || Date.now());
    }
    migrateAutostartPath();
    if (process.platform === "linux") {
      setUpLinuxDesktop();
    }
    autostartEnabled = isAutostartEnabled();
    createTray();
    // After an update the app comes back the way it was: hidden in the tray
    // when the update installed by itself or the window was closed. If the
    // install did not happen (same version), start normally.
    const updatedFrom = settings.get("updatedFrom");
    const justUpdated = Boolean(updatedFrom) && updatedFrom !== app.getVersion();
    const startHidden = START_HIDDEN || (justUpdated && Boolean(settings.get("startHiddenOnce")));
    if (updatedFrom || settings.get("startHiddenOnce")) {
      settings.set("updatedFrom", "");
      settings.set("startHiddenOnce", false);
    }
    if (!startHidden) {
      createSplash();
      createMainWindow({ show: false });
    }
    if (justUpdated) {
      settings.set("whatsNewPending", app.getVersion());
      settings.set("whatsNewFrom", updatedFrom);
      appendLog("update", `Updated from ${updatedFrom} to ${app.getVersion()}.`, { force: true });
      showTrayBalloon(t("updated", app.getVersion()));
    }
    overlay.registerGlobalShortcuts();
    if (overlay.isEnabled()) {
      overlay.open();
    }
    dotaWatcher.start();
    refreshPresence();
    startGsiPolling();
    for (const eventName of ["display-added", "display-removed", "display-metrics-changed"]) {
      screen.on(eventName, () => {
        overlay.refreshPlacement();
        overlay.enforceAlwaysOnTop();
      });
    }
    startBackend();
    updater.start();
    startOutbox();
    startDiscordWeekly();
    startAdviceStats();
    app.on("activate", showMainWindow);
  });

  // Keep running in the tray when every window is closed.
  app.on("window-all-closed", () => {});

  // A window's page that crashed or was killed (not a normal close) counts for the statistics.
  app.on("render-process-gone", (_event, _contents, details) => {
    if (details && details.reason !== "clean-exit") {
      countApp("renderer_crashes");
      appendLog("launcher", `A window's page stopped: ${details.reason}.`, { force: true });
    }
  });

  // Stop the backend gracefully before Electron exits.
  app.on("before-quit", (event) => {
    isQuitting = true;
    settings.set("sessionOpen", false);
    if (shutdownComplete) {
      return;
    }
    event.preventDefault();
    if (!shutdownPromise) {
      shutdownPromise = shutdownChildren()
        .catch((error) => appendLog("launcher", `Shutdown error: ${error.message}`, { force: true }))
        .finally(() => {
          shutdownComplete = true;
          if (tray && !tray.isDestroyed()) {
            tray.destroy();
          }
          app.quit();
        });
    }
  });

  // SIGHUP: the terminal that started the app (Linux) was closed.
  for (const signal of process.platform === "linux" ? ["SIGINT", "SIGTERM", "SIGHUP"] : ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => quitApp(`signal ${signal}`));
  }
}

bootstrap();
