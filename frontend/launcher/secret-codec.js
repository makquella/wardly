// Seals the launcher's secret settings (settings.js `secretKeys`) with Electron
// safeStorage: DPAPI for the current Windows user. A sealed value is
// "safe:v1:<base64>" of the JSON value. `open` returns undefined for a seal that
// cannot be opened (another user or computer), never throws; nothing is logged.
// On Linux Electron falls back to the "basic_text" backend (a hardcoded password)
// when no keyring (libsecret/kwallet) is running: that is not protection, so the
// codec then reports "not available" and values stay unsealed rather than claim sealing.
const PREFIX = "safe:v1:";

function createSecretCodec(safeStorage) {
  return {
    available() {
      try {
        if (!safeStorage || !safeStorage.isEncryptionAvailable()) {
          return false;
        }
        return !(typeof safeStorage.getSelectedStorageBackend === "function"
          && safeStorage.getSelectedStorageBackend() === "basic_text");
      } catch {
        return false;
      }
    },
    isSealed(value) {
      return typeof value === "string" && value.startsWith(PREFIX);
    },
    // A seal that does not open back to the same JSON is refused (null).
    seal(value) {
      try {
        const json = JSON.stringify(value);
        const sealed = PREFIX + safeStorage.encryptString(json).toString("base64");
        return JSON.stringify(this.open(sealed)) === json ? sealed : null;
      } catch {
        return null;
      }
    },
    open(value) {
      if (!this.isSealed(value)) {
        return undefined;
      }
      try {
        return JSON.parse(safeStorage.decryptString(Buffer.from(value.slice(PREFIX.length), "base64")));
      } catch {
        return undefined;
      }
    }
  };
}

module.exports = { createSecretCodec, PREFIX };
