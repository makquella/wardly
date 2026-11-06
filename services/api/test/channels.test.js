import assert from "node:assert/strict";
import test from "node:test";

import worker, { cleanup, handleDownload, handleHit, sendWeeklyStats } from "../src/index.js";
import {
  CHANNEL_MAX_SOURCES,
  CHANNEL_RATE_PER_HOUR,
  RELEASES_PAGE,
  aggregateChannels,
  channelSource,
  installerUrl,
  latestInstaller,
  resetInstallerCache
} from "../src/channels.js";
import { isoDay, weeklyStatsText } from "../src/stats.js";

const NOW = Date.UTC(2026, 8, 29, 12);
const DAY = 24 * 3_600_000;

// D1 stand-in for the channel_counts statements (and the rest the admin summary and the cleanup run).
function fakeEnv(vars = {}) {
  const counts = new Map();
  const rate = new Map();
  const DB = {
    counts,
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
          if (sql.startsWith("SELECT COUNT(*) AS sources")) {
            const today = [...counts.values()].filter((r) => r.day === args[0]);
            return { sources: today.length, known: today.some((r) => r.src === args[1]) ? 1 : 0 };
          }
          throw new Error(`unexpected first(): ${sql}`);
        },
        async all() {
          if (sql.startsWith("SELECT day, src, visits, downloads FROM channel_counts WHERE day >= ?1 AND day < ?2")) {
            return { results: [...counts.values()].filter((r) => r.day >= args[0] && r.day < args[1]) };
          }
          if (sql.startsWith("SELECT install_hash, day, version, body FROM daily_stats")) {
            return { results: [] };
          }
          if (sql.startsWith("SELECT id, r2_key FROM reports") || sql.startsWith("SELECT id, r2_key FROM sessions")) {
            return { results: [] };
          }
          throw new Error(`unexpected all(): ${sql}`);
        },
        async run() {
          if (sql.startsWith("INSERT INTO channel_counts")) {
            const [day, src, visits, downloads] = args;
            const row = counts.get(`${day}|${src}`) || { day, src, visits: 0, downloads: 0 };
            row.visits += visits;
            row.downloads += downloads;
            counts.set(`${day}|${src}`, row);
          } else if (sql.startsWith("DELETE FROM channel_counts WHERE day <")) {
            for (const [key, row] of [...counts]) if (row.day < args[0]) counts.delete(key);
          } else if (!sql.startsWith("DELETE FROM")) {
            throw new Error(`unexpected run(): ${sql}`);
          }
          return { success: true };
        }
      };
      return stmt;
    }
  };
  return { DB, ADMIN_TOKEN: "secret", ...vars };
}

function hit(src, ip = "203.0.113.5") {
  return new Request("https://api.luhovyimvp.dev/v1/hit", {
    method: "POST",
    headers: { "content-type": "text/plain", "cf-connecting-ip": ip },
    body: JSON.stringify({ src })
  });
}

function githubRedirect(tag) {
  return async (url, init) => {
    assert.equal(url, RELEASES_PAGE);
    assert.equal(init.redirect, "manual");
    return new Response(null, { status: 302, headers: { location: `https://github.com/makquella/wardly/releases/tag/${tag}` } });
  };
}

test("source names are short lowercase slugs", () => {
  assert.equal(channelSource("Pikabu"), "pikabu");
  assert.equal(channelSource("tg_dota-1"), "tg_dota-1");
  for (const bad of ["", "-x", "a b", "x".repeat(25), "https://reddit.com", null, 5]) {
    assert.equal(channelSource(bad), bad === 5 ? "5" : null, String(bad));
  }
});

test("the installer URL comes from the latest release tag", async () => {
  assert.equal(
    installerUrl("https://github.com/makquella/wardly/releases/tag/v0.18.0"),
    "https://github.com/makquella/wardly/releases/download/v0.18.0/Wardly-Setup-0.18.0.exe"
  );
  assert.equal(installerUrl("https://github.com/makquella/wardly/releases"), null);
  resetInstallerCache();
  assert.match(await latestInstaller(githubRedirect("v0.18.0"), NOW), /v0\.18\.0\/Wardly-Setup-0\.18\.0\.exe$/);
  // Cached for 10 minutes, then looked up again.
  assert.match(await latestInstaller(githubRedirect("v0.19.0"), NOW + 60_000), /0\.18\.0/);
  assert.match(await latestInstaller(githubRedirect("v0.19.0"), NOW + 11 * 60_000), /0\.19\.0/);
  // GitHub down with nothing cached: the releases page.
  resetInstallerCache();
  assert.equal(await latestInstaller(async () => { throw new Error("offline"); }, NOW), RELEASES_PAGE);
});

