import assert from "node:assert/strict";
import test from "node:test";

import {
  BACKOFF_MS,
  MAX_BODY_BYTES,
  OPENDOTA_BATCH,
  REFRESH_MS,
  cacheEnabled,
  checkBody,
  entryFor,
  entryForRequest,
  heroEntries,
  heroIds,
  refreshOpenDotaCache,
  serveOpenDota
} from "../src/opendota-cache.js";
import worker from "../src/index.js";

const NOW = 1_800_000_000_000;
const quiet = (t) => {
  const original = console.log;
  console.log = () => {};
  t.after(() => {
    console.log = original;
  });
};

test("only the five OpenDota paths map to a key", () => {
  assert.deepEqual(entryFor("/heroStats"), { path: "/heroStats", key: "opendota/heroStats.json", expect: "array" });
  assert.equal(entryFor("/constants/items").key, "opendota/constants/items.json");
  assert.equal(entryFor("/heroes/1/matchups").key, "opendota/heroes/1/matchups.json");
  assert.equal(entryFor("/heroes/135/itemPopularity").expect, "object");
  assert.equal(entryFor("/scenarios/itemTimings?hero_id=7").key, "opendota/scenarios/itemTimings/7.json");
  for (const bad of [
    "/players/1",
    "/heroes/0/matchups",
    "/heroes/01/matchups",
    "/heroes/301/matchups",
    "/heroes/1/matches",
    "/heroes/1/matchups/x",
    "/heroes/../matchups",
    "/constants/abilities",
    "/scenarios/itemTimings",
    "/scenarios/itemTimings?hero_id=0",
    "/scenarios/itemTimings?hero_id=1&x=2",
    "/heroStats?x=1"
  ]) {
    assert.equal(entryFor(bad), null, bad);
  }
});

test("a request URL is mapped with the same whitelist", () => {
  const ask = (rest) => entryForRequest(new URL(`https://api.test/v1/opendota/${rest}`));
  assert.equal(ask("heroStats").key, "opendota/heroStats.json");
  assert.equal(ask("heroStats/").key, "opendota/heroStats.json");
  assert.equal(ask("scenarios/itemTimings?hero_id=12").path, "/scenarios/itemTimings?hero_id=12");
  assert.equal(ask("scenarios/itemTimings?hero_id=12&api_key=x"), null);
  assert.equal(ask("scenarios/itemTimings?hero_id=1&hero_id=2"), null);
  assert.equal(ask("scenarios/itemTimings?other=1"), null);
  assert.equal(ask("heroStats?api_key=x"), null);
  assert.equal(ask("players/1"), null);
  assert.equal(ask("heroes/1/matchups?x=1"), null);
  assert.equal(entryForRequest(new URL("https://api.test/v1/opendota")), null);
});

test("hero ids from heroStats become three entries each, only valid and unique", () => {
  assert.deepEqual(heroIds('[{"id":1},{"id":2},{"x":3},{"id":"4"}]'), [1, 2]);
  assert.deepEqual(heroIds("{}"), []);
  assert.deepEqual(heroIds("not json"), []);
  const rows = heroEntries([1, 1, 0, 999, 14]);
  assert.deepEqual(rows.map((row) => row.key), [
    "opendota/heroes/1/itemPopularity.json",
    "opendota/heroes/1/matchups.json",
    "opendota/scenarios/itemTimings/1.json",
    "opendota/heroes/14/itemPopularity.json",
    "opendota/heroes/14/matchups.json",
    "opendota/scenarios/itemTimings/14.json"
  ]);
});

test("a body is checked by status, size and first byte, without parsing", () => {
  const bytes = (text) => new TextEncoder().encode(text).buffer;
  assert.equal(checkBody(200, bytes("[1]"), "array").ok, true);
  assert.equal(checkBody(200, bytes("  \n{\"a\":1}"), "object").ok, true);
  assert.equal(checkBody(200, bytes("{}"), "array").ok, false);
  assert.equal(checkBody(200, bytes("[]"), "object").ok, false);
  assert.equal(checkBody(200, bytes("<html>"), "array").reason, "not json");
  assert.equal(checkBody(500, bytes("[]"), "array").reason, "HTTP 500");
  assert.equal(checkBody(200, bytes(""), "array").reason, "empty");
  assert.equal(checkBody(200, new ArrayBuffer(MAX_BODY_BYTES + 1), "array").reason, "too large");
  assert.equal(checkBody(200, null, "array").ok, false);
});

