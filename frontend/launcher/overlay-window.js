const { BrowserWindow, globalShortcut, screen } = require("electron");
const path = require("node:path");

const { anchorArea, isReachable, physicalRectToDip, presetBounds, sameBounds } = require("./overlay-placement");
const { protectWindow } = require("./renderer-security");

// Always-on-top advice card. It used to be a separate Electron app
// (frontend/desktop-overlay); now it is a second window of the launcher so the
// whole coach runs as one process with one tray icon.

const WINDOW_WIDTH = 420;
// Room for a 3-line action + 2-line reason (Ukrainian text runs ~25% longer).
const WINDOW_HEIGHT = 212; // the card and, under it, the timer strip
// Windows/macOS stack "screen-saver" above fullscreen games. On Linux/X11
// Electron ignores the level and sets _NET_WM_STATE_ABOVE, which the window
// manager keeps over normal and borderless windows (not over a fullscreen one).
const ALWAYS_ON_TOP_LEVEL = "screen-saver";
const ENFORCE_ALWAYS_ON_TOP_MS = 2500;
const MUTE_MS = 5 * 60 * 1000;
// Card size presets (zoom of the whole card, window grows with it).
const OVERLAY_SCALES = { small: 0.85, normal: 1, large: 1.25 };

const OVERLAY_DEFAULTS = {
  enabled: true,
  pollIntervalMs: 1000,
  positionPreset: "right-center",
  locked: true,
  debugVisible: false,
  opacity: 1,
  autoHideMs: 8000,
  urgentAutoHideMs: 12000,
  // Spoken advice: "off" | "urgent" | "all" (overlay/voice.js).
  voice: "off",
  voiceVolume: 1,
  size: "normal",
  // The strip of the next events under the card, a card with the action only,
  // and the small map on cards (the farm target, the nearest rune spot).
  timers: true,
  compact: false,
  map: true
};
const VOICE_MODES = ["off", "urgent", "all"];

