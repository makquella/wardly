// Problem report: one text file a tester can send to the developer. Pure
// helpers (no Electron) so they are unit-tested; main.js gathers the parts
// and writes the file.
//
// Nothing secret may leave the machine: API keys are cut out of every part
// (log lines and JSON fields named api_key included).

const SECRET_PATTERNS = [
  /AIza[\w-]{20,}/g, // Google / Gemini
  /AQ\.[\w-]{20,}/g, // Google AI Studio (new format)
  /gsk_[\w-]{16,}/g, // Groq
  /sk-[\w-]{16,}/g, // OpenRouter and other OpenAI-style keys
  /Bearer\s+[\w.-]{12,}/g,
  /\b[0-9a-fA-F]{64}\b/g, // Local control/GSI credentials, including pasted Valve configs
  /(?<=api_key=)[^&\s'"]+/g, // OpenDota key in a URL
  /(?<=\/api\/(?:v\d+\/)?webhooks\/\d+\/)[\w-]+/g // Discord webhook token (the week in Discord)
];
// JSON fields holding a secret: API keys, the delete tokens of shared links
// (settings.shares), the Discord webhook link and the device key.
const KEY_FIELD = /("(?:api_?key|token|delete_?token|discord_?webhook|device_?key)"\s*:\s*")[^"]*"/gi;

const LOG_TAIL_LINES = 600;

// No nicknames or Steam ids in a report (site/privacy.html): JSON fields that
// name the player, SteamID64s, OpenDota player URLs and the Windows user name
// in paths are replaced.
const IDENTITY_FIELD =
  /("(?:account_?id|steam_?id(?:64)?|persona_?name|personaname|real_?name|avatar\w*|profile_?url)"\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d+)/gi;
const IDENTITY_PATTERNS = [
  [/\b7656119\d{10}\b/g, "[steam id]"],
  [/(\/players\/)\d+/g, "$1[id]"],
  [/(account[_ ]?id[=: ]+)\d+/gi, "$1[id]"],
  // Service job and cache keys carry the account (or a friend's): "sync:<id>",
  // "coach:match:<id>:<match>:uk", "match:<id>:<match>:uk". A bare
  // "match:<match>" job keeps its match id.
  [/\b((?:coach:(?:match|career|ask)|sync|rebuild|career|friend|mmr|cosmetics|last_review|rank_history):)\d+/g, "$1[id]"],
  [/\b(match:)\d+(?=:\d+:)/g, "$1[id]"],
  [/([A-Za-z]:(?:\\\\|\\|\/)+Users(?:\\\\|\\|\/)+)[^\\/"'\s]+/gi, "$1[user]"],
  [/(\/home\/)[^/"'\s]+/g, "$1[user]"]
];

function redact(text) {
  let result = String(text ?? "").replace(KEY_FIELD, '$1[redacted]"');
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, "[redacted]");
  }
  return result;
}

function anonymize(text) {
  let result = String(text ?? "").replace(IDENTITY_FIELD, '$1"[removed]"');
  for (const [pattern, replacement] of IDENTITY_PATTERNS) {
    result = result.replace(pattern, replacement);
  }
  return result;
}

function tail(text, lines = LOG_TAIL_LINES) {
  const all = String(text ?? "").replace(/\r/g, "").split("\n");
  while (all.length && all[all.length - 1] === "") {
    all.pop();
  }
  return all.slice(-lines).join("\n");
}

function reportFileName(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  const stamp = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
  return `Wardly-report-${stamp}.txt`;
}

function section(title, body) {
  const text = typeof body === "string" ? body : JSON.stringify(body, null, 2);
  return `===== ${title} =====\n${text || "(empty)"}\n`;
}

// parts: { app, status, settings, watcher, diagnostics, diagnosticsError, launcherLog, note }
function buildReport(parts, date = new Date()) {
  const blocks = [
    `Wardly problem report\nCreated: ${date.toISOString()}\n` +
      "API keys, Steam ids and nicknames are removed from this file. Send it to the developer together with a short description.\n",
    section("App", parts.app || {}),
    section("Launcher status", parts.status || {}),
    section("Settings", parts.settings || {}),
    section("Settings persistence", parts.settingsHealth || {}),
    section("Dota watcher", parts.watcher || {}),
    section(
      "Service diagnostics (GET /diagnostics)",
      parts.diagnostics || `Not available: ${parts.diagnosticsError || "the service is not running"}`
    ),
    section(`Launcher log (last ${LOG_TAIL_LINES} lines)`, tail(parts.launcherLog))
  ];
  return anonymize(redact(blocks.join("\n")));
}

// --- Sending the report (docs/DATA_PLAN.md, stage 1) ------------------------
// «Надіслати розробникові» posts the same report to the project's API; when it
// cannot be sent now it waits in an outbox and goes out later.

const API_URL = "https://api.luhovyimvp.dev";
const PRIVACY_URL = "https://luhovyimvp.dev/privacy.html";
const NOTE_MAX = 2000;
const OUTBOX_MAX = 10;

function apiUrl(env = process.env) {
  return String(env.DOTA_AI_API_URL || API_URL).replace(/\/+$/, "");
}

// app: { version, os, locale }
function uploadPayload({ text, note, installId, app = {} }) {
  return {
    install_id: String(installId || ""),
    version: String(app.version || ""),
    os: String(app.os || "").slice(0, 64),
    lang: String(app.locale || "").slice(0, 8),
    note: redact(String(note || "").trim().slice(0, NOTE_MAX)),
    text: anonymize(redact(text))
  };
}

// The player's note on top, as the service stores it (for a report saved as a
// file instead of being sent).
function withNote(text, note) {
  const clean = redact(String(note || "").trim().slice(0, NOTE_MAX));
  return clean ? `Player note:\n${clean}\n\n${text}` : String(text ?? "");
}

// Send again later: no connection, the service is busy or switched off. A
// report the service refuses (too large, malformed) is never sent again.
function isRetryable(result) {
  if (!result || result.ok) {
    return false;
  }
  const status = Number(result.status || 0);
  return result.code === "offline" || status === 429 || status >= 500;
}

// Outbox files are named by time; the oldest go when there are too many.
function outboxOverflow(names, max = OUTBOX_MAX) {
  const sorted = [...names].filter((name) => name.endsWith(".json")).sort();
  return sorted.slice(0, Math.max(0, sorted.length - max));
}

module.exports = {
  API_URL,
  NOTE_MAX,
  OUTBOX_MAX,
  PRIVACY_URL,
  anonymize,
  apiUrl,
  buildReport,
  isRetryable,
  outboxOverflow,
  redact,
  reportFileName,
  tail,
  uploadPayload,
  withNote,
  LOG_TAIL_LINES
};