test("the kill switch reads like the other flags", () => {
  assert.equal(cacheEnabled({}), true);
  assert.equal(cacheEnabled({ OPENDOTA_CACHE_ENABLED: "true" }), true);
  for (const off of ["false", "0", "off", "no", "FALSE"]) {
    assert.equal(cacheEnabled({ OPENDOTA_CACHE_ENABLED: off }), false);
  }
});

// A D1 that records statements and answers the "due" select from a list.
function fakeEnv({ due = [], extra = {} } = {}) {
  const calls = { batches: [], puts: [] };
  const statement = (sql) => ({ sql, args: [], bind(...args) { this.args = args; return this; } });
  const DB = {
    prepare: statement,
    async batch(statements) {
      calls.batches.push(statements);
      return statements.map((s) => (s.sql.startsWith("SELECT") ? { results: due } : { results: [] }));
    }
  };
  const REPORTS = {
    async put(key, body, options) {
      if (extra.putFails) throw new Error("r2 down");
      calls.puts.push({ key, size: body.byteLength, options });
    }
  };
  return { env: { DB, REPORTS, ...extra.env }, calls };
}

function answers(map) {
  const seen = [];
  const fetchImpl = async (url, init) => {
    seen.push({ url: String(url), init });
    const hit = [...Object.entries(map)].find(([part]) => String(url).includes(part));
    const value = hit ? hit[1] : { status: 404, body: "" };
    if (value instanceof Error) throw value;
    return new Response(value.body, { status: value.status ?? 200, headers: value.headers });
  };
  return { fetchImpl, seen };
}

const row = (path) => ({ path, key: entryFor(path).key });

test("a run fetches the due entries, stores the raw body and records success in one batch", async () => {
  const { env, calls } = fakeEnv({ due: [row("/heroStats"), row("/constants/items"), row("/heroes/1/matchups")] });
  const { fetchImpl, seen } = answers({
    "/heroStats": { body: '[{"id":1},{"id":2}]' },
    "/constants/items": { body: '{"blink":{}}' },
    "/heroes/1/matchups": { body: "[]" }
  });
  const result = await refreshOpenDotaCache(env, NOW, fetchImpl);
  assert.deepEqual([result.fetched, result.failed, result.stopped], [3, 0, false]);
  assert.deepEqual(calls.puts.map((p) => p.key), ["opendota/heroStats.json", "opendota/constants/items.json", "opendota/heroes/1/matchups.json"]);
  assert.equal(calls.puts[0].size, 19);
  assert.equal(calls.puts[0].options.customMetadata.fetched_at, String(NOW));
  assert.match(seen[0].init.headers["user-agent"], /Wardly/);
  assert.ok(seen[0].init.signal);
  // First batch: seed + due select. Second: three updates and the hero rows from heroStats.
  assert.equal(calls.batches.length, 2);
  assert.match(calls.batches[0][0].sql, /INSERT OR IGNORE/);
  assert.deepEqual(calls.batches[0][1].args, [NOW - REFRESH_MS, NOW, OPENDOTA_BATCH]);
  const writes = calls.batches[1];
  assert.equal(writes.length, 4);
  const heroes = writes.find((w) => w.sql.startsWith("INSERT"));
  assert.equal(JSON.parse(heroes.args[0]).length, 6);
});

test("the seed rows are the two global entries", async () => {
  const { env, calls } = fakeEnv();
  await refreshOpenDotaCache(env, NOW, answers({}).fetchImpl);
  assert.deepEqual(JSON.parse(calls.batches[0][0].args[0]), [
    ["opendota/heroStats.json", "/heroStats"],
    ["opendota/constants/items.json", "/constants/items"]
  ]);
  assert.equal(calls.batches.length, 1, "nothing due: no second batch");
});

test("a 429 stops the run and keeps what was already stored", async (t) => {
  quiet(t);
  const { env, calls } = fakeEnv({ due: [row("/heroStats"), row("/constants/items"), row("/heroes/1/matchups")] });
  const { fetchImpl, seen } = answers({ "/heroStats": { body: "[]" }, "/constants/items": { status: 429 } });
  const result = await refreshOpenDotaCache(env, NOW, fetchImpl);
  assert.deepEqual([result.fetched, result.failed, result.stopped], [1, 0, true]);
  assert.equal(seen.length, 2, "the third entry is not asked");
  assert.equal(calls.batches[1].length, 1);
});

