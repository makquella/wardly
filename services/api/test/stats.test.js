import assert from "node:assert/strict";
import test from "node:test";

import worker, { cleanup, config, sendWeeklyStats } from "../src/index.js";
import { aggregateStats, deviceRetention, isoDay, validateStats, weeklyStatsText } from "../src/stats.js";

const DAY = 24 * 3_600_000;
// The Worker checks the day against the real clock, so the tests run on it too.
const NOW = Date.now();
// The next Monday (UTC) on or after today: the weekly note covers the 7 days before it.
const MONDAY = NOW + ((8 - new Date(NOW).getUTCDay()) % 7) * DAY;
const INSTALL = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

const STATS = {
  install_id: INSTALL,
  day: isoDay(NOW - DAY),
  version: "0.17.0",
  os: "win32",
  lang: "uk",
  usage: {
    matches: 3,
    with_advice: 2,
    advice: { LOW_HP_WARNING: 5, LANING_FARM_CHECK: 2, "bad kind": 7 },
    ignored: { LOW_HP_WARNING: 2 }
  },
  settings: { overlay: true, voice: "urgent", frequency: "normal", role: "auto", map_hints: true, discord: false, nickname: "x" },
  ai: "ready",
  opendota_key: false,
  fullscreen: false,
  sync_error: null,
  // Nothing outside the allowlist is kept.
  steam_id: "76561198000000000",
  hero: "Juggernaut",
  match_id: 8843382732
};

// A D1 stand-in for the statements the statistics use (and the ones the device
// delete and the cleanup run on the other tables).
function fakeEnv(vars = {}) {
  const daily = new Map();
  const rate = new Map();
  const DB = {
    prepare(sql) {
      let args = [];
      const stmt = {
        bind(...values) {
          args = values;
          return stmt;
        },
        async first() {
          if (sql.startsWith("INSERT INTO rate")) {
            const key = `${args[0]}|${args[1]}`;
            rate.set(key, (rate.get(key) || 0) + 1);
            return { count: rate.get(key) };
          }
          throw new Error(`unexpected first(): ${sql}`);
        },
        async all() {
          if (sql.startsWith("SELECT install_hash, day")) {
            return { results: [...daily.values()].filter((r) => r.day >= args[0]) };
          }
          if (sql.startsWith("SELECT day, src, visits, downloads FROM channel_counts")) {
            return { results: [] };
          }
          if (sql.startsWith("SELECT r2_key FROM reports") || sql.startsWith("SELECT r2_key FROM sessions") || sql.startsWith("SELECT id, r2_key FROM reports") || sql.startsWith("SELECT id, r2_key FROM sessions")) {
            return { results: [] };
          }
          throw new Error(`unexpected all(): ${sql}`);
        },
        async run() {
          if (sql.startsWith("INSERT INTO daily_stats")) {
            const [install_hash, day, created_at, version, body] = args;
            daily.set(`${install_hash}|${day}`, { install_hash, day, created_at, version, body });
          } else if (sql.startsWith("DELETE FROM daily_stats WHERE install_hash")) {
            for (const [key, row] of [...daily]) if (row.install_hash === args[0]) daily.delete(key);
          } else if (sql.startsWith("DELETE FROM daily_stats WHERE day <")) {
            for (const [key, row] of [...daily]) if (row.day < args[0]) daily.delete(key);
          } else if (!sql.startsWith("DELETE FROM")) {
            throw new Error(`unexpected run(): ${sql}`);
          }
          return { success: true };
        }
      };
      return stmt;
    }
  };
  return { env: { DB, ...vars }, daily, rate };
}

const ctx = { waitUntil: (promise) => promise };

function post(body, ip = "203.0.113.9") {
  return new Request("https://api.example/v1/stats", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": ip },
    body: typeof body === "string" ? body : JSON.stringify(body)
  });
}

