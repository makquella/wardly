// Match recordings on the actual Worker, workerd D1 with every migration and
// a real R2 bucket: upload, the index row, admin download, the device delete
// and the 60-day cleanup (src/session.js, migrations/0010_sessions.sql).
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { gzipSync } from "node:zlib";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const SOURCE = path.join(ROOT, "src");
const MINE = "12345678-1234-4123-8123-123456789abc";
const KEY = "a".repeat(64);
const ADMIN = { authorization: "Bearer t0ken" };

async function localWorker(t) {
  const paths = (await readdir(SOURCE, { recursive: true })).filter((name) => name.endsWith(".js") && name !== "index.js");
  const modules = ["index.js", ...paths].map((name) => ({ type: "ESModule", path: path.join(SOURCE, name) }));
  const mf = new Miniflare(convertV4MiniflareOptions({
    modules,
    modulesRoot: ROOT,
    compatibilityDate: "2026-09-20",
    bindings: { ADMIN_TOKEN: "t0ken" },
    d1Databases: { DB: "wardly-sessions-integration" },
    r2Buckets: ["REPORTS"],
  }));
  t.after(() => mf.dispose());
  const db = await mf.getD1Database("DB");
  for (const file of (await readdir(path.join(ROOT, "migrations"))).filter((name) => name.endsWith(".sql")).sort()) {
    const sql = await readFile(path.join(ROOT, "migrations", file), "utf8");
    for (const statement of sql.replace(/--[^\n]*/g, "").split(";").map((part) => part.trim()).filter(Boolean)) {
      await db.prepare(statement).run();
    }
  }
  return { mf, db, bucket: await mf.getR2Bucket("REPORTS") };
}

function recording() {
  const meta = { k: "meta", hero: "npc_dota_hero_juggernaut", payloads: 1, advice: 0, last_clock: 90, format: 1, upload: 1, anonymized: true };
  const rows = [JSON.stringify(meta), JSON.stringify({ k: "gsi", w: 0, ts: "+0.000", p: { map: { clock_time: 90 } } })];
  return new Uint8Array(gzipSync(Buffer.from(`${rows.join("\n")}\n`)));
}

function upload(mf, body, key = KEY) {
  return mf.dispatchFetch("https://local.test/v1/session", {
    method: "POST",
    headers: {
      "content-type": "application/gzip",
      "cf-connecting-ip": "198.51.100.1",
      "x-install-id": MINE,
      "x-app-version": "0.63.0",
      "x-hero": "npc_dota_hero_juggernaut",
      "x-minutes": "1",
      ...(key ? { "x-device-key": key } : {}),
    },
    body,
  });
}

test("a recording is stored in R2, indexed, downloadable by the developer and deletable by its owner", async (t) => {
  const { mf, db, bucket } = await localWorker(t);
  const bytes = recording();
  const response = await upload(mf, bytes);
  assert.equal(response.status, 201);
  const { id } = await response.json();
  const row = await db.prepare("SELECT * FROM sessions WHERE id = ?1").bind(id).first();
  assert.equal("install_id" in row, false);
  assert.match(row.owner_hash, /^[a-f0-9]{32}$/);
  assert.match(row.install_hash, /^[a-f0-9]{32}$/);
  assert.ok(!JSON.stringify(row).includes(MINE));
  assert.equal(row.size, bytes.length);
  assert.ok(["tune", "holdout"].includes(row.split));
  assert.equal((await bucket.list()).objects.length, 1);

  const list = await (await mf.dispatchFetch(`https://local.test/v1/admin/sessions?split=${row.split}`, { headers: ADMIN })).json();
  assert.equal(list.sessions[0].id, id);
  const file = await mf.dispatchFetch(`https://local.test/v1/admin/session/${id}`, { headers: ADMIN });
  assert.deepEqual([...new Uint8Array(await file.arrayBuffer())], [...bytes]);
  assert.equal((await mf.dispatchFetch(`https://local.test/v1/admin/session/${id}`)).status, 404);

  const wrong = await mf.dispatchFetch(`https://local.test/v1/device/${MINE}`, { method: "DELETE", headers: { "x-device-key": "b".repeat(64) } });
  assert.equal(wrong.status, 200);
  assert.equal((await bucket.list()).objects.length, 1, "a wrong key removes nothing");
  await mf.dispatchFetch(`https://local.test/v1/device/${MINE}`, { method: "DELETE", headers: { "x-device-key": KEY } });
  assert.equal((await bucket.list()).objects.length, 0);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM sessions").first()).n, 0);
});

test("the daily cleanup removes recordings older than 60 days, object and row", async (t) => {
  const { mf, db, bucket } = await localWorker(t);
  const old = Date.now() - 61 * 24 * 3_600_000;
  await bucket.put("sessions/2026/01/S-OLDAAA.jsonl.gz", recording());
  await bucket.put("sessions/2026/11/S-NEWAAA.jsonl.gz", recording());
  for (const [id, at] of [["S-OLDAAA", old], ["S-NEWAAA", Date.now()]]) {
    await db
      .prepare("INSERT INTO sessions (id, created_at, owner_hash, r2_key, split) VALUES (?1, ?2, ?3, ?4, 'tune')")
      .bind(id, at, "owner", `sessions/${id === "S-OLDAAA" ? "2026/01" : "2026/11"}/${id}.jsonl.gz`)
      .run();
  }
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: "17 3 * * *" });
  assert.deepEqual((await bucket.list()).objects.map((o) => o.key), ["sessions/2026/11/S-NEWAAA.jsonl.gz"]);
  assert.deepEqual((await db.prepare("SELECT id FROM sessions").all()).results.map((r) => r.id), ["S-NEWAAA"]);
});

test("a recording that names a match id is refused by the real Worker", async (t) => {
  const { mf, db } = await localWorker(t);
  const meta = { k: "meta", anonymized: true, matchid: "8012345678" };
  const bytes = new Uint8Array(gzipSync(Buffer.from(`${JSON.stringify(meta)}\n`.repeat(3))));
  const response = await upload(mf, bytes);
  assert.equal(response.status, 422);
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM sessions").first()).n, 0);
});

test("without a device key the real Worker refuses the recording", async (t) => {
  const { mf, db, bucket } = await localWorker(t);
  const response = await upload(mf, recording(), null);
  assert.equal(response.status, 400);
  assert.equal((await response.json()).code, "no_device_key");
  assert.equal((await db.prepare("SELECT COUNT(*) AS n FROM sessions").first()).n, 0);
  assert.equal((await bucket.list()).objects.length, 0);
});