test("failures are marked for backoff and do not touch the older object", async (t) => {
  quiet(t);
  const { env, calls } = fakeEnv({ due: [row("/heroes/1/matchups"), row("/heroes/2/matchups"), row("/heroes/3/matchups"), row("/heroes/4/matchups")] });
  const { fetchImpl } = answers({
    "/heroes/1/": { status: 500, body: "oops" },
    "/heroes/2/": { body: "<html>" },
    "/heroes/3/": new Error("fetch failed"),
    "/heroes/4/": { body: "[1]" }
  });
  const result = await refreshOpenDotaCache(env, NOW, fetchImpl);
  assert.deepEqual([result.fetched, result.failed], [1, 3]);
  assert.deepEqual(calls.puts.map((p) => p.key), ["opendota/heroes/4/matchups.json"]);
  const fails = calls.batches[1].filter((w) => w.sql.includes("fails = fails + 1"));
  assert.equal(fails.length, 3);
  assert.deepEqual(fails[0].args, ["opendota/heroes/1/matchups.json", NOW]);
});

test("an R2 failure counts as a failed refresh", async (t) => {
  quiet(t);
  const { env, calls } = fakeEnv({ due: [row("/constants/items")], extra: { putFails: true } });
  const result = await refreshOpenDotaCache(env, NOW, answers({ "/constants/items": { body: "{}" } }).fetchImpl);
  assert.deepEqual([result.fetched, result.failed], [0, 1]);
  assert.ok(calls.batches[1][0].sql.includes("fails = fails + 1"));
});

test("the backoff and the due order are in the select", async () => {
  const { env, calls } = fakeEnv();
  await refreshOpenDotaCache(env, NOW, answers({}).fetchImpl);
  const sql = calls.batches[0][1].sql;
  assert.match(sql, new RegExp(`failed_at \\+ ${BACKOFF_MS} \\* MIN\\(MAX\\(fails, 1\\), 6\\) <= \\?2`));
  assert.match(sql, /ORDER BY \(path IN \('\/heroStats', '\/constants\/items'\)\) DESC, fetched_at ASC/);
});

test("rows outside the whitelist are never fetched", async () => {
  const { env } = fakeEnv({ due: [{ key: "opendota/players/1.json", path: "/players/1" }, { key: "x", path: "/heroes/1/matchups" }] });
  const { fetchImpl, seen } = answers({});
  const result = await refreshOpenDotaCache(env, NOW, fetchImpl);
  assert.equal(seen.length, 0);
  assert.equal(result.fetched + result.failed, 0);
});

test("the kill switch and a missing bucket do nothing at all", async () => {
  const { env, calls } = fakeEnv({ extra: { env: { OPENDOTA_CACHE_ENABLED: "false" } } });
  assert.equal((await refreshOpenDotaCache(env, NOW, answers({}).fetchImpl)).skipped, "disabled");
  const none = fakeEnv();
  delete none.env.REPORTS;
  assert.equal((await refreshOpenDotaCache(none.env, NOW, answers({}).fetchImpl)).skipped, "no_storage");
  assert.equal(calls.batches.length + none.calls.batches.length, 0);
});

test("the optional API key goes only to OpenDota and never into the log", async (t) => {
  const lines = [];
  const original = console.log;
  console.log = (...args) => lines.push(args.join(" "));
  t.after(() => {
    console.log = original;
  });
  const { env } = fakeEnv({ due: [row("/heroes/1/matchups"), row("/scenarios/itemTimings?hero_id=1")], extra: { env: { OPENDOTA_API_KEY: "SECRET-KEY-123" } } });
  const { fetchImpl, seen } = answers({ "/heroes/1/matchups": { status: 500 }, "itemTimings": new Error("fetch failed https://x?api_key=SECRET-KEY-123") });
  await refreshOpenDotaCache(env, NOW, fetchImpl);
  assert.ok(seen.every((s) => s.url.startsWith("https://api.opendota.com/api/") && s.url.includes("api_key=SECRET-KEY-123")));
  assert.ok(seen[1].url.includes("hero_id=1"));
  assert.ok(!lines.join("\n").includes("SECRET-KEY-123"));
});