test("only allowlisted fields and counts are kept", () => {
  const checked = validateStats(STATS, NOW);
  assert.equal(checked.ok, true);
  assert.deepEqual(checked.row, {
    os: "win32",
    lang: "uk",
    matches: 3,
    with_advice: 2,
    advice: { LOW_HP_WARNING: 5, LANING_FARM_CHECK: 2 },
    ignored: { LOW_HP_WARNING: 2 },
    settings: { voice: "urgent", frequency: "normal", role: "auto", overlay: true, map_hints: true, discord: false },
    ai: "ready",
    opendota_key: false,
    fullscreen: false,
    sync_error: null,
    app: { launches: 0, backend_crashes: 0, renderer_crashes: 0, unclean_exits: 0 },
    marks: { useful: 0, irrelevant: 0, repeated: 0 },
    noisy: {},
    setup: {},
    age: null
  });
  const stored = JSON.stringify(checked.row);
  for (const secret of ["76561198", "Juggernaut", "8843382732", "nickname", INSTALL]) {
    assert.ok(!stored.includes(secret), secret);
  }
  assert.equal(validateStats({ ...STATS, day: isoDay(NOW + 3 * DAY) }, NOW).code, "bad_day");
  assert.equal(validateStats({ ...STATS, day: isoDay(NOW - 10 * DAY) }, NOW).code, "bad_day");
  assert.equal(validateStats({ ...STATS, install_id: "x" }, NOW).code, "bad_install_id");
  assert.equal(validateStats({ ...STATS, version: "dev" }, NOW).code, "bad_version");
  assert.equal(validateStats({ ...STATS, usage: { matches: -1, advice: { A_B: 1e9 } } }, NOW).row.matches, 0);
});

test("one row per installation and day; the device delete and the cleanup remove it", async () => {
  const { env, daily, rate } = fakeEnv();
  const first = await worker.fetch(post(STATS), env, ctx);
  assert.equal(first.status, 201);
  // Sent again (a retry): replaced, not added.
  await worker.fetch(post({ ...STATS, usage: { ...STATS.usage, matches: 4 } }), env, ctx);
  assert.equal(daily.size, 1);
  const [row] = daily.values();
  assert.equal(JSON.parse(row.body).matches, 4);
  assert.notEqual(row.install_hash, INSTALL);
  assert.ok(!row.body.includes(INSTALL));
  // Nor in the rate counters: the install id is stored only as its hash.
  assert.ok([...rate.keys()].every((key) => !key.includes(INSTALL)), [...rate.keys()].join());

  await worker.fetch(new Request(`https://api.example/v1/device/${INSTALL}`, { method: "DELETE" }), env, ctx);
  assert.equal(daily.size, 0);

  await worker.fetch(post(STATS), env, ctx);
  await cleanup(env, NOW + 366 * DAY);
  assert.equal(daily.size, 0);
});

test("the kill switch, bad bodies and the rate limit", async () => {
  const { env } = fakeEnv();
  assert.equal(config({ STATS_ENABLED: "false" }).stats, false);
  assert.equal((await worker.fetch(post(STATS), { ...env, STATS_ENABLED: "false" }, ctx)).status, 503);
  assert.equal((await worker.fetch(post("{"), env, ctx)).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(20_000)), env, ctx)).status, 413);
  const statuses = [];
  for (let i = 0; i < 7; i += 1) {
    statuses.push((await worker.fetch(post(STATS), env, ctx)).status);
  }
  assert.deepEqual(statuses, [201, 201, 201, 201, 201, 201, 429]);
});

test("the admin summary and the weekly note", async () => {
  const { env } = fakeEnv({ ADMIN_TOKEN: "t0ken" });
  await worker.fetch(post(STATS), env, ctx);
  await worker.fetch(post({ ...STATS, install_id: "other-install-1", lang: "en", usage: { matches: 1, advice: { LOW_HP_WARNING: 1 } } }, "203.0.113.10"), env, ctx);
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/stats"), env, ctx)).status, 404);
  const answer = await (
    await worker.fetch(new Request("https://api.example/v1/admin/stats?days=7", { headers: { authorization: "Bearer t0ken" } }), env, ctx)
  ).json();
  assert.equal(answer.stats.devices, 2);
  assert.equal(answer.stats.matches, 4);
  assert.deepEqual(answer.stats.advice, { LOW_HP_WARNING: 6, LANING_FARM_CHECK: 2 });
  assert.deepEqual(answer.stats.ignored_share, { LOW_HP_WARNING: 33 });
  assert.deepEqual(answer.stats.langs, { uk: 1, en: 1 });
  assert.equal(answer.stats.retention.devices, 2);
  assert.equal(answer.stats.retention.returned, 0);

  const sent = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    sent.push({ url, body: JSON.parse(init.body) });
    return new Response("{}", { status: 200 });
  };
  try {
    const telegram = { ...env, TELEGRAM_BOT_TOKEN: "bot", TELEGRAM_CHAT_ID: "1" };
    assert.equal(await sendWeeklyStats(telegram, MONDAY), true);
    assert.equal(await sendWeeklyStats(telegram, MONDAY + DAY), false, "Mondays only");
    assert.equal(await sendWeeklyStats(env, MONDAY), false, "no Telegram secrets");
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(sent.length, 1);
  assert.ok(sent[0].body.text.includes("Devices: 2"));
  assert.ok(sent[0].body.text.includes("LOW_HP_WARNING 6"));
});

