// Opt-in anonymous statistics («Анонімна статистика» in the launcher's
// Settings → App, off by default): one row per installation and day, rebuilt
// here field by field from an allowlist, so nothing else can be stored.
//
// A row says which advice the app showed (per decision point), which urgent
// warnings were followed by a death within 30 s, how many matches were
// analysed, and the few settings that shape the advice. Since 0.56 also the
// day's launches and crashes, the advice marks given since the last row
// («Корисно / Не до речі / Повторювалося», and the noisy ones per decision
// point), the first-run steps the installation has reached and its age as a
// bucket. No match ids, heroes, times, texts, nicknames, Steam IDs or keys; the
// installation id is kept only as a salted hash (device delete still finds it).

export const STATS_RETENTION_DAYS = 365;
export const STATS_RATE_PER_HOUR = { install: 6, address: 60 };
export const STATS_MAX_BYTES = 16 * 1024;
export const STATS_MAX_KINDS = 60;
export const STATS_ADMIN_MAX_DAYS = 90;

const DAY_MS = 24 * 3_600_000;
const KIND = /^[A-Z][A-Z0-9_]{1,47}$/;
const CHOICES = {
  voice: ["off", "urgent", "all"],
  frequency: ["calm", "normal", "active"],
  role: ["auto", "carry", "mid", "offlane", "support"]
};
const FLAGS = ["overlay", "map_hints", "discord"];
// The launcher's daily app counters and their caps.
const APP_COUNTERS = { launches: 200, backend_crashes: 100, renderer_crashes: 100, unclean_exits: 50 };
const VERDICTS = ["useful", "irrelevant", "repeated"];
// First-run steps in the order a new player meets them (launcher advice-stats.js).
export const SETUP_STEPS = ["dota", "gsi", "launch", "data", "preview", "account", "advice", "review", "ai"];
const AGES = ["0", "1", "2-6", "7-29", "30+"];

function count(value, max) {
  return Number.isInteger(value) && value >= 0 && value <= max ? value : null;
}

function counters(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const out = {};
  for (const [kind, n] of Object.entries(value).slice(0, STATS_MAX_KINDS)) {
    const checked = count(n, 10_000);
    if (KIND.test(kind) && checked !== null) {
      out[kind] = checked;
    }
  }
  return out;
}

export function isoDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

/** { ok, row } or { ok: false, status, code }. `now` decides which days are accepted. */
export function validateStats(body, now = Date.now()) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, status: 400, code: "bad_body" };
  }
  const installId = String(body.install_id || "").toLowerCase();
  if (!/^[a-z0-9-]{8,64}$/.test(installId)) {
    return { ok: false, status: 400, code: "bad_install_id" };
  }
  const day = String(body.day || "");
  // Yesterday or up to a week before (a computer that was off), never the future.
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day > isoDay(now + DAY_MS) || day < isoDay(now - 8 * DAY_MS)) {
    return { ok: false, status: 400, code: "bad_day" };
  }
  const version = String(body.version || "");
  if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(version)) {
    return { ok: false, status: 400, code: "bad_version" };
  }
  const usage = body.usage && typeof body.usage === "object" ? body.usage : {};
  const settings = body.settings && typeof body.settings === "object" ? body.settings : {};
  const row = {
    os: ["win32", "linux", "darwin"].includes(body.os) ? body.os : "other",
    lang: ["uk", "en"].includes(body.lang) ? body.lang : "other",
    matches: count(usage.matches, 200) ?? 0,
    with_advice: count(usage.with_advice, 200) ?? 0,
    advice: counters(usage.advice),
    ignored: counters(usage.ignored),
    settings: {},
    ai: ["off", "ready", "error", "none"].includes(body.ai) ? body.ai : "none",
    opendota_key: body.opendota_key === true,
    fullscreen: body.fullscreen === true,
    sync_error: typeof body.sync_error === "string" && /^[a-z_]{1,32}$/.test(body.sync_error) ? body.sync_error : null,
    app: {},
    marks: {},
    noisy: counters(body.noisy),
    setup: {},
    age: AGES.includes(body.age) ? body.age : null
  };
  const app = body.app && typeof body.app === "object" ? body.app : {};
  for (const [key, max] of Object.entries(APP_COUNTERS)) {
    row.app[key] = count(app[key], max) ?? 0;
  }
  const marks = body.marks && typeof body.marks === "object" ? body.marks : {};
  for (const verdict of VERDICTS) {
    row.marks[verdict] = count(marks[verdict], 1000) ?? 0;
  }
  const setup = body.setup && typeof body.setup === "object" ? body.setup : {};
  for (const step of SETUP_STEPS) {
    if (typeof setup[step] === "boolean") {
      row.setup[step] = setup[step];
    }
  }
  for (const [key, allowed] of Object.entries(CHOICES)) {
    if (allowed.includes(settings[key])) {
      row.settings[key] = settings[key];
    }
  }
  for (const key of FLAGS) {
    if (typeof settings[key] === "boolean") {
      row.settings[key] = settings[key];
    }
  }
  return { ok: true, installId, day, version, row };
}

function add(target, source) {
  for (const [key, n] of Object.entries(source || {})) {
    target[key] = (target[key] || 0) + n;
  }
}

function tally(target, key) {
  if (key !== undefined && key !== null) {
    target[String(key)] = (target[String(key)] || 0) + 1;
  }
}

