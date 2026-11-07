// Discord Rich Presence: «Грає в Dota 2 · Juggernaut · з тренером Wardly» on the
// player's Discord profile. Discord's desktop client listens on a local IPC pipe
// (discord-ipc-0..9); the frames are an int32 op, an int32 length and JSON. No
// bot, no token, no server: only the public Application ID. Nothing is sent when
// Discord is not running, and the switch in Settings turns it off.
//
// Pure parts (frames, pipe paths, the activity) are tested in
// test/discord-presence.test.js, the client against a fake Discord pipe.

const net = require("node:net");
const crypto = require("node:crypto");

const CLIENT_ID = "1554093692971655250";
const OP = { HANDSHAKE: 0, FRAME: 1, CLOSE: 2, PING: 3, PONG: 4 };
const SITE_URL = "https://luhovyimvp.dev";
const RETRY_MS = 30_000;

function encode(op, payload) {
  const json = Buffer.from(JSON.stringify(payload), "utf8");
  const header = Buffer.alloc(8);
  header.writeInt32LE(op, 0);
  header.writeInt32LE(json.length, 4);
  return Buffer.concat([header, json]);
}

/** Whole frames out of a stream buffer: { frames: [{ op, data }], rest }. */
function decode(buffer) {
  const frames = [];
  let offset = 0;
  while (buffer.length - offset >= 8) {
    const op = buffer.readInt32LE(offset);
    const length = buffer.readInt32LE(offset + 4);
    if (length < 0 || buffer.length - offset - 8 < length) {
      break;
    }
    const body = buffer.subarray(offset + 8, offset + 8 + length).toString("utf8");
    let data = null;
    try {
      data = JSON.parse(body);
    } catch {
      data = null;
    }
    frames.push({ op, data });
    offset += 8 + length;
  }
  return { frames, rest: buffer.subarray(offset) };
}

function ipcPath(index, { platform = process.platform, env = process.env } = {}) {
  if (platform === "win32") {
    return `\\\\?\\pipe\\discord-ipc-${index}`;
  }
  const base = env.XDG_RUNTIME_DIR || env.TMPDIR || env.TMP || env.TEMP || "/tmp";
  return `${base.replace(/\/+$/, "")}/discord-ipc-${index}`;
}

// Every place a Discord client may listen on this platform, most likely first.
// Linux: the plain client uses $XDG_RUNTIME_DIR; the Flatpak and Snap builds
// keep the socket in their own folder below it (and the sandboxed build only
// shares that folder if it was granted, so each one is tried in turn).
function ipcPaths(index, { platform = process.platform, env = process.env } = {}) {
  if (platform === "win32") {
    return [ipcPath(index, { platform, env })];
  }
  const bases = [];
  const runtime = env.XDG_RUNTIME_DIR ? env.XDG_RUNTIME_DIR.replace(/\/+$/, "") : "";
  if (platform === "linux" && runtime) {
    bases.push(runtime, `${runtime}/app/com.discordapp.Discord`, `${runtime}/snap.discord`);
  }
  bases.push(env.TMPDIR || env.TMP || env.TEMP || "/tmp");
  if (platform === "linux") {
    bases.push("/tmp");
  }
  const seen = new Set();
  return bases
    .map((base) => `${base.replace(/\/+$/, "")}/discord-ipc-${index}`)
    .filter((candidate) => !seen.has(candidate) && seen.add(candidate));
}

const TEXT = {
  uk: {
    match: (hero) => (hero ? `Матч на ${hero}` : "Матч у Dota 2"),
    menu: "У меню Dota 2",
    coach: "З тренером Wardly",
    large: "Wardly — тренер з Dota 2",
    button: "Wardly — тренер з Доти"
  },
  en: {
    match: (hero) => (hero ? `Playing ${hero}` : "In a Dota 2 match"),
    menu: "In the Dota 2 menu",
    coach: "With the Wardly coach",
    large: "Wardly — a Dota 2 coach",
    button: "Wardly — Dota 2 coach"
  }
};

/**
 * The activity for the current state, or null to clear it (Dota not running).
 * @param {{ dotaRunning: boolean, inMatch: boolean, hero: string|null, startedAt: number|null, lang: string }} input
 */
function buildActivity({ dotaRunning, inMatch, hero, startedAt, lang }) {
  if (!dotaRunning && !inMatch) {
    return null;
  }
  const t = TEXT[lang === "uk" ? "uk" : "en"];
  const activity = {
    details: inMatch ? t.match(hero) : t.menu,
    state: t.coach,
    assets: { large_image: "wardly", large_text: t.large },
    // Friends who click it land on the site in the player's language; ?ref= lets
    // the site count them (see site/app.js).
    buttons: [{ label: t.button, url: `${SITE_URL}/${lang === "uk" ? "" : "en/"}?ref=discord` }],
    instance: false
  };
  if (inMatch && Number.isFinite(startedAt)) {
    // Milliseconds, as the RPC server expects (seconds read as January 1970).
    activity.timestamps = { start: Math.floor(startedAt) };
  }
  return activity;
}

/**
 * The match start for the timer, kept across polls: reset when the match or
 * hero changes, fixed at the horn (the first clock of 0 or more; before it —
 * strategy time, pre-game — there is no timer), never moved by later polls.
 */
function trackMatchStart(previous, { inMatch, hero, clock, now }) {
  let state = previous || { hero: null, startedAt: null };
  if (!inMatch || hero !== state.hero) {
    state = { hero: inMatch ? hero : null, startedAt: null };
  }
  if (inMatch && state.startedAt === null && Number.isFinite(clock) && clock >= 0) {
    state = { ...state, startedAt: now - clock * 1000 };
  }
  return state;
}