test("a visit and a download are counted per source and day", async () => {
  const env = fakeEnv();
  assert.equal((await handleHit(hit("pikabu"), env, NOW)).status, 204);
  await handleHit(hit("pikabu", "198.51.100.7"), env, NOW);
  resetInstallerCache();
  const response = await handleDownload(
    new Request("https://api.luhovyimvp.dev/d/pikabu", { headers: { "cf-connecting-ip": "203.0.113.5" } }),
    "pikabu",
    env,
    NOW,
    githubRedirect("v0.18.0")
  );
  assert.equal(response.status, 302);
  assert.match(response.headers.get("location"), /Wardly-Setup-0\.18\.0\.exe$/);
  assert.deepEqual(env.DB.counts.get(`${isoDay(NOW)}|pikabu`), { day: isoDay(NOW), src: "pikabu", visits: 2, downloads: 1 });
  // Nothing but the day, the source and two numbers is stored.
  assert.deepEqual(Object.keys(env.DB.counts.get(`${isoDay(NOW)}|pikabu`)).sort(), ["day", "downloads", "src", "visits"]);
});

test("a bad source is refused for a visit and counted as the site for a download", async () => {
  const env = fakeEnv();
  assert.equal((await handleHit(hit("not a source"), env, NOW)).status, 400);
  const bad = new Request("https://api.luhovyimvp.dev/v1/hit", { method: "POST", body: "{" });
  assert.equal((await handleHit(bad, env, NOW)).status, 400);
  resetInstallerCache();
  await handleDownload(new Request("https://api.luhovyimvp.dev/d"), undefined, env, NOW, githubRedirect("v0.18.0"));
  await handleDownload(new Request("https://api.luhovyimvp.dev/d/%20"), "%20", env, NOW, githubRedirect("v0.18.0"));
  assert.equal(env.DB.counts.get(`${isoDay(NOW)}|site`).downloads, 2);
  assert.equal(env.DB.counts.size, 1);
});

test("one address counts only so often, but the download still works", async () => {
  const env = fakeEnv();
  for (let i = 0; i < CHANNEL_RATE_PER_HOUR.visit + 5; i += 1) {
    await handleHit(hit("reddit"), env, NOW);
  }
  assert.equal(env.DB.counts.get(`${isoDay(NOW)}|reddit`).visits, CHANNEL_RATE_PER_HOUR.visit);
  resetInstallerCache();
  let last;
  for (let i = 0; i < CHANNEL_RATE_PER_HOUR.download + 3; i += 1) {
    last = await handleDownload(new Request("https://api.luhovyimvp.dev/d/reddit"), "reddit", env, NOW, githubRedirect("v0.18.0"));
  }
  assert.equal(last.status, 302);
  assert.equal(env.DB.counts.get(`${isoDay(NOW)}|reddit`).downloads, CHANNEL_RATE_PER_HOUR.download);
});

test("a flood of made-up sources ends up as other", async () => {
  const env = fakeEnv();
  for (let i = 0; i < CHANNEL_MAX_SOURCES + 5; i += 1) {
    await handleHit(hit(`src${i}`, `192.0.2.${i}`), env, NOW);
  }
  assert.equal(env.DB.counts.size, CHANNEL_MAX_SOURCES + 1);
  assert.equal(env.DB.counts.get(`${isoDay(NOW)}|other`).visits, 5);
  // A source already seen today keeps counting under its own name.
  await handleHit(hit("src0", "192.0.2.250"), env, NOW);
  assert.equal(env.DB.counts.get(`${isoDay(NOW)}|src0`).visits, 2);
});

test("the kill switch stops counting, never the download", async () => {
  const env = fakeEnv({ CHANNELS_ENABLED: "false" });
  assert.equal((await handleHit(hit("pikabu"), env, NOW)).status, 204);
  resetInstallerCache();
  const response = await handleDownload(new Request("https://api.luhovyimvp.dev/d/pikabu"), "pikabu", env, NOW, githubRedirect("v0.18.0"));
  assert.equal(response.status, 302);
  assert.equal(env.DB.counts.size, 0);
});

test("routes: /v1/hit, /d and /d/<source>, and the admin summary lists the sources", async () => {
  const env = fakeEnv();
  resetInstallerCache();
  const realFetch = globalThis.fetch;
  globalThis.fetch = githubRedirect("v0.18.0");
  try {
    assert.equal((await worker.fetch(hit("dtf"), env)).status, 204);
    const direct = await worker.fetch(new Request("https://api.luhovyimvp.dev/d/dtf"), env);
    assert.equal(direct.status, 302);
    assert.equal((await worker.fetch(new Request("https://api.luhovyimvp.dev/d"), env)).status, 302);
  } finally {
    globalThis.fetch = realFetch;
  }
  const admin = await worker.fetch(
    new Request("https://api.luhovyimvp.dev/v1/admin/stats?days=7", { headers: { authorization: "Bearer secret" } }),
    env
  );
  const { stats } = await admin.json();
  assert.deepEqual(stats.channels, [
    { src: "dtf", visits: 1, downloads: 1, rate: 100 },
    { src: "site", visits: 0, downloads: 1, rate: null }
  ]);
});