test("who comes back: active this week, on two or more days, after 7 and 30 days", () => {
  const rows = [
    // Installed long ago, still here.
    { install_hash: "old", day: "2026-09-01" },
    { install_hash: "old", day: "2026-09-09" },
    { install_hash: "old", day: "2026-10-30" },
    // Came back within the first week only.
    { install_hash: "week", day: "2026-10-01" },
    { install_hash: "week", day: "2026-10-04" },
    // One day and gone.
    { install_hash: "once", day: "2026-10-20" },
    // Too new to say anything about 7 days.
    { install_hash: "new", day: "2026-10-29" },
    { install_hash: "new", day: "2026-10-30" },
    { install_hash: "new", day: "2026-10-30" },
    { install_hash: "bad", day: "yesterday" }
  ];
  assert.deepEqual(deviceRetention(rows, "2026-10-31"), {
    devices: 4,
    active7: 2,
    returned: 3,
    d7: { known: 3, kept: 1 },
    d30: { known: 2, kept: 1 }
  });
  assert.deepEqual(deviceRetention([], "2026-10-31"), { devices: 0, active7: 0, returned: 0, d7: { known: 0, kept: 0 }, d30: { known: 0, kept: 0 } });
  const note = weeklyStatsText({ ...aggregateStats([]), retention: deviceRetention(rows, "2026-10-31") });
  assert.ok(note.includes("active in the last 7 days 2, on 2+ days 3, after 7 days 1/3, after 30 days 1/2"), note);
  assert.ok(weeklyStatsText(aggregateStats([])).includes("Coming back: —"));
});

test("a day's devices are split into first-time and returning ones", () => {
  const row = JSON.stringify({ matches: 0, advice: {}, ignored: {} });
  const summary = aggregateStats([
    { install_hash: "a", day: "2026-10-11", version: "0.56.0", body: row },
    { install_hash: "a", day: "2026-10-10", version: "0.56.0", body: row },
    { install_hash: "b", day: "2026-10-11", version: "0.56.0", body: row }
  ]);
  assert.deepEqual(
    summary.by_day.map((d) => [d.day, d.devices, d.fresh]),
    [
      ["2026-10-10", 1, 1],
      ["2026-10-11", 2, 1]
    ]
  );
});

test("aggregate skips broken rows", () => {
  assert.equal(aggregateStats([{ install_hash: "a", day: "2026-09-27", version: "0.17.0", body: "{" }]).rows, 0);
});

test("the statistics page: no data in it, a strict CSP, hidden without a token", async () => {
  const { env } = fakeEnv({ ADMIN_TOKEN: "t0ken" });
  const page = await worker.fetch(new Request("https://api.example/admin"), env, ctx);
  assert.equal(page.status, 200);
  const csp = page.headers.get("content-security-policy");
  assert.ok(csp.includes("script-src 'self'") && csp.includes("default-src 'none'"), csp);
  assert.equal(page.headers.get("x-robots-tag"), "noindex, nofollow");
  const html = await page.text();
  assert.ok(html.includes('<script src="/admin/app.js"></script>'));
  assert.ok(!html.includes("t0ken"));
  const script = await worker.fetch(new Request("https://api.example/admin/app.js"), env, ctx);
  assert.match(script.headers.get("content-type"), /javascript/);
  const code = await script.text();
  assert.ok(code.includes("/v1/admin/stats?days=") && code.includes("authorization"));
  // The script parses (the page would be blank otherwise).
  assert.doesNotThrow(() => new Function(code));
  const hidden = fakeEnv();
  assert.equal((await worker.fetch(new Request("https://api.example/admin"), hidden.env, ctx)).status, 404);
});