/**
 * A small client: connects when there is something to show, sends the latest
 * activity (same one twice is sent once), reconnects every RETRY_MS while
 * Discord is closed. `log(message)` gets connection changes only; `onState`
 * gets every change of `getState()` — { state: idle | connecting | no_discord |
 * connected | shown | rejected, error } — for the panel, so a player can see
 * why nothing shows (Discord closed, or Discord refused the activity).
 */
function createDiscordPresence({
  clientId = CLIENT_ID,
  connect = (path) => net.createConnection(path),
  pathFor = ipcPaths,
  log = () => {},
  onState = () => {},
  retryMs = RETRY_MS,
  pid = process.pid
} = {}) {
  let socket = null;
  let ready = false;
  let connecting = false;
  let wanted; // undefined: nothing asked yet; null: clear
  let sent = "";
  let retryTimer = null;
  let buffer = Buffer.alloc(0);
  let stopped = false;
  let status = { state: "idle", error: null };
  const pending = new Map(); // nonce -> activity sent

  function setState(state, error = null) {
    if (status.state === state && status.error === error) {
      return;
    }
    status = { state, error };
    onState({ ...status });
  }

  function send(activity) {
    const key = JSON.stringify(activity);
    if (!ready || !socket || key === sent) {
      return;
    }
    sent = key;
    const nonce = crypto.randomUUID();
    pending.set(nonce, activity);
    socket.write(encode(OP.FRAME, { cmd: "SET_ACTIVITY", args: { pid, activity }, nonce }));
  }

  function reset() {
    ready = false;
    connecting = false;
    sent = "";
    buffer = Buffer.alloc(0);
    pending.clear();
    if (socket) {
      socket.removeAllListeners();
      socket.destroy();
      socket = null;
    }
  }

  function scheduleRetry() {
    if (stopped || retryTimer || !wanted) {
      return;
    }
    retryTimer = setTimeout(() => {
      retryTimer = null;
      open();
    }, retryMs);
    retryTimer.unref?.();
  }

  // pathFor(index) is one path or a list of places to look, tried in turn.
  function tryPipe(index, variant = 0) {
    if (index > 9) {
      connecting = false;
      setState("no_discord");
      scheduleRetry();
      return;
    }
    const paths = [].concat(pathFor(index));
    const candidate = connect(paths[variant]);
    candidate.once("error", () => {
      candidate.destroy();
      if (variant + 1 < paths.length) {
        tryPipe(index, variant + 1);
      } else {
        tryPipe(index + 1);
      }
    });
    candidate.once("connect", () => {
      candidate.removeAllListeners("error");
      socket = candidate;
      socket.on("data", onData);
      socket.on("error", () => {});
      socket.on("close", () => {
        if (ready) {
          log("Discord closed the connection.");
        }
        reset();
        if (status.state !== "rejected") {
          setState("no_discord");
        }
        scheduleRetry();
      });
      socket.write(encode(OP.HANDSHAKE, { v: 1, client_id: clientId }));
    });
  }

  function onData(chunk) {
    buffer = Buffer.concat([buffer, chunk]);
    const { frames, rest } = decode(buffer);
    buffer = rest;
    for (const frame of frames) {
      if (frame.op === OP.PING) {
        socket.write(encode(OP.PONG, frame.data || {}));
      } else if (frame.op === OP.CLOSE) {
        const message = String((frame.data && frame.data.message) || "closed");
        log(`Discord refused the connection: ${message}`);
        setState("rejected", message.slice(0, 200));
        reset();
        scheduleRetry();
        return;
      } else if (frame.op === OP.FRAME && frame.data && frame.data.evt === "READY") {
        ready = true;
        connecting = false;
        log("Connected to Discord.");
        setState("connected");
        if (wanted !== undefined) {
          send(wanted);
        }
      } else if (frame.op === OP.FRAME && frame.data && pending.has(frame.data.nonce)) {
        // The answer to a SET_ACTIVITY: accepted, or an ERROR with the reason.
        const activity = pending.get(frame.data.nonce);
        pending.delete(frame.data.nonce);
        if (frame.data.evt === "ERROR") {
          const message = String((frame.data.data && frame.data.data.message) || "error").slice(0, 200);
          log(`Discord did not accept the activity: ${message}`);
          setState("rejected", message);
          sent = ""; // try again with the next update
        } else {
          setState(activity ? "shown" : "connected");
        }
      }
    }
  }

  function open() {
    if (stopped || socket || connecting) {
      return;
    }
    connecting = true;
    if (status.state === "idle") {
      setState("connecting");
    }
    tryPipe(0);
  }

  return {
    /** The activity to show (null clears it). */
    update(activity) {
      wanted = activity;
      if (ready) {
        send(activity);
      } else if (activity) {
        open();
      }
    },
    isReady: () => ready,
    getState: () => ({ ...status }),
    stop() {
      stopped = true;
      clearTimeout(retryTimer);
      retryTimer = null;
      if (socket && ready) {
        try {
          socket.write(encode(OP.FRAME, { cmd: "SET_ACTIVITY", args: { pid }, nonce: crypto.randomUUID() }));
        } catch {
          // Closing anyway.
        }
      }
      reset();
    }
  };
}

module.exports = { CLIENT_ID, OP, buildActivity, createDiscordPresence, decode, encode, ipcPath, ipcPaths, trackMatchStart };