test("sources are summed over days, most visits first, with the download rate", () => {
  const rows = [
    { day: "2026-09-28", src: "pikabu", visits: 30, downloads: 3 },
    { day: "2026-09-29", src: "pikabu", visits: 10, downloads: 1 },
    { day: "2026-09-29", src: "search", visits: 50, downloads: 10 },
    { day: "2026-09-29", src: "site", visits: 0, downloads: 2 }
  ];
  assert.deepEqual(aggregateChannels(rows), [
    { src: "search", visits: 50, downloads: 10, rate: 20 },
    { src: "pikabu", visits: 40, downloads: 4, rate: 10 },
    { src: "site", visits: 0, downloads: 2, rate: null }
  ]);
  const text = weeklyStatsText({ devices: 0, rows: 0, matches: 0, with_advice: 0, advice: {}, ignored: {}, versions: {}, channels: aggregateChannels(rows) });
  assert.match(text, /Sources \(visits → downloads\): search 50→10, pikabu 40→4, site 0→2/);
});

test("the cleanup drops source counts after a year", async () => {
  const env = fakeEnv();
  env.DB.counts.set("old|x", { day: isoDay(NOW - 400 * DAY), src: "x", visits: 1, downloads: 0 });
  env.DB.counts.set("new|y", { day: isoDay(NOW - 10 * DAY), src: "y", visits: 1, downloads: 0 });
  await cleanup(env, NOW);
  assert.deepEqual([...env.DB.counts.keys()], ["new|y"]);
});

test("a HEAD probe gets the redirect but is not counted as a download", async () => {
  const env = fakeEnv();
  resetInstallerCache();
  const realFetch = globalThis.fetch;
  globalThis.fetch = githubRedirect("v0.18.0");
  try {
    const probe = await worker.fetch(new Request("https://api.luhovyimvp.dev/d/pikabu", { method: "HEAD" }), env);
    assert.equal(probe.status, 302);
    assert.equal(env.DB.counts.size, 0);
    await worker.fetch(new Request("https://api.luhovyimvp.dev/d/pikabu"), env);
    assert.equal(env.DB.counts.get(`${isoDay(Date.now())}|pikabu`).downloads, 1);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("the admin range is the last N dates with today; the weekly note the 7 finished days", async () => {
  const env = fakeEnv({ TELEGRAM_BOT_TOKEN: "t", TELEGRAM_CHAT_ID: "1" });
  const now = Date.now();
  for (let back = 0; back <= 8; back += 1) {
    const day = isoDay(now - back * DAY);
    env.DB.counts.set(`${day}|d${back}`, { day, src: `d${back}`, visits: 1, downloads: 0 });
  }
  const admin = async (days) => {
    const response = await worker.fetch(
      new Request(`https://api.luhovyimvp.dev/v1/admin/stats?days=${days}`, { headers: { authorization: "Bearer secret" } }),
      env
    );
    return (await response.json()).stats.channels.map((c) => c.src).sort();
  };
  assert.deepEqual(await admin(1), ["d0"]);
  assert.deepEqual(await admin(7), ["d0", "d1", "d2", "d3", "d4", "d5", "d6"]);
  // Monday's note: the 7 finished days before it. The dates just outside have
  // the most visits, so they would lead the list if the range were wrong.
  const weekly = fakeEnv({ TELEGRAM_BOT_TOKEN: "t", TELEGRAM_CHAT_ID: "1" });
  const monday = now + ((8 - new Date(now).getUTCDay()) % 7) * DAY;
  const visits = { 0: 9, 1: 5, 7: 5, 8: 9 };
  for (let back = 0; back <= 8; back += 1) {
    const day = isoDay(monday - back * DAY);
    weekly.DB.counts.set(`${day}|m${back}`, { day, src: `m${back}`, visits: visits[back] || 1, downloads: 0 });
  }
  const sent = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (_url, init) => {
    sent.push(JSON.parse(init.body).text);
    return new Response("{}");
  };
  try {
    assert.equal(await sendWeeklyStats(weekly, monday), true);
  } finally {
    globalThis.fetch = realFetch;
  }
  const line = sent[0].split("\n").find((l) => l.startsWith("Sources"));
  assert.match(line, /^Sources \(visits → downloads\): m1 5→0, m7 5→0, m2 1→0/);
  assert.doesNotMatch(line, /m0|m8/);
});
