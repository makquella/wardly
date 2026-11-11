const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("overlayApi", {
  getConfig: () => ipcRenderer.invoke("overlay:get-config"),
  // The main process owns the backend port, so the renderer never builds URLs itself.
  fetchRecommendation: () => ipcRenderer.invoke("overlay:fetch-recommendation"),
  // What the system voice did (voice.js onEvent): a line in the launcher log.
  voiceEvent: (event) => ipcRenderer.invoke("overlay:voice-event", event),
  onConfigUpdated: (callback) => {
    ipcRenderer.on("overlay-config-updated", (_event, config) => callback(config));
  },
  onMuted: (callback) => {
    ipcRenderer.on("overlay-muted", (_event, mutedUntil) => callback(mutedUntil));
  },
  onRepeat: (callback) => {
    ipcRenderer.on("overlay-repeat", () => callback());
  },
  onToggleDebug: (callback) => {
    ipcRenderer.on("overlay-toggle-debug", (_event, visible) => callback(visible));
  }
});