// The window exists while the overlay is enabled; whether it is on screen is
// decided separately (setVisible) from Dota focus + fresh GSI, see
// overlay-visibility.js. The always-on-top timer only runs while it is shown.
// getDotaRect() returns Dota's window in physical pixels (dota-watcher.js) or
// null; the card follows it to its monitor, see overlay-placement.js.
function createOverlayController({
  settings,
  getBackend,
  getLocale = () => "en",
  getDotaRect = () => null,
  onChange = () => {},
  log = () => {}
}) {
  let overlayWindow = null;
  let alwaysOnTopTimer = null;
  let moveSaveTimer = null;
  let windowShortcutsRegistered = false;
  let wantVisible = false;
  let ignoreMovesUntil = 0;
  let lastDotaDisplayId = null;

  const windowShortcuts = [
    ["CommandOrControl+Alt+M", muteAdvice],
    ["CommandOrControl+Alt+R", repeatAdvice],
    ["CommandOrControl+Alt+L", toggleLocked],
    ["CommandOrControl+Alt+D", toggleDebugLine],
    ["CommandOrControl+Alt+1", () => setPosition("left-center")],
    ["CommandOrControl+Alt+2", () => setPosition("right-center")],
    ["CommandOrControl+Alt+3", () => setPosition("bottom-center")]
  ];

  function config() {
    const merged = { ...OVERLAY_DEFAULTS, ...(settings.get("overlay") || {}) };
    // 0.92 was the old default window opacity; the card itself is now 85%
    // opaque, so dimming the whole window on top of that hurts readability.
    if (merged.opacity === 0.92) {
      merged.opacity = 1;
    }
    return merged;
  }

  function updateConfig(patch) {
    settings.update("overlay", patch);
  }

  function isEnabled() {
    return Boolean(config().enabled);
  }

  function isOpen() {
    return Boolean(overlayWindow && !overlayWindow.isDestroyed());
  }

  function isVisible() {
    return isOpen() && overlayWindow.isVisible();
  }

  function isUnlocked() {
    return !config().locked;
  }

  function setVisible(visible) {
    wantVisible = Boolean(visible);
    if (!isOpen()) {
      return;
    }
    if (wantVisible && !overlayWindow.isVisible()) {
      overlayWindow.showInactive();
      enforceAlwaysOnTop();
    } else if (!wantVisible && overlayWindow.isVisible()) {
      overlayWindow.hide();
    }
    updateAlwaysOnTopTimer();
  }

  function setEnabled(enabled) {
    updateConfig({ enabled: Boolean(enabled) });
    if (enabled) {
      open();
    } else {
      close();
    }
    onChange();
  }

  function toggle() {
    setEnabled(!isEnabled());
  }

  function open() {
    if (isOpen()) {
      enforceAlwaysOnTop();
      return overlayWindow;
    }
    const current = config();
    const initialSize = windowSize();
    overlayWindow = new BrowserWindow({
      width: initialSize.width,
      height: initialSize.height,
      title: "Wardly Overlay",
      frame: false,
      transparent: true,
      backgroundColor: "#00000000",
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      maximizable: false,
      minimizable: false,
      fullscreenable: false,
      focusable: false,
      hasShadow: false,
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "overlay-preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true
      }
    });

    protectWindow(overlayWindow);
    overlayWindow.setOpacity(Number(current.opacity) || OVERLAY_DEFAULTS.opacity);
    enforceAlwaysOnTop();
    moveToPreset(current.positionPreset || OVERLAY_DEFAULTS.positionPreset, false);
    applyLockedMode();

    overlayWindow.loadFile(path.join(__dirname, "overlay", "index.html"));
    overlayWindow.webContents.on("did-finish-load", applyZoom);
    overlayWindow.once("ready-to-show", () => {
      if (!isOpen() || !wantVisible) {
        return;
      }
      overlayWindow.showInactive();
      enforceAlwaysOnTop();
      updateAlwaysOnTopTimer();
    });

    overlayWindow.on("show", enforceAlwaysOnTop);
    overlayWindow.on("closed", () => {
      overlayWindow = null;
      updateAlwaysOnTopTimer();
      unregisterWindowShortcuts();
    });
    overlayWindow.on("move", () => {
      // Our own setBounds (presets, following Dota) is not a hand move.
      if (!isOpen() || config().locked || Date.now() < ignoreMovesUntil) {
        return;
      }
      clearTimeout(moveSaveTimer);
      moveSaveTimer = setTimeout(() => {
        if (!isOpen()) {
          return;
        }
        const bounds = overlayWindow.getBounds();
        updateConfig({ positionPreset: "custom", customBounds: { x: bounds.x, y: bounds.y } });
      }, 250);
    });

    registerWindowShortcuts();
    updateAlwaysOnTopTimer();
    return overlayWindow;
  }

  function close() {
    unregisterWindowShortcuts();
    clearTimeout(moveSaveTimer);
    if (isOpen()) {
      overlayWindow.destroy();
    }
    overlayWindow = null;
    updateAlwaysOnTopTimer();
  }

  function enforceAlwaysOnTop() {
    if (!isVisible()) {
      return;
    }
    overlayWindow.setAlwaysOnTop(true, ALWAYS_ON_TOP_LEVEL);
    overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    overlayWindow.moveTop();
  }

  function updateAlwaysOnTopTimer() {
    clearInterval(alwaysOnTopTimer);
    alwaysOnTopTimer = null;
    if (!isVisible()) {
      return;
    }
    alwaysOnTopTimer = setInterval(enforceAlwaysOnTop, ENFORCE_ALWAYS_ON_TOP_MS);
    if (typeof alwaysOnTopTimer.unref === "function") {
      alwaysOnTopTimer.unref();
    }
  }

  function applyLockedMode() {
    if (!isOpen()) {
      return;
    }
    const locked = Boolean(config().locked);
    try {
      overlayWindow.setIgnoreMouseEvents(locked, { forward: true });
    } catch {
      overlayWindow.setIgnoreMouseEvents(locked);
    }
    send("overlay-config-updated", publicConfig());
  }

  // Presets keep the card off the Dota HUD (minimap and hero panel at the
  // bottom, top bar at the top) and are computed inside Dota's window.
  function moveToPreset(preset, persist = true) {
    if (!isOpen()) {
      return;
    }
    preset = normalizePreset(preset);
    const current = config();
    const size = windowSize();
    let bounds = null;
    if (preset === "custom" && current.customBounds) {
      const custom = {
        x: Number(current.customBounds.x) || 0,
        y: Number(current.customBounds.y) || 0,
        ...size
      };
      if (isReachable(custom, screen.getAllDisplays().map((display) => display.workArea))) {
        bounds = custom;
      } else {
        log("The hand-placed overlay position is off-screen (monitor removed?); using the right preset.");
      }
    }
    if (!bounds) {
      bounds = presetBounds(preset === "custom" ? "right-center" : preset, targetArea(size), size);
    }
    applyBounds(bounds);
    if (persist) {
      updateConfig({
        positionPreset: preset,
        customBounds: preset === "custom" ? current.customBounds : undefined
      });
    }
  }

  function applyBounds(bounds) {
    if (sameBounds(overlayWindow.getBounds(), bounds)) {
      return;
    }
    ignoreMovesUntil = Date.now() + 500;
    overlayWindow.setBounds(bounds);
  }

  function targetArea(size) {
    const displays = screen.getAllDisplays();
    const physical = getDotaRect();
    let dotaRect = null;
    let display = null;
    if (physical) {
      dotaRect = toDip(physical);
      display = screen.getDisplayMatching(dotaRect);
      lastDotaDisplayId = display ? display.id : null;
    }
    // Dota minimized or closed: stay on the monitor it was last seen on.
    const lastDisplay = displays.find((item) => item.id === lastDotaDisplayId);
    const fallbackArea = (lastDisplay || screen.getPrimaryDisplay()).workArea;
    return anchorArea({ dotaRect, display, fallbackArea, size });
  }

  // The watcher reports physical pixels; Electron places windows in DIP.
  function toDip(rect) {
    if (process.platform === "win32" && typeof screen.screenToDipRect === "function") {
      try {
        return screen.screenToDipRect(null, rect);
      } catch {
        // Fall through to the raw rect.
      }
    }
    if (process.platform === "linux") {
      return physicalRectToDip(rect, screen.getAllDisplays());
    }
    return rect;
  }

  // Called when Dota's window moves to another monitor or displays change.
  // Not while the user is dragging the card (unlocked).
  function refreshPlacement() {
    if (!isOpen() || !config().locked) {
      return;
    }
    moveToPreset(config().positionPreset || OVERLAY_DEFAULTS.positionPreset, false);
  }

  function normalizePreset(preset) {
    // "top-left" was an older preset that sat on Dota's top-left menu.
    return preset === "top-left" ? "left-center" : preset;
  }

  function setPosition(preset) {
    const next = normalizePreset(preset);
    if (!["left-center", "right-center", "bottom-center"].includes(next)) {
      return;
    }
    if (isOpen()) {
      moveToPreset(next);
    } else {
      updateConfig({ positionPreset: next, customBounds: undefined });
    }
    onChange();
  }

  function setVoice(mode, volume) {
    const patch = {};
    if (VOICE_MODES.includes(mode)) {
      patch.voice = mode;
    }
    if (Number.isFinite(Number(volume)) && volume !== undefined && volume !== null) {
      patch.voiceVolume = Math.min(1, Math.max(0, Number(volume)));
    }
    updateConfig(patch);
    send("overlay-config-updated", publicConfig());
    onChange();
  }

  // What the card shows: the timer strip, the compact card (the action only)
  // and the small map.
  function setDisplay(patch) {
    const next = {};
    for (const key of ["timers", "compact", "map"]) {
      if (typeof patch?.[key] === "boolean") {
        next[key] = patch[key];
      }
    }
    updateConfig(next);
    send("overlay-config-updated", publicConfig());
    onChange();
  }

  function display() {
    const current = config();
    return { timers: current.timers !== false, compact: current.compact === true, map: current.map !== false };
  }

  function voice() {
    const current = config();
    return {
      mode: VOICE_MODES.includes(current.voice) ? current.voice : "off",
      volume: Number.isFinite(Number(current.voiceVolume)) ? Number(current.voiceVolume) : 1
    };
  }

  function sizeName() {
    const value = config().size;
    return Object.hasOwn(OVERLAY_SCALES, value) ? value : "normal";
  }

  function windowSize() {
    const scale = OVERLAY_SCALES[sizeName()];
    return { width: Math.round(WINDOW_WIDTH * scale), height: Math.round(WINDOW_HEIGHT * scale) };
  }

  function applyZoom() {
    if (isOpen()) {
      overlayWindow.webContents.setZoomFactor(OVERLAY_SCALES[sizeName()]);
    }
  }

  function setSize(name) {
    if (!Object.hasOwn(OVERLAY_SCALES, name)) {
      return;
    }
    updateConfig({ size: name });
    if (isOpen()) {
      applyZoom();
      moveToPreset(config().positionPreset || OVERLAY_DEFAULTS.positionPreset, false);
    }
    onChange();
  }

  function position() {
    return normalizePreset(config().positionPreset || OVERLAY_DEFAULTS.positionPreset);
  }

  function setLocked(locked) {
    if (Boolean(locked) === Boolean(config().locked)) {
      return;
    }
    toggleLocked();
  }

  function toggleLocked() {
    updateConfig({ locked: !config().locked });
    applyLockedMode();
    log(`Overlay ${config().locked ? "locked (click-through)" : "unlocked (draggable, shown until locked again)"}.`);
    onChange();
  }

  function muteAdvice() {
    send("overlay-muted", Date.now() + MUTE_MS);
  }

  // Show (and speak, if the voice is on) the last advice again.
  function repeatAdvice() {
    send("overlay-repeat", Date.now());
  }

  function toggleDebugLine() {
    updateConfig({ debugVisible: !config().debugVisible });
    send("overlay-toggle-debug", Boolean(config().debugVisible));
    send("overlay-config-updated", publicConfig());
  }

  function send(channel, payload) {
    if (isOpen()) {
      overlayWindow.webContents.send(channel, payload);
    }
  }

  function registerShortcut(accelerator, handler) {
    try {
      if (!globalShortcut.register(accelerator, handler)) {
        log(`Shortcut ${accelerator} is used by another application.`);
      }
    } catch (error) {
      log(`Shortcut ${accelerator} could not be registered: ${error.message}`);
    }
  }

  function registerWindowShortcuts() {
    if (windowShortcutsRegistered) {
      return;
    }
    windowShortcutsRegistered = true;
    for (const [accelerator, handler] of windowShortcuts) {
      registerShortcut(accelerator, handler);
    }
  }

  function unregisterWindowShortcuts() {
    if (!windowShortcutsRegistered) {
      return;
    }
    windowShortcutsRegistered = false;
    for (const [accelerator] of windowShortcuts) {
      globalShortcut.unregister(accelerator);
    }
  }

  // Ctrl+Alt+O stays registered while the app runs so the overlay can be
  // turned back on from inside the game.
  function registerGlobalShortcuts() {
    registerShortcut("CommandOrControl+Alt+O", toggle);
  }

  function publicConfig() {
    const current = config();
    const backend = getBackend();
    return {
      locale: getLocale(),
      backendUrl: backend.url,
      backendPort: backend.port,
      backendStatus: backend.status,
      pollIntervalMs: current.pollIntervalMs,
      positionPreset: current.positionPreset,
      locked: current.locked,
      debugVisible: current.debugVisible,
      opacity: current.opacity,
      autoHideMs: current.autoHideMs,
      urgentAutoHideMs: current.urgentAutoHideMs,
      voice: voice().mode,
      voiceVolume: voice().volume,
      ...display()
    };
  }

  function notifyBackendChanged() {
    send("overlay-config-updated", publicConfig());
  }

  function dispose() {
    close();
    globalShortcut.unregisterAll();
  }

  return {
    open,
    close,
    toggle,
    setEnabled,
    isEnabled,
    isOpen,
    isVisible,
    isUnlocked,
    setVisible,
    setPosition,
    position,
    setVoice,
    voice,
    setDisplay,
    display,
    setSize,
    size: sizeName,
    refreshPlacement,
    setLocked,
    window: () => (isOpen() ? overlayWindow : null),
    enforceAlwaysOnTop,
    publicConfig,
    notifyBackendChanged,
    registerGlobalShortcuts,
    dispose
  };
}

module.exports = { createOverlayController, OVERLAY_DEFAULTS };