test("the summary has a row per day", () => {
  const body = (matches, advice, ignored) => JSON.stringify({ matches, advice, ignored });
  const summary = aggregateStats([
    { install_hash: "a", day: "2026-09-27", version: "0.17.0", body: body(2, { A_B: 3 }, { A_B: 1 }) },
    { install_hash: "b", day: "2026-09-26", version: "0.17.0", body: body(1, { A_B: 1 }, {}) },
    { install_hash: "b", day: "2026-09-27", version: "0.17.0", body: body(4, { C_D: 2 }, {}) }
  ]);
  assert.deepEqual(summary.by_day, [
    { day: "2026-09-26", devices: 1, fresh: 1, matches: 1, advice: 1, ignored: 0 },
    { day: "2026-09-27", devices: 2, fresh: 1, matches: 6, advice: 5, ignored: 1 }
  ]);
});

test("launches, crashes, advice marks and first-run steps are kept as counts and flags only", () => {
  const checked = validateStats(
    {
      ...STATS,
      app: { launches: 3, backend_crashes: 1, renderer_crashes: -2, unclean_exits: 999, path: "C:\\Users\\me" },
      marks: { useful: 4, irrelevant: 1, repeated: "2", text: "bad advice" },
      noisy: { LANING_FARM_CHECK: 1, "bad kind": 3 },
      setup: { dota: true, gsi: true, launch: null, data: false, folder: "D:\\Steam", advice: "yes" },
      age: "2-6"
    },
    NOW
  );
  assert.deepEqual(checked.row.app, { launches: 3, backend_crashes: 1, renderer_crashes: 0, unclean_exits: 0 });
  assert.deepEqual(checked.row.marks, { useful: 4, irrelevant: 1, repeated: 0 });
  assert.deepEqual(checked.row.noisy, { LANING_FARM_CHECK: 1 });
  assert.deepEqual(checked.row.setup, { dota: true, gsi: true, data: false });
  assert.equal(checked.row.age, "2-6");
  assert.equal(validateStats({ ...STATS, age: "100" }, NOW).row.age, null);
  const stored = JSON.stringify(checked.row);
  for (const secret of ["Users", "Steam", "bad advice"]) {
    assert.ok(!stored.includes(secret), secret);
  }
});

test("the summary counts crash-free days, marks and the first-run funnel by each device's newest row", () => {
  const row = (app, setup, extra = {}) => JSON.stringify({ matches: 0, advice: {}, ignored: {}, app, setup, ...extra });
  const summary = aggregateStats([
    { install_hash: "a", day: "2026-10-10", version: "0.56.0", body: row({ launches: 2 }, { dota: true, gsi: false }, { age: "0" }) },
    {
      install_hash: "a",
      day: "2026-10-11",
      version: "0.56.0",
      body: row({ launches: 1, backend_crashes: 1 }, { dota: true, gsi: true, data: true }, {
        age: "1",
        marks: { useful: 3, irrelevant: 1, repeated: 0 },
        noisy: { LANING_FARM_CHECK: 1 }
      })
    },
    { install_hash: "b", day: "2026-10-11", version: "0.56.0", body: row({ launches: 1 }, { dota: true, gsi: false, data: false }, { age: "30+" }) },
    // An older version without the new fields counts for nothing new.
    { install_hash: "c", day: "2026-10-11", version: "0.55.0", body: row(undefined, undefined) }
  ]);
  assert.deepEqual(summary.app, { launches: 4, backend_crashes: 1, renderer_crashes: 0, unclean_exits: 0 });
  assert.equal(summary.crash_free, 66.7);
  assert.deepEqual(summary.marks, { useful: 3, irrelevant: 1, repeated: 0 });
  assert.deepEqual(summary.noisy, { LANING_FARM_CHECK: 1 });
  assert.equal(summary.setup.dota, 2);
  assert.equal(summary.setup.gsi, 1);
  assert.equal(summary.setup_known.gsi, 2);
  assert.equal(summary.setup.data, 1);
  assert.equal(summary.setup_known.advice, 0);
  assert.deepEqual(summary.ages, { 1: 1, "30+": 1 });
  const text = weeklyStatsText({ ...summary, channels: [] });
  assert.ok(text.includes("Launches: 4; crashes: service 1, window 0, unclean exits 0; days without a crash: 66.7%"), text);
  assert.ok(text.includes("Advice marks: useful 3 (75%), not to the point 1, repeated 0; noisiest: LANING_FARM_CHECK 1"), text);
  assert.ok(text.includes("First run (devices that reached the step): dota 2/2, gsi 1/2, data 1/2"), text);
  const empty = weeklyStatsText(aggregateStats([]));
  assert.ok(empty.includes("Launches: —") && empty.includes("Advice marks: —"), empty);
});
