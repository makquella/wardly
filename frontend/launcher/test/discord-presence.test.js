const assert = require("node:assert/strict");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { CLIENT_ID, OP, buildActivity, createDiscordPresence, decode, encode, ipcPath, ipcPaths, trackMatchStart } = require("../discord-presence");

test("frames: int32 op, int32 length, JSON; partial frames wait for the rest", () => {
  const one = encode(OP.FRAME, { cmd: "SET_ACTIVITY" });
  assert.equal(one.readInt32LE(0), OP.FRAME);
  assert.equal(one.readInt32LE(4), one.length - 8);
  const two = Buffer.concat([one, encode(OP.PING, { n: 1 })]);
  const { frames, rest } = decode(Buffer.concat([two, one.subarray(0, 5)]));
  assert.deepEqual(frames.map((f) => f.op), [OP.FRAME, OP.PING]);
  assert.equal(rest.length, 5);
});

test("pipe paths per platform", () => {
  assert.equal(ipcPath(0, { platform: "win32", env: {} }), "\\\\?\\pipe\\discord-ipc-0");
  assert.equal(ipcPath(3, { platform: "linux", env: { XDG_RUNTIME_DIR: "/run/user/1000/" } }), "/run/user/1000/discord-ipc-3");
  assert.equal(ipcPath(0, { platform: "darwin", env: {} }), "/tmp/discord-ipc-0");
});

test("the activity: a match with the hero and its start, the menu, nothing without Dota", () => {
  const match = buildActivity({ dotaRunning: true, inMatch: true, hero: "Juggernaut", startedAt: 1_790_000_000_500, lang: "uk" });
  assert.equal(match.details, "Матч на Juggernaut");
  assert.equal(match.state, "З тренером Wardly");
  assert.deepEqual(match.timestamps, { start: 1_790_000_000_500 }, "milliseconds, as the RPC server reads them");
  assert.equal(match.assets.large_image, "wardly");
  assert.ok(match.buttons[0].label.length <= 32);
  assert.equal(match.buttons[0].url, "https://luhovyimvp.dev/?ref=discord", "friends who click it are counted");
  const menu = buildActivity({ dotaRunning: true, inMatch: false, hero: null, startedAt: null, lang: "en" });
  assert.equal(menu.details, "In the Dota 2 menu");
  assert.equal(menu.buttons[0].url, "https://luhovyimvp.dev/en/?ref=discord");
  assert.ok(!("timestamps" in menu));
  assert.equal(buildActivity({ dotaRunning: false, inMatch: false, hero: null, startedAt: null, lang: "en" }), null);
});

test("the timer starts at the horn, not at pre-game, and stays put", () => {
  let state = trackMatchStart(null, { inMatch: true, hero: "Lina", clock: -75, now: 1_000_000 });
  assert.equal(state.startedAt, null, "strategy time / pre-game: no timer yet");
  state = trackMatchStart(state, { inMatch: true, hero: "Lina", clock: 3, now: 1_080_000 });
  assert.equal(state.startedAt, 1_077_000);
  state = trackMatchStart(state, { inMatch: true, hero: "Lina", clock: 64, now: 1_141_500 });
  assert.equal(state.startedAt, 1_077_000, "later polls do not move it");
  state = trackMatchStart(state, { inMatch: false, hero: null, clock: null, now: 2_000_000 });
  assert.deepEqual(state, { hero: null, startedAt: null });
  state = trackMatchStart(state, { inMatch: true, hero: "Axe", clock: 600, now: 3_000_000 });
  assert.equal(state.startedAt, 2_400_000, "joined mid-game: counted back from the clock");
});