/** Sums over stored rows ({ install_hash, day, version, body }): what the admin sees. */
export function aggregateStats(rows) {
  const result = {
    rows: 0,
    devices: 0,
    matches: 0,
    with_advice: 0,
    advice: {},
    ignored: {},
    versions: {},
    langs: {},
    ai: {},
    settings: { voice: {}, frequency: {}, role: {}, overlay: {}, map_hints: {}, discord: {} },
    fullscreen: 0,
    sync_errors: {},
    // Launches and crashes summed over the rows; `crash_free` = the share of
    // device-days with a launch and no crash or unclean exit (null without launches).
    app: { launches: 0, backend_crashes: 0, renderer_crashes: 0, unclean_exits: 0 },
    crash_free: null,
    marks: { useful: 0, irrelevant: 0, repeated: 0 },
    noisy: {},
    // Devices that reached each first-run step (their newest row), and how many devices answered it at all.
    setup: {},
    setup_known: {},
    ages: {},
    // Per day, oldest first: devices that sent it, matches, advice shown, warnings before a death.
    by_day: []
  };
  const devices = new Set();
  const days = new Map();
  const newest = new Map();
  let launchDays = 0;
  let cleanDays = 0;
  for (const stored of rows) {
    let body;
    try {
      body = JSON.parse(stored.body);
    } catch {
      continue;
    }
    result.rows += 1;
    devices.add(stored.install_hash);
    result.matches += body.matches || 0;
    result.with_advice += body.with_advice || 0;
    add(result.advice, body.advice);
    add(result.ignored, body.ignored);
    tally(result.versions, stored.version);
    tally(result.langs, body.lang);
    tally(result.ai, body.ai);
    for (const key of Object.keys(result.settings)) {
      tally(result.settings[key], body.settings?.[key]);
    }
    result.fullscreen += body.fullscreen ? 1 : 0;
    tally(result.sync_errors, body.sync_error);
    const app = body.app || {};
    for (const key of Object.keys(result.app)) {
      result.app[key] += app[key] || 0;
    }
    if (app.launches > 0) {
      launchDays += 1;
      if (!app.backend_crashes && !app.renderer_crashes && !app.unclean_exits) {
        cleanDays += 1;
      }
    }
    add(result.marks, body.marks);
    add(result.noisy, body.noisy);
    const seen = newest.get(stored.install_hash);
    if (!seen || seen.day < stored.day) {
      newest.set(stored.install_hash, { day: stored.day, setup: body.setup || {}, age: body.age });
    }
    const day = days.get(stored.day) || { day: stored.day, devices: 0, matches: 0, advice: 0, ignored: 0 };
    day.devices += 1;
    day.matches += body.matches || 0;
    day.advice += Object.values(body.advice || {}).reduce((a, b) => a + b, 0);
    day.ignored += Object.values(body.ignored || {}).reduce((a, b) => a + b, 0);
    days.set(stored.day, day);
  }
  result.devices = devices.size;
  result.crash_free = launchDays ? Math.round((1000 * cleanDays) / launchDays) / 10 : null;
  for (const step of SETUP_STEPS) {
    result.setup[step] = 0;
    result.setup_known[step] = 0;
  }
  for (const { setup, age } of newest.values()) {
    for (const step of SETUP_STEPS) {
      if (typeof setup[step] === "boolean") {
        result.setup_known[step] += 1;
        result.setup[step] += setup[step] ? 1 : 0;
      }
    }
    tally(result.ages, age);
  }
  result.by_day = [...days.values()].sort((a, b) => (a.day < b.day ? -1 : 1));
  // Per decision point: how often a shown urgent warning was followed by a death.
  result.ignored_share = Object.fromEntries(
    Object.entries(result.ignored).map(([kind, n]) => [kind, result.advice[kind] ? Math.round((100 * n) / result.advice[kind]) : null])
  );
  return result;
}

function launchesLine(summary) {
  const app = summary.app || {};
  if (!app.launches) {
    return "Launches: —";
  }
  const share = summary.crash_free === null || summary.crash_free === undefined ? "—" : `${summary.crash_free}%`;
  return `Launches: ${app.launches}; crashes: service ${app.backend_crashes}, window ${app.renderer_crashes}, unclean exits ${app.unclean_exits}; days without a crash: ${share}`;
}

function marksLine(summary) {
  const marks = summary.marks || {};
  const total = (marks.useful || 0) + (marks.irrelevant || 0) + (marks.repeated || 0);
  if (!total) {
    return "Advice marks: —";
  }
  const noisy = Object.entries(summary.noisy || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([kind, n]) => `${kind} ${n}`)
    .join(", ");
  return `Advice marks: useful ${marks.useful} (${Math.round((100 * marks.useful) / total)}%), not to the point ${marks.irrelevant}, repeated ${marks.repeated}${
    noisy ? `; noisiest: ${noisy}` : ""
  }`;
}

/** The weekly Telegram note for the developer. */
export function weeklyStatsText(summary) {
  const top = (counts, n) =>
    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([kind, value]) => `${kind} ${value}`)
      .join(", ") || "—";
  return [
    "Wardly: stats of the last 7 days",
    `Devices: ${summary.devices}, days sent: ${summary.rows}`,
    `Matches analysed: ${summary.matches} (with live advice: ${summary.with_advice})`,
    `Advice shown: ${top(summary.advice, 8)}`,
    `Warnings before a death: ${top(summary.ignored, 5)}`,
    launchesLine(summary),
    marksLine(summary),
    `First run (devices that reached the step): ${
      SETUP_STEPS.filter((step) => (summary.setup_known || {})[step])
        .map((step) => `${step} ${summary.setup[step]}/${summary.setup_known[step]}`)
        .join(", ") || "—"
    }`,
    `New installations (days since install): ${top(summary.ages || {}, 5)}`,
    `Versions: ${top(summary.versions, 4)}`,
    `Sources (visits → downloads): ${
      (summary.channels || [])
        .slice(0, 6)
        .map((c) => `${c.src} ${c.visits}→${c.downloads}`)
        .join(", ") || "—"
    }`
  ].join("\n");
}
