const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {createSettingsStore} = require("../settings");
const {createSecretCodec, PREFIX} = require("../secret-codec");

// Stands in for Electron safeStorage: a per-user XOR, ready only after `ready`.
function fakeSafeStorage(user = "user-1") {
  const pad = Buffer.from(user);
  const flip = buffer => Buffer.from(buffer.map((byte, index) => byte ^ pad[index % pad.length]));
  const storage = {
    ready: false,
    isEncryptionAvailable: () => storage.ready,
    encryptString: text => Buffer.concat([pad, flip(Buffer.from(text, "utf8"))]),
    decryptString: buffer => {
      if (!buffer.subarray(0, pad.length).equals(pad)) {
        throw new Error("another user");
      }
      return flip(buffer.subarray(pad.length)).toString("utf8");
    }
  };
  return storage;
}

const DEFAULTS = {
  language: "uk",
  discordWebhook: "",
  shares: {},
  friendsProfile: {enabled:false, id:"", token:"", showMmr:true}
};
const SECRET = ["shares", "friendsProfile", "discordWebhook"];
const WEBHOOK = "https://discord.com/api/webhooks/1/abcdefghijklmnop";
const SHARES = {"8843471434": {id:"r1", token:"d".repeat(32), url:"https://x/r/r1", expiresAt:Date.now() + 1e9}};
const PROFILE = {enabled:true, id:"4k7p9qx2", token:"t".repeat(32), showMmr:false};

function workspace(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-secrets-"));
  t.after(() => fs.rmSync(directory, {recursive:true, force:true}));
  return path.join(directory, "settings.json");
}

function open(file, storage) {
  return createSettingsStore(file, DEFAULTS, {secretKeys:SECRET, codec:createSecretCodec(storage)});
}

test("plain secrets of an older version are sealed once the app is ready", t => {
  const file = workspace(t);
  fs.writeFileSync(file, JSON.stringify({language:"en", discordWebhook:WEBHOOK, shares:SHARES, friendsProfile:PROFILE}));
  const storage = fakeSafeStorage();
  const store = open(file, storage);
  // Before ready: plain values work as before and nothing is rewritten.
  assert.equal(store.get("discordWebhook"), WEBHOOK);
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, WEBHOOK);
  storage.ready = true;
  assert.deepEqual(store.unlockSecrets(), {sealing:true, locked:0});
  const disk = fs.readFileSync(file, "utf8");
  for (const value of [WEBHOOK, "d".repeat(32), "t".repeat(32)]) {
    assert.ok(!disk.includes(value), "a secret is still readable on disk");
  }
  const raw = JSON.parse(disk);
  assert.equal(raw.language, "en");
  for (const key of SECRET) {
    assert.ok(raw[key].startsWith(PREFIX), key);
  }
  assert.equal(store.get("discordWebhook"), WEBHOOK);
  assert.deepEqual(store.get("shares"), SHARES);
  assert.deepEqual(store.get("friendsProfile"), PROFILE);
});

test("sealed secrets wait for ready, then open; later writes stay sealed", t => {
  const file = workspace(t);
  const first = fakeSafeStorage();
  first.ready = true;
  const store = open(file, first);
  store.unlockSecrets();
  store.set("discordWebhook", WEBHOOK);
  store.update("friendsProfile", {enabled:true, token:"t".repeat(32)});

  const storage = fakeSafeStorage();
  const again = open(file, storage);
  // Not ready: the defaults, and a write of another key keeps the seals on disk.
  assert.equal(again.get("discordWebhook"), "");
  again.set("language", "en");
  assert.ok(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook.startsWith(PREFIX));
  storage.ready = true;
  again.unlockSecrets();
  assert.equal(again.get("discordWebhook"), WEBHOOK);
  assert.equal(again.get("friendsProfile").token, "t".repeat(32));
  assert.equal(again.get("friendsProfile").showMmr, true, "defaults still fill missing fields");
  assert.equal(again.get("language"), "en");
  assert.ok(!fs.readFileSync(file, "utf8").includes(WEBHOOK));
});

test("a seal another user made is kept on disk and reads as the default", t => {
  const file = workspace(t);
  const owner = fakeSafeStorage("user-1");
  owner.ready = true;
  const store = open(file, owner);
  store.unlockSecrets();
  store.set("discordWebhook", WEBHOOK);
  const sealed = JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook;

  const other = fakeSafeStorage("user-2");
  other.ready = true;
  const foreign = open(file, other);
  // All three were sealed by user-1 (the defaults too).
  assert.deepEqual(foreign.unlockSecrets(), {sealing:true, locked:3});
  assert.equal(foreign.get("discordWebhook"), "");
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, sealed);
  assert.equal(foreign.health().secrets.locked, 3);
  // Entering a new webhook replaces the locked one.
  foreign.set("discordWebhook", "https://discord.com/api/webhooks/2/zzzzzzzzzzzz");
  assert.equal(foreign.health().secrets.locked, 2);
  assert.notEqual(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, sealed);
});

test("without OS sealing the settings stay as before", t => {
  const file = workspace(t);
  const store = open(file, fakeSafeStorage());
  assert.deepEqual(store.unlockSecrets(), {sealing:false, locked:0});
  store.set("discordWebhook", WEBHOOK);
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, WEBHOOK);
  const plainStore = createSettingsStore(workspace(t), DEFAULTS);
  assert.deepEqual(plainStore.unlockSecrets(), {sealing:false, locked:0});
});

test("a seal that does not open back is refused and the write fails safely", t => {
  const broken = {isEncryptionAvailable:() => true, encryptString:text => Buffer.from(text), decryptString:() => "\"other\""};
  const codec = createSecretCodec(broken);
  assert.equal(codec.seal(WEBHOOK), null);
  const working = createSecretCodec(fakeSafeStorage());
  assert.equal(working.open(`${PREFIX}%%%`), undefined);
  assert.equal(working.open("plain"), undefined);
  const file = workspace(t);
  fs.writeFileSync(file, JSON.stringify({discordWebhook:WEBHOOK}));
  const store = createSettingsStore(file, DEFAULTS, {secretKeys:SECRET, codec});
  store.unlockSecrets();
  // Never written in plain text once sealing is on, and never lost from RAM.
  assert.equal(store.health().lastError.code, "seal_failed");
  assert.equal(store.get("discordWebhook"), WEBHOOK);
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, WEBHOOK);
});

test("Linux basic_text storage (no keyring) does not count as OS sealing", t => {
  const storage = fakeSafeStorage();
  storage.ready = true;
  storage.getSelectedStorageBackend = () => "basic_text";
  assert.equal(createSecretCodec(storage).available(), false);
  for (const backend of ["gnome_libsecret", "kwallet5", "kwallet6", "unknown"]) {
    storage.getSelectedStorageBackend = () => backend;
    assert.equal(createSecretCodec(storage).available(), true, backend);
  }
  // Windows/macOS have no such method: the plain readiness check decides.
  delete storage.getSelectedStorageBackend;
  assert.equal(createSecretCodec(storage).available(), true);
  storage.getSelectedStorageBackend = () => { throw new Error("boom"); };
  assert.equal(createSecretCodec(storage).available(), false);

  // The settings store then keeps secrets as before instead of sealing them.
  storage.getSelectedStorageBackend = () => "basic_text";
  const file = workspace(t);
  const store = open(file, storage);
  assert.deepEqual(store.unlockSecrets(), {sealing:false, locked:0});
  store.set("discordWebhook", WEBHOOK);
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).discordWebhook, WEBHOOK);
});