test("the client shakes hands, sets the activity once per change and clears it", async (t) => {
  if (process.platform === "win32") {
    t.skip("unix socket fake");
    return;
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-discord-"));
  const received = [];
  let buffer = Buffer.alloc(0);
  const server = net.createServer((socket) => {
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      const { frames, rest } = decode(buffer);
      buffer = rest;
      for (const frame of frames) {
        received.push(frame);
        if (frame.op === OP.HANDSHAKE) {
          socket.write(encode(OP.FRAME, { cmd: "DISPATCH", evt: "READY", data: {} }));
        }
      }
    });
  });
  // Only discord-ipc-1 exists: the client tries 0 first and moves on.
  await new Promise((resolve) => server.listen(path.join(dir, "discord-ipc-1"), resolve));
  const presence = createDiscordPresence({ pathFor: (i) => path.join(dir, `discord-ipc-${i}`), pid: 42 });
  const activity = buildActivity({ dotaRunning: true, inMatch: true, hero: "Lina", startedAt: Date.now(), lang: "en" });
  presence.update(activity);
  await waitFor(() => received.some((f) => f.data && f.data.cmd === "SET_ACTIVITY"));
  presence.update(activity); // the same: not sent again
  presence.update(null);
  await waitFor(() => received.filter((f) => f.data && f.data.cmd === "SET_ACTIVITY").length === 2);
  const [handshake, ...sets] = received;
  assert.deepEqual(handshake.data, { v: 1, client_id: CLIENT_ID });
  assert.equal(sets[0].data.args.pid, 42);
  assert.equal(sets[0].data.args.activity.details, "Playing Lina");
  assert.equal(sets[1].data.args.activity, null);
  presence.stop();
  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

test("the state says why nothing shows: accepted, refused with the reason, Discord not found", async (t) => {
  if (process.platform === "win32") {
    t.skip("unix socket fake");
    return;
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-discord-"));
  let refuse = true;
  const server = net.createServer((socket) => {
    socket.on("error", () => {}); // the client may hang up first
    let buffer = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      const { frames, rest } = decode(buffer);
      buffer = rest;
      for (const frame of frames) {
        if (frame.op === OP.HANDSHAKE) {
          socket.write(encode(OP.FRAME, { cmd: "DISPATCH", evt: "READY", data: {} }));
        } else if (frame.data && frame.data.cmd === "SET_ACTIVITY") {
          const answer = refuse
            ? { cmd: "SET_ACTIVITY", evt: "ERROR", nonce: frame.data.nonce, data: { code: 4000, message: "child \"activity\" fails" } }
            : { cmd: "SET_ACTIVITY", evt: null, nonce: frame.data.nonce, data: {} };
          socket.write(encode(OP.FRAME, answer));
        }
      }
    });
  });
  await new Promise((resolve) => server.listen(path.join(dir, "discord-ipc-0"), resolve));
  const states = [];
  const presence = createDiscordPresence({
    pathFor: (i) => path.join(dir, `discord-ipc-${i}`),
    onState: (state) => states.push(state)
  });
  const activity = buildActivity({ dotaRunning: true, inMatch: false, hero: null, startedAt: null, lang: "en" });
  presence.update(activity);
  await waitFor(() => presence.getState().state === "rejected");
  assert.equal(presence.getState().error, 'child "activity" fails');
  refuse = false;
  presence.update({ ...activity, details: "In a Dota 2 match" });
  await waitFor(() => presence.getState().state === "shown");
  assert.deepEqual(states.map((s) => s.state), ["connecting", "connected", "rejected", "shown"]);
  presence.stop();
  server.close();

  const nowhere = createDiscordPresence({ pathFor: (i) => path.join(dir, `missing-${i}`), retryMs: 60_000 });
  nowhere.update(activity);
  await waitFor(() => nowhere.getState().state === "no_discord");
  nowhere.stop();
  fs.rmSync(dir, { recursive: true, force: true });
});

async function waitFor(check, ms = 2000) {
  const until = Date.now() + ms;
  while (!check()) {
    if (Date.now() > until) {
      throw new Error("timed out");
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

test("linux: the plain, Flatpak and Snap Discord sockets are all looked for", () => {
  const env = { XDG_RUNTIME_DIR: "/run/user/1000/" };
  assert.deepEqual(ipcPaths(0, { platform: "linux", env }), [
    "/run/user/1000/discord-ipc-0",
    "/run/user/1000/app/com.discordapp.Discord/discord-ipc-0",
    "/run/user/1000/snap.discord/discord-ipc-0",
    "/tmp/discord-ipc-0"
  ]);
  assert.deepEqual(ipcPaths(2, { platform: "linux", env: { TMPDIR: "/var/tmp" } }), [
    "/var/tmp/discord-ipc-2",
    "/tmp/discord-ipc-2"
  ]);
  assert.deepEqual(ipcPaths(1, { platform: "win32", env: {} }), ["\\\\?\\pipe\\discord-ipc-1"]);
  assert.deepEqual(ipcPaths(0, { platform: "darwin", env: {} }), ["/tmp/discord-ipc-0"]);
});

test("linux: the client connects to a Flatpak Discord socket below XDG_RUNTIME_DIR", async (t) => {
  if (process.platform === "win32") {
    t.skip("unix socket fake");
    return;
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wardly-flatpak-"));
  const flatpak = path.join(dir, "app", "com.discordapp.Discord");
  fs.mkdirSync(flatpak, { recursive: true });
  let handshakes = 0;
  const server = net.createServer((socket) => {
    socket.on("error", () => {});
    socket.on("data", () => {
      handshakes += 1;
      socket.write(encode(OP.FRAME, { cmd: "DISPATCH", evt: "READY", data: {} }));
    });
  });
  await new Promise((resolve) => server.listen(path.join(flatpak, "discord-ipc-0"), resolve));
  const presence = createDiscordPresence({
    pathFor: (i) => ipcPaths(i, { platform: "linux", env: { XDG_RUNTIME_DIR: dir } }),
    pid: 1
  });
  presence.update(buildActivity({ dotaRunning: true, inMatch: false, hero: null, startedAt: null, lang: "en" }));
  await waitFor(() => handshakes > 0);
  presence.stop();
  server.close();
  fs.rmSync(dir, { recursive: true, force: true });
});