test("a run stops starting new fetches after its time budget", async () => {
  const { env } = fakeEnv({ due: [row("/heroes/1/matchups"), row("/heroes/2/matchups")] });
  const { fetchImpl, seen } = answers({ "/heroes/": { body: "[]" } });
  let time = 0;
  const clock = () => {
    time += 3 * 60_000;
    return time;
  };
  await refreshOpenDotaCache(env, NOW, fetchImpl, clock);
  assert.equal(seen.length, 1);
});

// --- the route ---

function bucket(objects) {
  return {
    async get(key) {
      const hit = objects[key];
      return hit ? { body: new Response(hit.body).body, customMetadata: { fetched_at: String(hit.at) } } : null;
    }
  };
}

function memoryCache() {
  const store = new Map();
  return {
    store,
    async match(request) {
      return store.get(request.url)?.clone();
    },
    async put(request, response) {
      store.set(request.url, response);
    }
  };
}

const ctx = () => {
  const tasks = [];
  return { tasks, waitUntil: (p) => tasks.push(p) };
};

const get = (rest, method = "GET") => new Request(`https://api.test/v1/opendota/${rest}`, { method });

test("the route answers the stored body with its age, then serves it from the Cache API", async () => {
  const cache = memoryCache();
  const env = { REPORTS: bucket({ "opendota/heroes/5/matchups.json": { body: '[{"hero_id":1}]', at: NOW } }) };
  const first = ctx();
  const response = await serveOpenDota(get("heroes/5/matchups"), env, first, { cache });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
  assert.equal(response.headers.get("x-fetched-at"), String(NOW));
  assert.equal(response.headers.get("cache-control"), "public, max-age=3600");
  assert.equal(await response.text(), '[{"hero_id":1}]');
  await Promise.all(first.tasks);
  assert.equal(cache.store.size, 1);
  // Served from the cache: R2 is not asked.
  const second = await serveOpenDota(get("heroes/5/matchups"), { REPORTS: { get: () => assert.fail("R2 read") } }, ctx(), { cache });
  assert.equal(await second.text(), '[{"hero_id":1}]');
});

test("HEAD has headers and no body; other methods are refused", async () => {
  const env = { REPORTS: bucket({ "opendota/heroStats.json": { body: "[]", at: 5 } }) };
  const head = await serveOpenDota(get("heroStats", "HEAD"), env, ctx(), { cache: null });
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("x-fetched-at"), "5");
  assert.equal(await head.text(), "");
  const post = await serveOpenDota(get("heroStats", "POST"), env, ctx(), { cache: null });
  assert.equal(post.status, 405);
});

test("not whitelisted is 404 not_found, missing is 404 not_cached, no bucket is 503, switched off is 503", async () => {
  const env = { REPORTS: bucket({}) };
  const code = async (response) => [response.status, (await response.json()).code];
  assert.deepEqual(await code(await serveOpenDota(get("players/1"), env, ctx(), { cache: null })), [404, "not_found"]);
  assert.deepEqual(await code(await serveOpenDota(get("heroes/9/matchups"), env, ctx(), { cache: null })), [404, "not_cached"]);
  assert.deepEqual(await code(await serveOpenDota(get("heroStats"), {}, ctx(), { cache: null })), [503, "storage_unavailable"]);
  assert.deepEqual(
    await code(await serveOpenDota(get("heroStats"), { ...env, OPENDOTA_CACHE_ENABLED: "false" }, ctx(), { cache: null })),
    [503, "disabled"]
  );
});

test("a broken Cache API does not break the route", async () => {
  const env = { REPORTS: bucket({ "opendota/constants/items.json": { body: "{}", at: 1 } }) };
  const cache = {
    match: async () => {
      throw new Error("cache down");
    },
    put: async () => {
      throw new Error("cache down");
    }
  };
  const c = ctx();
  const response = await serveOpenDota(get("constants/items"), env, c, { cache });
  assert.equal(await response.text(), "{}");
  await Promise.all(c.tasks);
});

test("the Worker routes /v1/opendota/ to the cache", async () => {
  const env = { REPORTS: bucket({ "opendota/heroStats.json": { body: "[]", at: 7 } }) };
  const response = await worker.fetch(get("heroStats"), env, ctx());
  assert.equal(response.status, 200);
  assert.equal((await worker.fetch(get("nothing"), env, ctx())).status, 404);
});
