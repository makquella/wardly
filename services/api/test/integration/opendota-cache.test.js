// The OpenDota cache on the actual Worker: workerd D1 with every migration, a
// real R2 bucket and the Cache API; only api.opendota.com is replaced by a
// local answer (src/opendota-cache.js, migrations/0011_opendota_cache.sql).
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const SOURCE = path.join(ROOT, "src");
const CRON = "*/5 * * * *";
const DAY = 24 * 3_600_000;

async function localWorker(t, { opendota, bindings = {} } = {}) {
  const asked = [];
  const paths = (await readdir(SOURCE, { recursive: true })).filter((name) => name.endsWith(".js") && name !== "index.js");
  const modules = ["index.js", ...paths].map((name) => ({ type: "ESModule", path: path.join(SOURCE, name) }));
  const mf = new Miniflare(convertV4MiniflareOptions({
    modules,
    modulesRoot: ROOT,
    compatibilityDate: "2026-09-20",
    bindings,
    d1Databases: { DB: "wardly-opendota-integration" },
    r2Buckets: ["REPORTS"],
    outboundService: async (request) => {
      const url = new URL(request.url);
      if (url.hostname !== "api.opendota.com") {
        return new Response("", { status: 599 });
      }
      asked.push(`${url.pathname.replace("/api", "")}${url.search}`);
      return opendota(url) || new Response("not found", { status: 404 });
    },
  }));
  t.after(() => mf.dispose());
  const db = await mf.getD1Database("DB");
  for (const file of (await readdir(path.join(ROOT, "migrations"))).filter((name) => name.endsWith(".sql")).sort()) {
    const sql = await readFile(path.join(ROOT, "migrations", file), "utf8");
    for (const statement of sql.replace(/--[^\n]*/g, "").split(";").map((part) => part.trim()).filter(Boolean)) {
      await db.prepare(statement).run();
    }
  }
  return { mf, db, asked, bucket: await mf.getR2Bucket("REPORTS") };
}

const answer = (url) => {
  if (url.pathname.endsWith("/heroStats")) return Response.json([{ id: 1 }, { id: 2 }, { id: 0 }, { id: 500 }]);
  if (url.pathname.endsWith("/constants/items")) return Response.json({ blink: { id: 1 } });
  if (url.pathname.endsWith("/itemPopularity")) return Response.json({ start_game_items: {} });
  return Response.json([]);
};

const rows = async (db) => (await db.prepare("SELECT * FROM opendota_cache ORDER BY key").all()).results;

test("the first run seeds the two global entries, fetches them and adds the hero rows", async (t) => {
  const { mf, db, bucket, asked } = await localWorker(t, { opendota: answer });
  await (await mf.getWorker()).scheduled({ cron: CRON });
  assert.deepEqual(asked.sort(), ["/constants/items", "/heroStats"]);
  const all = await rows(db);
  // 2 global + 3 for each of heroes 1 and 2; ids 0 and 500 are not whitelisted.
  assert.equal(all.length, 8);
  const stats = all.find((r) => r.path === "/heroStats");
  assert.ok(stats.fetched_at > 0 && stats.size > 0 && stats.fails === 0 && stats.failed_at === null);
  assert.equal(all.filter((r) => r.fetched_at === 0).length, 6);
  assert.deepEqual((await bucket.list({ prefix: "opendota/" })).objects.map((o) => o.key).sort(), ["opendota/constants/items.json", "opendota/heroStats.json"]);
  assert.equal(await (await bucket.get("opendota/constants/items.json")).text(), '{"blink":{"id":1}}');
});

test("the next runs take the never-fetched entries, 8 at most, and a fresh entry waits a day", async (t) => {
  const { mf, db, bucket, asked } = await localWorker(t, { opendota: answer });
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: CRON });
  asked.length = 0;
  await worker.scheduled({ cron: CRON });
  assert.equal(asked.length, 6, "six hero rows were left, the two global ones are fresh");
  assert.ok(asked.includes("/scenarios/itemTimings?hero_id=2"));
  assert.ok((await rows(db)).every((r) => r.fetched_at > 0));
  assert.equal(await (await bucket.get("opendota/scenarios/itemTimings/1.json")).text(), "[]");
  asked.length = 0;
  await worker.scheduled({ cron: CRON });
  assert.equal(asked.length, 0);
  // A day later the oldest come first, global entries before everything else.
  const old = Date.now() - 2 * DAY;
  await db.prepare("UPDATE opendota_cache SET fetched_at = ?1 WHERE path NOT IN ('/heroStats', '/constants/items')").bind(old - 1000).run();
  await db.prepare("UPDATE opendota_cache SET fetched_at = ?1 WHERE path = '/heroStats'").bind(old).run();
  await worker.scheduled({ cron: CRON });
  assert.equal(asked[0], "/heroStats");
  assert.equal(asked.length, 7, "items are still fresh");
});

