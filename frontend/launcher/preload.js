const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("launcherApi", {
  getStatus: () => ipcRenderer.invoke("launcher:get-status"),
  getLogs: () => ipcRenderer.invoke("launcher:get-logs"),
  clearLogs: () => ipcRenderer.invoke("launcher:clear-logs"),
  copyLogs: () => ipcRenderer.invoke("launcher:copy-logs"),
  copyLaunchOption: () => ipcRenderer.invoke("launcher:copy-launch-option"),
  copyReplayTick: (tick) => ipcRenderer.invoke("launcher:copy-replay-tick", tick),
  startBackend: () => ipcRenderer.invoke("launcher:start-backend"),
  stopBackend: () => ipcRenderer.invoke("launcher:stop-backend"),
  restartBackend: () => ipcRenderer.invoke("launcher:restart-backend"),
  startOverlay: () => ipcRenderer.invoke("launcher:start-overlay"),
  stopOverlay: () => ipcRenderer.invoke("launcher:stop-overlay"),
  setAutostart: (enabled) => ipcRenderer.invoke("launcher:set-autostart", enabled),
  runDemo: (presetName) => ipcRenderer.invoke("launcher:run-demo", presetName),
  runDeepReview: (presetName) => ipcRenderer.invoke("launcher:run-deep-review", presetName),
  stopDemo: () => ipcRenderer.invoke("launcher:stop-demo"),
  setLogMode: (mode) => ipcRenderer.invoke("launcher:set-log-mode", mode),
  checkLiveGsi: () => ipcRenderer.invoke("launcher:check-live-gsi"),
  operationsHealth: () => ipcRenderer.invoke("launcher:operations-health"),
  startLiveRecording: () => ipcRenderer.invoke("launcher:start-live-recording"),
  stopLiveRecording: () => ipcRenderer.invoke("launcher:stop-live-recording"),
  checkGsi: (customPath) => ipcRenderer.invoke("launcher:check-gsi", customPath),
  installGsi: (customPath) => ipcRenderer.invoke("launcher:install-gsi", customPath),
  chooseGsiFolder: () => ipcRenderer.invoke("launcher:choose-gsi-folder"),
  chooseDotaFolder: () => ipcRenderer.invoke("launcher:choose-dota-folder"),
  launchDota: () => ipcRenderer.invoke("launcher:launch-dota"),
  setOverlayPosition: (preset) => ipcRenderer.invoke("launcher:set-overlay-position", preset),
  setLanguage: (value) => ipcRenderer.invoke("launcher:set-language", value),
  setUiScale: (value) => ipcRenderer.invoke("launcher:set-ui-scale", Number(value)),
  // The new size after Ctrl + plus / minus / 0 or Ctrl + the wheel (a toast names it).
  onUiScale: (callback) => {
    ipcRenderer.on("launcher:ui-scale", (_event, value) => callback(value));
  },
  setAdviceFrequency: (value) => ipcRenderer.invoke("launcher:set-advice-frequency", value),
  setDiscordPresence: (enabled) => ipcRenderer.invoke("launcher:set-discord-presence", Boolean(enabled)),
  setShareStats: (enabled) => ipcRenderer.invoke("launcher:set-share-stats", Boolean(enabled)),
  statsPreview: () => ipcRenderer.invoke("launcher:stats-preview"),
  matchRecords: (request) => ipcRenderer.invoke("launcher:match-records", request),
  friends: (request) => ipcRenderer.invoke("launcher:friends", request),
  deleteServerData: () => ipcRenderer.invoke("launcher:delete-server-data"),
  discordWeekly: (action, url) => ipcRenderer.invoke("launcher:discord-weekly", { action: String(action), url: typeof url === "string" ? url : "" }),
  setAdvicePreferences: (patch) => ipcRenderer.invoke("launcher:set-advice-preferences", patch),
  setOverlaySize: (name) => ipcRenderer.invoke("launcher:set-overlay-size", name),
  setOverlayVoice: (mode, volume) => ipcRenderer.invoke("launcher:set-overlay-voice", mode, volume),
  setOverlayDisplay: (patch) => ipcRenderer.invoke("launcher:set-overlay-display", patch),
  // "on" | "off" | "calibrate" | "reset" (skill-arrow-window.js).
  skillArrows: (action) => ipcRenderer.invoke("launcher:skill-arrows", action),
  setOverlayLocked: (locked) => ipcRenderer.invoke("launcher:set-overlay-locked", locked),
  dismissFullscreenWarning: () => ipcRenderer.invoke("launcher:dismiss-fullscreen-warning"),
  checkForUpdates: () => ipcRenderer.invoke("launcher:check-updates"),
  installUpdate: () => ipcRenderer.invoke("launcher:install-update"),
  openUpdatePage: () => ipcRenderer.invoke("launcher:open-update-page"),
  // Linked player, match table, post-match review, career (see PLAYER_OPS in main.js).
  player: (op, args) => ipcRenderer.invoke("launcher:player", op, args),
  onPlayerEvent: (callback) => {
    ipcRenderer.on("launcher:player-event", (_event, payload) => callback(payload));
  },
  openLogs: () => ipcRenderer.invoke("launcher:open-logs"),
  exportPdf: (kind, id) => ipcRenderer.invoke("launcher:export-pdf", kind, id),
  // History backup: save to a file / merge a file back (dialogs in the main process).
  // Share a review by link (the delete token never leaves the main process).
  shareStatus: (matchId) => ipcRenderer.invoke("launcher:share-status", matchId),
  shareCreate: (matchId, withCoach) => ipcRenderer.invoke("launcher:share-create", matchId, withCoach),
  shareDelete: (matchId) => ipcRenderer.invoke("launcher:share-delete", matchId),
  shareCopy: (matchId) => ipcRenderer.invoke("launcher:share-copy", matchId),
  shareOpen: (matchId) => ipcRenderer.invoke("launcher:share-open", matchId),
  exportHistory: () => ipcRenderer.invoke("launcher:backup-export"),
  importHistory: () => ipcRenderer.invoke("launcher:backup-import"),
  // The same history to another computer by a one-time code (encrypted, 15 minutes).
  sendHistoryByCode: () => ipcRenderer.invoke("launcher:transfer-send"),
  receiveHistoryByCode: (code) => ipcRenderer.invoke("launcher:transfer-receive", String(code || "")),
  dismissSetup: () => ipcRenderer.invoke("launcher:dismiss-setup"),
  dismissWhatsNew: () => ipcRenderer.invoke("launcher:dismiss-whats-new"),
  invite: (action) => ipcRenderer.invoke("launcher:invite", action),
  statsAnswer: (answer) => ipcRenderer.invoke("launcher:stats-answer", answer === "yes" ? "yes" : "no"),
  tourDone: () => ipcRenderer.invoke("launcher:tour-done"),
  session: (action) => ipcRenderer.invoke("launcher:session", action),
  saveProblemReport: () => ipcRenderer.invoke("launcher:save-problem-report"),
  previewProblemReport: () => ipcRenderer.invoke("launcher:preview-problem-report"),
  sendProblemReport: (note) => ipcRenderer.invoke("launcher:send-problem-report", note),
  openPrivacy: () => ipcRenderer.invoke("launcher:open-privacy"),
  openSpeechSettings: () => ipcRenderer.invoke("launcher:open-speech-settings"),
  openSimulationResults: () => ipcRenderer.invoke("launcher:open-simulation-results"),
  openSessionRecords: () => ipcRenderer.invoke("launcher:open-session-records"),
  openReadme: () => ipcRenderer.invoke("launcher:open-readme"),
  openAiKeyPage: (provider) => ipcRenderer.invoke("launcher:open-ai-key-page", provider),
  openMatchSite: (site, matchId) => ipcRenderer.invoke("launcher:open-match-site", site, matchId),
  onStatus: (callback) => {
    ipcRenderer.on("launcher:status", (_event, status) => callback(status));
  },
  onLogs: (callback) => {
    ipcRenderer.on("launcher:logs", (_event, logs) => callback(logs));
  }
});