test("a failed entry backs off for an hour per failure in a row and keeps its older object", async (t) => {
  let fail = false;
  const { mf, db, bucket, asked } = await localWorker(t, { opendota: (url) => (fail && url.pathname.endsWith("/constants/items") ? new Response("no", { status: 500 }) : answer(url)) });
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: CRON });
  const old = Date.now() - 2 * DAY;
  await db.prepare("UPDATE opendota_cache SET fetched_at = ?1 WHERE path = '/constants/items'").bind(old).run();
  fail = true;
  asked.length = 0;
  await worker.scheduled({ cron: CRON });
  assert.ok(asked.includes("/constants/items"));
  let items = (await rows(db)).find((r) => r.path === "/constants/items");
  assert.equal(items.fails, 1);
  assert.equal(items.fetched_at, old, "the last success is untouched");
  assert.equal(await (await bucket.get("opendota/constants/items.json")).text(), '{"blink":{"id":1}}');
  asked.length = 0;
  await worker.scheduled({ cron: CRON });
  assert.ok(!asked.includes("/constants/items"), "no new try within the hour");
  await db.prepare("UPDATE opendota_cache SET failed_at = ?1 WHERE path = '/constants/items'").bind(Date.now() - 2 * 3_600_000).run();
  fail = false;
  await worker.scheduled({ cron: CRON });
  assert.ok(asked.includes("/constants/items"));
  items = (await rows(db)).find((r) => r.path === "/constants/items");
  assert.deepEqual([items.fails, items.failed_at], [0, null]);
  assert.ok(items.fetched_at > old);
});

test("OpenDota's 429 ends the run and the API key goes only to OpenDota", async (t) => {
  const { mf, db, asked } = await localWorker(t, {
    opendota: (url) => (url.pathname.endsWith("/heroStats") ? new Response("slow down", { status: 429 }) : answer(url)),
    bindings: { OPENDOTA_API_KEY: "key-for-opendota" }
  });
  await (await mf.getWorker()).scheduled({ cron: CRON });
  assert.deepEqual(asked, ["/constants/items?api_key=key-for-opendota", "/heroStats?api_key=key-for-opendota"], "items, then the 429 on heroStats");
  const all = await rows(db);
  assert.equal(all.length, 2, "no hero rows without a heroStats");
  assert.equal(all.find((r) => r.path === "/heroStats").fails, 0, "a 429 is not the entry's fault");
  assert.ok(all.find((r) => r.path === "/constants/items").fetched_at > 0);
  const served = await mf.dispatchFetch("https://local.test/v1/opendota/heroStats");
  assert.ok(!JSON.stringify([...served.headers]).includes("key-for-opendota"));
});

test("the route serves the stored body with its age and nothing outside the whitelist", async (t) => {
  const { mf, bucket } = await localWorker(t, { opendota: answer });
  await (await mf.getWorker()).scheduled({ cron: CRON });
  const response = await mf.dispatchFetch("https://local.test/v1/opendota/constants/items");
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "public, max-age=3600");
  assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
  assert.ok(Number(response.headers.get("x-fetched-at")) > Date.now() - 60_000);
  assert.deepEqual(await response.json(), { blink: { id: 1 } });
  assert.equal((await mf.dispatchFetch("https://local.test/v1/opendota/heroes/1/matchups")).status, 404, "listed but not fetched yet");
  assert.equal((await mf.dispatchFetch("https://local.test/v1/opendota/players/1")).status, 404);
  assert.equal((await mf.dispatchFetch("https://local.test/v1/opendota/heroStats", { method: "POST", body: "x" })).status, 405);
  assert.equal((await mf.dispatchFetch("https://local.test/v1/opendota/heroStats", { method: "HEAD" })).status, 200);
  // Replaced in R2, the Cache API still answers the hour-old copy.
  await bucket.put("opendota/constants/items.json", '{"changed":true}', { customMetadata: { fetched_at: "1" } });
  assert.deepEqual(await (await mf.dispatchFetch("https://local.test/v1/opendota/constants/items")).json(), { blink: { id: 1 } });
});

test("the kill switch stops the refresh and the route", async (t) => {
  const { mf, asked } = await localWorker(t, { opendota: answer, bindings: { OPENDOTA_CACHE_ENABLED: "false" } });
  await (await mf.getWorker()).scheduled({ cron: CRON });
  assert.equal(asked.length, 0);
  assert.equal((await mf.dispatchFetch("https://local.test/v1/opendota/heroStats")).status, 503);
});
