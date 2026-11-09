import assert from "node:assert/strict";
import test from "node:test";

import worker, { cleanup, config, versionAtLeast } from "../src/index.js";
import { RATE_PER_HOUR, redact, reportId, summarize, validateReport } from "../src/report.js";
import { siteHome } from "../src/share.js";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { gzipSync } from "node:zlib";
import { ADMIN_JS } from "../src/admin-page.js";
import { renderProfilePage } from "../src/profile.js";

// In-memory stand-ins for the D1 and R2 bindings, for the statements the Worker uses.
function fakeEnv(vars = {}, { r2 = true } = {}) {
  const reports = [];
  const shares = [];
  const transfers = [];
  const profiles = [];
  const sessions = [];
  const daily = new Map();
  const rate = new Map();
  const objects = new Map();
  // OWNED in src/index.js: the key's rows, or this install's rows without an owner.
  const owned = (row, installId, owner) => row.owner_hash === owner || (row.install_id === installId && row.owner_hash == null);
  const dropOwned = (list) => list.splice(0, list.length, ...list.filter((r) => !owned(r, ownedArgs[0], ownedArgs[1])));
  let ownedArgs = [];
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
          if (sql.startsWith("SELECT COALESCE(SUM(CASE WHEN created_at >=")) {
            const sum = (rows) => rows.reduce((total, r) => total + Number(r.size || 0), 0);
            return { day: sum(sessions.filter((r) => r.created_at >= args[0])), total: sum(sessions) };
          }
          if (sql.startsWith("SELECT r2_key FROM sessions WHERE id")) {
            return sessions.find((r) => r.id === args[0]) || null;
          }
          if (sql.startsWith("SELECT r2_key, body FROM reports WHERE id")) {
            return reports.find((r) => r.id === args[0]) || null;
          }
          if (sql.startsWith("SELECT body, expires_at, lang FROM shares WHERE id") || sql.startsWith("SELECT delete_hash FROM shares WHERE id")) {
            return shares.find((r) => r.id === args[0]) || null;
          }
          if (sql.startsWith("SELECT token_hash FROM profiles WHERE id") || sql.startsWith("SELECT body FROM profiles WHERE id")) {
            return profiles.find((r) => r.id === args[0]) || null;
          }
          if (sql.startsWith("INSERT INTO transfers")) {
            const [id, created_at, expires_at, install_id, size, body, owner_hash = null, delete_hash = null] = args;
            if (transfers.some((row) => row.id === id)) return null;
            transfers.push({ id, created_at, expires_at, install_id, size, tries: 0, body: [...body], owner_hash, delete_hash });
            return { id };
          }
          if (sql.startsWith("SELECT 1 AS kept FROM transfers WHERE id")) {
            return transfers.some((r) => r.id === args[0]) ? { kept: 1 } : null;
          }
          if (sql.startsWith("UPDATE transfers SET tries")) {
            const row = transfers.find((r) => r.id === args[0] && r.tries < args[1] && r.expires_at >= args[2]);
            if (!row) return null;
            row.tries += 1;
            return { body: [...row.body], tries: row.tries };
          }
          throw new Error(`unexpected first(): ${sql}`);
        },
        async all() {
          if (sql.startsWith("SELECT id, updated_at, body FROM profiles WHERE id IN")) {
            return { results: profiles.filter((r) => args.includes(r.id)) };
          }
          if (sql.startsWith("SELECT r2_key FROM sessions WHERE owner_hash = ?1")) {
            return { results: sessions.filter((r) => r.owner_hash === args[0]) };
          }
          if (sql.startsWith("SELECT id, r2_key FROM sessions WHERE created_at <")) {
            const limit = Number(sql.match(/LIMIT (\d+)/)[1]);
            return { results: sessions.filter((r) => r.created_at < args[0]).slice(0, limit) };
          }
          if (sql.startsWith("SELECT id, created_at, version, hero, minutes, size, split FROM sessions")) {
            const rows = sql.includes("WHERE split = ?1") ? sessions.filter((r) => r.split === args[0]) : sessions;
            const columns = ["id", "created_at", "version", "hero", "minutes", "size", "split"];
            return { results: [...rows].reverse().slice(0, 200).map((r) => Object.fromEntries(columns.map((c) => [c, r[c]]))) };
          }
          if (sql.startsWith("SELECT r2_key FROM reports WHERE (owner_hash")) {
            return { results: reports.filter((r) => owned(r, args[0], args[1])) };
          }
          if (sql.startsWith("SELECT id, r2_key FROM reports WHERE created_at <")) {
            const limit = Number(sql.match(/LIMIT (\d+)/)[1]);
            return { results: reports.filter((r) => r.created_at < args[0]).slice(0, limit) };
          }
          if (sql.startsWith("SELECT install_hash, day")) {
            return { results: [...daily.values()].filter((r) => r.day >= args[0]) };
          }
          if (sql.startsWith("SELECT id, created_at")) {
            return { results: [...reports].reverse() };
          }
          throw new Error(`unexpected all(): ${sql}`);
        },
        async run() {
          ownedArgs = args;
          if (/^DELETE FROM (reports|shares|transfers|profiles) WHERE \(owner_hash/.test(sql)) {
            dropOwned({ reports, shares, transfers, profiles }[sql.split(" ")[2]]);
          } else if (sql.startsWith("DELETE FROM sessions WHERE owner_hash = ?1")) {
            sessions.splice(0, sessions.length, ...sessions.filter((r) => r.owner_hash !== args[0]));
          } else if (sql.startsWith("DELETE FROM sessions WHERE id = ?1")) {
            sessions.splice(0, sessions.length, ...sessions.filter((r) => r.id !== args[0]));
          } else if (sql.startsWith("INSERT INTO sessions")) {
            const [id, created_at, owner_hash, install_hash, version, hero, minutes, size, r2_key, split] = args;
            if (sessions.some((r) => r.id === id)) throw new Error("UNIQUE constraint failed: sessions.id");
            sessions.push({ id, created_at, owner_hash, install_hash, version, hero, minutes, size, r2_key, split });
          } else if (sql.startsWith("DELETE FROM sessions WHERE id IN")) {
            sessions.splice(0, sessions.length, ...sessions.filter((r) => !args.includes(r.id)));
          } else if (sql.startsWith("INSERT INTO shares")) {
            const [id, created_at, expires_at, install_id, delete_hash, lang, version, body, owner_hash = null] = args;
            shares.push({ id, created_at, expires_at, install_id, delete_hash, lang, version, body: [...body], owner_hash });
          } else if (sql.startsWith("DELETE FROM shares WHERE id")) {
            shares.splice(0, shares.length, ...shares.filter((r) => r.id !== args[0]));
          } else if (sql.startsWith("DELETE FROM shares WHERE install_id")) {
            shares.splice(0, shares.length, ...shares.filter((r) => r.install_id !== args[0]));
          } else if (sql.startsWith("DELETE FROM shares WHERE expires_at")) {
            shares.splice(0, shares.length, ...shares.filter((r) => r.expires_at >= args[0]));
          } else if (sql.startsWith("INSERT INTO profiles")) {
            const [id, created_at, install_id, token_hash, version, body, owner_hash = null] = args;
            profiles.push({ id, created_at, updated_at: created_at, install_id, token_hash, version, body, owner_hash });
          } else if (sql.startsWith("UPDATE profiles SET updated_at")) {
            const row = profiles.find((r) => r.id === args[0]);
            Object.assign(row, { updated_at: args[1], version: args[2], body: args[3], owner_hash: row.owner_hash ?? args[4] ?? null });
          } else if (sql.startsWith("DELETE FROM profiles WHERE id")) {
            profiles.splice(0, profiles.length, ...profiles.filter((r) => r.id !== args[0]));
          } else if (sql.startsWith("DELETE FROM profiles WHERE install_id")) {
            profiles.splice(0, profiles.length, ...profiles.filter((r) => r.install_id !== args[0]));
          } else if (sql.startsWith("DELETE FROM profiles WHERE updated_at <")) {
            profiles.splice(0, profiles.length, ...profiles.filter((r) => r.updated_at >= args[0]));
          } else if (sql.startsWith("DELETE FROM transfers WHERE id")) {
            transfers.splice(0, transfers.length, ...transfers.filter((r) => {
              if (r.id !== args[0]) return true;
              if (sql.includes("expires_at <")) return !(r.expires_at < args[1] || r.tries >= args[2]);
              if (sql.includes("tries >=")) return r.tries < args[1];
              if (sql.includes("delete_hash IS NULL")) return !(r.delete_hash == null || r.delete_hash === args[1]);
              return false;
            }));
          } else if (sql.startsWith("DELETE FROM transfers WHERE install_id")) {
            transfers.splice(0, transfers.length, ...transfers.filter((r) => r.install_id !== args[0]));
          } else if (sql.startsWith("DELETE FROM transfers WHERE expires_at")) {
            transfers.splice(0, transfers.length, ...transfers.filter((r) => r.expires_at >= args[0]));
          } else if (sql.startsWith("INSERT INTO daily_stats")) {
            const [install_hash, day, created_at, version, body] = args;
            daily.set(`${install_hash}|${day}`, { install_hash, day, created_at, version, body });
          } else if (sql.startsWith("DELETE FROM daily_stats WHERE install_hash")) {
            for (const [key, row] of [...daily]) if (row.install_hash === args[0]) daily.delete(key);
          } else if (sql.startsWith("DELETE FROM daily_stats WHERE day <")) {
            for (const [key, row] of [...daily]) if (row.day < args[0]) daily.delete(key);
          } else if (sql.startsWith("DELETE FROM channel_counts WHERE day <")) {
            // Source counts (test/channels.test.js) are not kept by this fake.
          } else if (sql.startsWith("INSERT INTO reports")) {
            const [id, created_at, install_id, version, os, lang, size, summary, r2_key, body, owner_hash = null] = args;
            // D1 returns a BLOB as an array of bytes.
            const blob = body ? [...body] : null;
            reports.push({ id, created_at, install_id, version, os, lang, size, summary, r2_key, body: blob, owner_hash });
          } else if (sql.startsWith("DELETE FROM reports WHERE install_id")) {
            reports.splice(0, reports.length, ...reports.filter((r) => r.install_id !== args[0]));
          } else if (sql.startsWith("DELETE FROM reports WHERE id IN")) {
            reports.splice(0, reports.length, ...reports.filter((r) => !args.includes(r.id)));
          } else if (sql.startsWith("DELETE FROM rate")) {
            for (const key of [...rate.keys()]) {
              if (Number(key.split("|")[1]) < args[0]) rate.delete(key);
            }
          } else {
            throw new Error(`unexpected run(): ${sql}`);
          }
          return { success: true };
        }
      };
      return stmt;
    }
  };
  const REPORTS = {
    async put(key, body, options) {
      if (vars.FAIL_PUT) throw new Error("R2 is down");
      objects.set(key, { body, options });
    },
    async get(key) {
      const object = objects.get(key);
      return object ? { body: new Blob([object.body]).stream() } : null;
    },
    async delete(keys) {
      for (const key of [].concat(keys)) objects.delete(key);
    }
  };
  return { env: { DB, ...(r2 ? { REPORTS } : {}), ...vars }, reports, sessions, shares, transfers, profiles, objects, daily };
}

const ctx = { waitUntil: (promise) => promise };

function upload(body, ip = "203.0.113.5") {
  return new Request("https://api.example/v1/report", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": ip },
    body: typeof body === "string" ? body : JSON.stringify(body)
  });
}

const REPORT = {
  install_id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
  version: "0.2.1",
  os: "win32 10.0.22631",
  lang: "uk",
  note: "Оверлея не видно",
  text: '===== Settings =====\n{"api_key": "gsk_abcdefghijklmnopqrstu"}\nERROR sync failed\n'
};

test("keys never reach storage", () => {
  const text = [
    '{"apiKey": "secret-value"}',
    "Authorization: Bearer abcdefghijklmnop",
    "GET /players/1?api_key=0000aaaa-1111-bbbb",
    "AIzaSyA1234567890abcdefghijk",
    "AQ.FakeStudioKey000000-abcdefgh"
  ].join("\n");
  const clean = redact(text);
  for (const secret of ["secret-value", "abcdefghijklmnop", "0000aaaa", "AIzaSyA123", "FakeStudioKey"]) {
    assert.ok(!clean.includes(secret), secret);
  }
});

test("uploads are checked before anything is stored", () => {
  assert.equal(validateReport(null).code, "bad_json");
  assert.equal(validateReport({ install_id: "x", text: "a" }).code, "bad_install_id");
  assert.equal(validateReport({ install_id: REPORT.install_id, text: "  " }).code, "empty_report");
  assert.equal(validateReport({ install_id: REPORT.install_id, text: "a".repeat(1_500_001) }).status, 413);
  const ok = validateReport({ ...REPORT, extra: "dropped", note: "n".repeat(5000) });
  assert.equal(ok.ok, true);
  assert.equal(ok.report.note.length, 1000);
  assert.ok(!("extra" in ok.report));
  assert.match(reportId(new Uint8Array([0, 1, 2, 3, 4, 31])), /^R-[2-9A-HJ-NP-Z]{6}$/);
  assert.equal(summarize({ note: "", text: "===== x =====\nok\nERROR sync failed: timeout\n" }), "ERROR sync failed: timeout");
});

test("a report is stored, indexed and answered with its number", async () => {
  const { env, reports, objects } = fakeEnv();
  const response = await worker.fetch(upload(REPORT), env, ctx);
  assert.equal(response.status, 201);
  const answer = await response.json();
  assert.match(answer.id, /^R-[A-Z0-9]{6}$/);
  assert.equal(reports.length, 1);
  assert.equal(reports[0].summary, "Оверлея не видно");
  const [key] = objects.keys();
  assert.match(key, /^reports\/\d{4}\/\d{2}\/R-[A-Z0-9]{6}\.txt\.gz$/);
  const stored = await new Response(
    new Blob([objects.get(key).body]).stream().pipeThrough(new DecompressionStream("gzip"))
  ).text();
  assert.ok(stored.startsWith("Player note:\nОверлея не видно"));
  assert.ok(stored.includes('"api_key": "[redacted]"') && !stored.includes("gsk_"));
});

test("bad bodies, rate limits and the kill switch", async () => {
  const { env } = fakeEnv();
  assert.equal((await worker.fetch(upload("not json"), env, ctx)).status, 400);
  for (let i = 0; i < RATE_PER_HOUR.install; i += 1) {
    assert.equal((await worker.fetch(upload(REPORT), env, ctx)).status, 201);
  }
  const limited = await worker.fetch(upload(REPORT), env, ctx);
  assert.equal(limited.status, 429);
  assert.equal((await limited.json()).code, "rate_limited");

  const off = fakeEnv({ REPORTS_ENABLED: "false" });
  assert.equal(config(off.env).reports, false);
  assert.equal((await worker.fetch(upload(REPORT), off.env, ctx)).status, 503);
  const answer = await (await worker.fetch(new Request("https://api.example/v1/config"), off.env, ctx)).json();
  assert.deepEqual(answer, {
    reports: false,
    shares: true,
    transfers: true,
    transfer_minutes: 15,
    share_days: 90,
    stats: true,
    channels: true,
    profiles: true,
    recordings: true,
    recordings_sample: 1,
    recording_days: 60,
    retention_days: 180
  });
});

test("a player can delete their reports; old ones expire", async () => {
  const { env, reports, objects } = fakeEnv();
  await worker.fetch(upload(REPORT), env, ctx);
  await worker.fetch(upload({ ...REPORT, install_id: "other-install-1" }), env, ctx);
  const gone = await worker.fetch(
    new Request(`https://api.example/v1/device/${REPORT.install_id}`, { method: "DELETE" }),
    env,
    ctx
  );
  assert.deepEqual(await gone.json(), { ok: true, deleted: 1 });
  assert.equal(reports.length, 1);
  assert.equal(objects.size, 1);
  // 181 days later the last one is removed by the daily cleanup.
  assert.equal(await cleanup(env, Date.now() + 181 * 24 * 3_600_000), 1);
  assert.equal(reports.length, 0);
  assert.equal(objects.size, 0);
});

test("the admin page script runs, also as the deploy bundles it", () => {
  // wrangler/esbuild add __name(...) calls inside the function's text; without
  // the helper the script died on its first line and «Показати» did nothing.
  const bundled = ADMIN_JS.replace('const KEY = ', '__name(() => 0, "probe");\n  const KEY = ');
  assert.notEqual(bundled, ADMIN_JS);
  for (const source of [ADMIN_JS, bundled]) {
    const listeners = {};
    const node = (id) => ({
      id,
      value: "",
      textContent: "",
      className: "",
      classList: { add() {}, remove() {} },
      addEventListener(type) {
        listeners[`${id}:${type}`] = true;
      },
      replaceChildren() {}
    });
    const nodes = {};
    const context = {
      document: { getElementById: (id) => (nodes[id] ||= node(id)), createElement: () => node("x") },
      sessionStorage: { getItem: () => "", setItem() {}, removeItem() {} },
      fetch: async () => ({ status: 404 })
    };
    vm.runInNewContext(source, context);
    assert.ok(listeners["login:submit"], "the form listens for submit");
    assert.ok(listeners["days:change"]);
  }
});

test("admin endpoints need the token and hide otherwise", async () => {
  const { env } = fakeEnv({ ADMIN_TOKEN: "t0ken" });
  const { id } = await (await worker.fetch(upload(REPORT), env, ctx)).json();
  const hidden = await worker.fetch(new Request("https://api.example/v1/admin/reports"), env, ctx);
  assert.equal(hidden.status, 404);
  const auth = { headers: { authorization: "Bearer t0ken" } };
  const list = await (await worker.fetch(new Request("https://api.example/v1/admin/reports", auth), env, ctx)).json();
  assert.equal(list.reports[0].id, id);
  const text = await (await worker.fetch(new Request(`https://api.example/v1/admin/report/${id}`, auth), env, ctx)).text();
  assert.ok(text.includes("ERROR sync failed"));
  const noToken = fakeEnv();
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/reports", auth), noToken.env, ctx)).status, 404);
  // A secret pasted with a trailing newline still matches; another token does not.
  const pasted = fakeEnv({ ADMIN_TOKEN: "t0ken\n" });
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/reports", auth), pasted.env, ctx)).status, 200);
  const wrong = { headers: { authorization: "Bearer t0ke" } };
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/reports", wrong), pasted.env, ctx)).status, 404);
  const blank = fakeEnv({ ADMIN_TOKEN: " \n" });
  const empty = { headers: { authorization: "Bearer " } };
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/reports", empty), blank.env, ctx)).status, 404);
});

test("cleanup removes every expired report, object and row together", async () => {
  const { env, reports, objects } = fakeEnv();
  for (let i = 0; i < 250; i += 1) {
    const id = `R-OLD${String(i).padStart(3, "0")}`;
    reports.push({ id, created_at: 1, install_id: "old-install-1", r2_key: `reports/2026/01/${id}.txt.gz` });
    objects.set(`reports/2026/01/${id}.txt.gz`, { body: new Uint8Array() });
  }
  await worker.fetch(upload(REPORT), env, ctx);
  assert.equal(await cleanup(env, Date.now()), 250);
  assert.equal(reports.length, 1);
  assert.equal(objects.size, 1);
  assert.deepEqual([...objects.keys()], [reports[0].r2_key]);
});

test("without an R2 bucket the report is kept in D1", async () => {
  const { env, reports } = fakeEnv({ ADMIN_TOKEN: "t0ken" }, { r2: false });
  const response = await worker.fetch(upload(REPORT), env, ctx);
  assert.equal(response.status, 201);
  const { id } = await response.json();
  assert.equal(reports[0].r2_key, null);
  assert.ok(reports[0].body.length > 0);
  const auth = { headers: { authorization: "Bearer t0ken" } };
  const text = await (await worker.fetch(new Request(`https://api.example/v1/admin/report/${id}`, auth), env, ctx)).text();
  assert.ok(text.startsWith("Player note:\nОверлея не видно"));
  assert.equal(await cleanup(env, Date.now() + 181 * 24 * 3_600_000), 1);
  assert.equal(reports.length, 0);
  await worker.fetch(upload(REPORT), env, ctx);
  const gone = await worker.fetch(new Request(`https://api.example/v1/device/${REPORT.install_id}`, { method: "DELETE" }), env, ctx);
  assert.deepEqual(await gone.json(), { ok: true, deleted: 1 });
});

// --- «Поділитися розбором» ------------------------------------------------------------

const REVIEW = {
  lang: "uk",
  hero: "Juggernaut",
  hero_key: "juggernaut",
  win: false,
  duration: 2280,
  played_on: "2026-09-21",
  score: 31,
  grade: "D",
  role: "кор",
  parsed: true,
  stats: { kills: 3, deaths: 9, assists: 6, gpm: 390, xpm: 430, last_hits: 160, denies: 3, net_worth: 11500, hero_damage: 9000 },
  sections: [{ label: "Лінія", score: 20 }],
  strengths: [],
  improvements: [{ title: "Програна лінія <script>alert(1)</script>", text: "36 добивань до 10:00", drill: "Добивайте під вежею" }],
  deaths: { count: 9, enemy_half: 5, unspent_gold: 2 },
  coach: "Матч вирішила лінія. Steam 76561198000000001"
};

function shareRequest(body, ip = "198.51.100.7") {
  return new Request("https://api.example/v1/share", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": ip },
    body: JSON.stringify(body)
  });
}

test("a shared review is published, shown as a page and deleted by its author", async () => {
  const { env, shares } = fakeEnv();
  const response = await worker.fetch(
    shareRequest({ install_id: REPORT.install_id, version: "0.5.0", review: { ...REVIEW, match_id: 8012345678, extra: "x" } }),
    env,
    ctx
  );
  assert.equal(response.status, 201);
  const answer = await response.json();
  assert.match(answer.id, /^[2-9a-z]{10}$/);
  assert.equal(answer.url, `https://api.example/r/${answer.id}`);
  assert.equal(shares.length, 1);
  // With a Workers route on the site, the link points at the site.
  const siteEnv = { ...env, SHARE_ORIGIN: "https://luhovyimvp.dev" };
  const onSite = await (
    await worker.fetch(shareRequest({ install_id: REPORT.install_id, version: "0.9.0", review: REVIEW }), siteEnv, ctx)
  ).json();
  assert.match(onSite.url, /^https:\/\/luhovyimvp\.dev\/r\/[2-9a-z]{10}$/);
  // A 0.8 launcher opens only links on the API's address: it keeps getting those.
  const older = await (
    await worker.fetch(shareRequest({ install_id: REPORT.install_id, version: "0.8.0", review: REVIEW }), siteEnv, ctx)
  ).json();
  assert.match(older.url, /^https:\/\/api\.example\/r\//);
  shares.splice(1);

  const json = await (await worker.fetch(new Request(`https://api.example/v1/share/${answer.id}`), env, ctx)).json();
  assert.equal(json.review.hero, "Juggernaut");
  assert.ok(!("match_id" in json.review) && !("extra" in json.review));
  assert.ok(!json.review.coach.includes("76561198000000001"), "Steam IDs are cut out");

  const page = await worker.fetch(new Request(`https://api.example/r/${answer.id}`), env, ctx);
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-security-policy"), /default-src 'none'/);
  const html = await page.text();
  assert.match(html, /<meta property="og:title" content="Juggernaut · поразка · оцінка 31"/);
  assert.match(html, /heroes\/juggernaut\.png/);
  assert.ok(!html.includes("<script>alert(1)</script>"), "texts are escaped");
  assert.ok(html.includes("&lt;script&gt;"));
  // A visible way to try it, leading to the site in the review's language, tagged.
  assert.match(html, /<a class="try" href="https:\/\/luhovyimvp\.dev\/\?ref=share">Спробувати безкоштовно<\/a>/);
  assert.ok(!html.includes('href="https://luhovyimvp.dev/"'), "every site link carries ?ref=share");

  const noToken = await worker.fetch(new Request(`https://api.example/v1/share/${answer.id}`, { method: "DELETE" }), env, ctx);
  assert.equal(noToken.status, 403);
  const deleted = await worker.fetch(
    new Request(`https://api.example/v1/share/${answer.id}`, { method: "DELETE", headers: { "x-delete-token": answer.delete_token } }),
    env,
    ctx
  );
  assert.equal(deleted.status, 200);
  const gone = await worker.fetch(new Request(`https://api.example/r/${answer.id}`, { headers: { "accept-language": "uk-UA" } }), env, ctx);
  assert.equal(gone.status, 404);
  assert.match(await gone.text(), /Розбір не знайдено/);
  assert.equal(siteHome("en"), "https://luhovyimvp.dev/en/?ref=share");
  assert.equal(siteHome("uk"), "https://luhovyimvp.dev/?ref=share");
});

test("shares are checked, limited, expire and go with the installation", async () => {
  const { env, shares } = fakeEnv();
  const bad = await worker.fetch(shareRequest({ install_id: REPORT.install_id, review: { hero: "" } }), env, ctx);
  assert.equal(bad.status, 400);
  const off = await worker.fetch(shareRequest({ install_id: REPORT.install_id, review: REVIEW }), { ...env, SHARES_ENABLED: "false" }, ctx);
  assert.equal(off.status, 503);
  const now = Date.now();
  for (let i = 0; i < 20; i += 1) {
    const ok = await worker.fetch(shareRequest({ install_id: REPORT.install_id, review: REVIEW }), env, ctx);
    assert.equal(ok.status, 201);
  }
  const limited = await worker.fetch(shareRequest({ install_id: REPORT.install_id, review: REVIEW }), env, ctx);
  assert.equal(limited.status, 429);
  // 90 days later the cron removes them all.
  await cleanup(env, now + 91 * 24 * 3_600_000);
  assert.equal(shares.length, 0);
  await worker.fetch(shareRequest({ install_id: REPORT.install_id, review: REVIEW }, "198.51.100.8"), env, ctx);
  await worker.fetch(new Request(`https://api.example/v1/device/${REPORT.install_id}`, { method: "DELETE" }), env, ctx);
  assert.equal(shares.length, 0);
  assert.equal((await worker.fetch(new Request("https://api.example/r/not-an-id!"), env, ctx)).status, 404);
});

// --- «Поділитися прогресом» ----------------------------------------------------------

const PROGRESS = {
  kind: "progress",
  lang: "uk",
  matches: 14,
  analyzed: 12,
  wins: 9,
  losses: 5,
  winrate: 64,
  rank: "Легенда",
  period: { from: "2026-09-01", to: "2026-09-21" },
  averages: { kda: 8, gpm: 578.6, xpm: 632.9, lh_10: 58.7, deaths: 4.6, score: 70.3 },
  trend: [
    { key: "score", recent: 66.4, previous: 90, better: false },
    { key: "hacked", recent: 1, previous: 2, better: true }
  ],
  heroes: [{ hero: "Juggernaut", hero_key: "juggernaut", matches: 13, winrate: 62, match_id: 8012345678 }],
  strengths: [{ title: "Сильна лінія", count: 8, of: 12, drill: "not for strengths" }],
  problems: [{ title: "Фарм нижчий за <b>суперника</b>", count: 4, of: 12, drill: "Не віддавайте хвилі" }],
  focus: { title: "Смерті на лінії", met: 2, total: 3, results: [{ match_id: 1 }] },
  coach: "Стабільний фарм. Steam 76561198000000001",
  series: [{ match_id: 8012345678 }]
};

test("a shared progress page is checked field by field and rendered", async () => {
  const { env } = fakeEnv();
  const response = await worker.fetch(shareRequest({ install_id: REPORT.install_id, version: "0.7.0", progress: PROGRESS }), env, ctx);
  assert.equal(response.status, 201);
  const answer = await response.json();
  const { review } = await (await worker.fetch(new Request(`https://api.example/v1/share/${answer.id}`), env, ctx)).json();
  assert.equal(review.kind, "progress");
  assert.deepEqual(review.trend.map((t) => t.key), ["score"], "unknown trend keys are dropped");
  assert.ok(!("series" in review) && !("match_id" in review.heroes[0]) && !("results" in review.focus));
  assert.ok(!("drill" in review.strengths[0]));
  assert.ok(!review.coach.includes("76561198000000001"));
  const html = await (await worker.fetch(new Request(`https://api.example/r/${answer.id}`), env, ctx)).text();
  assert.match(html, /<meta property="og:title" content="Прогрес у Dota 2 · 14 матчів · 64% перемог"/);
  assert.match(html, /heroes\/juggernaut\.png/);
  assert.ok(html.includes("Фарм нижчий за &lt;b&gt;суперника&lt;/b&gt;"), "texts are escaped");
  assert.ok(html.includes("Виконано в 2 з 3 матчів"));

  const bad = await worker.fetch(shareRequest({ install_id: REPORT.install_id, progress: { analyzed: 0 } }), env, ctx);
  assert.equal(bad.status, 400);
  assert.equal((await bad.json()).code, "bad_progress");
});


// --- «Перенесення історії за кодом» --------------------------------------------------------

function sealed(size = 64) {
  const bytes = new Uint8Array(size);
  bytes.set([0x57, 0x44, 0x54, 0x31]);
  return bytes;
}

function putTransferRequest(id, body, { install = REPORT.install_id, ip = "198.51.100.9" } = {}) {
  return new Request(`https://api.example/v1/transfer/${id}`, {
    method: "PUT",
    headers: { "content-type": "application/octet-stream", "x-install-id": install, "cf-connecting-ip": ip },
    body
  });
}

function claimRequest(id, ip = "198.51.100.10") {
  return new Request(`https://api.example/v1/transfer/${id}/claim`, { method: "POST", headers: { "cf-connecting-ip": ip } });
}

test("an encrypted history is kept 15 minutes, downloaded and deleted by the receiver", async () => {
  const { env, transfers } = fakeEnv();
  const put = await worker.fetch(putTransferRequest("AB2C", sealed()), env, ctx);
  assert.equal(put.status, 201);
  assert.equal((await put.json()).id, "AB2C");
  assert.equal(transfers.length, 1);
  assert.equal((await worker.fetch(putTransferRequest("AB2C", sealed()), env, ctx)).status, 409, "the id is taken");

  const claim = await worker.fetch(claimRequest("AB2C"), env, ctx);
  assert.equal(claim.status, 200);
  const bytes = new Uint8Array(await claim.arrayBuffer());
  assert.deepEqual([...bytes.slice(0, 4)], [0x57, 0x44, 0x54, 0x31]);
  assert.equal(transfers.length, 1, "kept for a retry after a mistyped code");
  const done = await worker.fetch(new Request("https://api.example/v1/transfer/AB2C", { method: "DELETE" }), env, ctx);
  assert.equal(done.status, 200);
  assert.equal(transfers.length, 0);
  assert.equal((await worker.fetch(claimRequest("AB2C"), env, ctx)).status, 404);
});

test("three downloads at most", async () => {
  const { env, transfers } = fakeEnv();
  await worker.fetch(putTransferRequest("EF3G", sealed()), env, ctx);
  for (let i = 0; i < 3; i += 1) {
    assert.equal((await worker.fetch(claimRequest("EF3G"), env, ctx)).status, 200);
  }
  assert.equal(transfers.length, 0);
  assert.equal((await worker.fetch(claimRequest("EF3G"), env, ctx)).status, 404);
});

test("transfers refuse other bodies, big files and expire", async () => {
  const { env, transfers } = fakeEnv();
  assert.equal((await worker.fetch(putTransferRequest("AB2C", new Uint8Array(64)), env, ctx)).status, 400);
  assert.equal((await worker.fetch(putTransferRequest("ab2c", sealed()), env, ctx)).status, 400, "lowercase is not an id");
  assert.equal((await worker.fetch(putTransferRequest("AB2C", sealed(1_600_000)), env, ctx)).status, 413);
  assert.equal((await worker.fetch(putTransferRequest("AB2C", sealed(), { install: "x" }), env, ctx)).status, 400);
  const off = await worker.fetch(putTransferRequest("AB2C", sealed()), { ...env, TRANSFERS_ENABLED: "false" }, ctx);
  assert.equal(off.status, 503);

  await worker.fetch(putTransferRequest("CD3E", sealed()), env, ctx);
  assert.equal(transfers.length, 1);
  await cleanup(env, Date.now() + 16 * 60_000);
  assert.equal(transfers.length, 0);
  await worker.fetch(putTransferRequest("CD3E", sealed()), env, ctx);
  await worker.fetch(new Request(`https://api.example/v1/device/${REPORT.install_id}`, { method: "DELETE" }), env, ctx);
  assert.equal(transfers.length, 0, "the device delete removes it too");
});

test("guessing codes is slow", async () => {
  const { env } = fakeEnv();
  for (let i = 0; i < 30; i += 1) {
    assert.equal((await worker.fetch(claimRequest("ZZZZ", "203.0.113.5"), env, ctx)).status, 404);
  }
  assert.equal((await worker.fetch(claimRequest("ZZZZ", "203.0.113.5"), env, ctx)).status, 429);
});

test("version gate for site links", () => {
  assert.equal(versionAtLeast("0.9.0", [0, 9, 0]), true);
  assert.equal(versionAtLeast("0.10.2", [0, 9, 0]), true);
  assert.equal(versionAtLeast("1.0.0", [0, 9, 0]), true);
  assert.equal(versionAtLeast("0.8.9", [0, 9, 0]), false);
  assert.equal(versionAtLeast("", [0, 9, 0]), false);
  assert.equal(versionAtLeast("dev", [0, 9, 0]), false);
});


// --- «Друзі»: profile cards by friend code (src/profile.js) ---------------------

const INSTALL = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";
const TOKEN = "0123456789abcdef0123456789abcdef";
const CARD = {
  lang: "uk",
  name: "farm_or_die 76561198000000000",
  avatar: "0123456789abcdef0123456789abcdef01234567",
  title: "Легенда Wardly",
  level: 7,
  rank_tier: 54,
  rank_label: "Легенда 4",
  mmr: 3619,
  equipped: { frame: "frame_arcana", banner: "banner_aurora", name: "name_prism", title: "title_legend", extra: "x" },
  achievements: [{ id: "app_games", tier: 2, title: "З тренером" }, { id: "Bad Id", tier: 9 }],
  stats: { app_games: 12, app_winrate: 58, week_games: 4 },
  steam_id: "76561198000000000"
};

function putCard(id, { token = TOKEN, card = CARD, ip = "203.0.113.9" } = {}) {
  return new Request(`https://api.example/v1/profile/${id}`, {
    method: "PUT",
    headers: { "content-type": "application/json", "x-profile-token": token, "cf-connecting-ip": ip },
    body: JSON.stringify({ install_id: INSTALL, version: "0.35.0", profile: card })
  });
}

test("a profile card is published, read by friend code and shown as a page", async () => {
  const { env, profiles } = fakeEnv();
  let response = await worker.fetch(putCard("4k7p9qx2"), env, ctx);
  assert.equal(response.status, 201);
  const created = await response.json();
  assert.equal(created.code, "WD-4K7P9QX2");
  assert.match(created.url, /\/p\/4k7p9qx2$/);
  const stored = JSON.parse(profiles[0].body);
  assert.equal(stored.name, "farm_or_die"); // a Steam ID is cut from the text
  assert.equal(stored.steam_id, undefined);
  assert.deepEqual(Object.keys(stored.equipped), ["frame", "banner", "name", "title"]);
  assert.deepEqual(stored.achievements.map((a) => a.id), ["app_games"]);
  // The same launcher updates it; another token cannot.
  response = await worker.fetch(putCard("4k7p9qx2", { card: { ...CARD, level: 8 } }), env, ctx);
  assert.equal(response.status, 200);
  response = await worker.fetch(putCard("4k7p9qx2", { token: "f".repeat(32) }), env, ctx);
  assert.equal(response.status, 409);
  // Friends read cards by code, as people type it.
  response = await worker.fetch(
    new Request("https://api.example/v1/profiles", { method: "POST", body: JSON.stringify({ ids: ["WD-4K7P 9QX2", "nope", "22222222"] }) }),
    env,
    ctx
  );
  const read = await response.json();
  assert.deepEqual(Object.keys(read.profiles), ["4k7p9qx2"]);
  assert.equal(read.profiles["4k7p9qx2"].level, 8);
  // The page: escaped, with the code to add.
  response = await worker.fetch(new Request("https://api.example/p/4k7p9qx2"), env, ctx);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /WD-4K7P9QX2/);
  assert.match(html, /Легенда Wardly/);
  assert.doesNotMatch(html, /76561198/);
  // The looks and the avatar as the launcher draws them.
  assert.match(html, /class="pf-banner cos-banner_aurora"/);
  assert.match(html, /class="pf-avatar-wrap cos-frame_arcana"/);
  assert.match(html, /src="https:\/\/avatars\.steamstatic\.com\/0123456789abcdef0123456789abcdef01234567_full\.jpg"/);
  assert.match(response.headers.get("content-security-policy"), /img-src [^;]*https:\/\/avatars\.steamstatic\.com/);
  response = await worker.fetch(new Request("https://api.example/p/zzzzzzzz"), env, ctx);
  assert.equal(response.status, 404);
});

test("a profile page without looks or avatar wears the free looks, and a bad avatar is dropped", async () => {
  const { env, profiles } = fakeEnv();
  const card = { ...CARD, avatar: "https://evil.example/x.jpg", equipped: {} };
  await worker.fetch(putCard("4k7p9qx2", { card }), env, ctx);
  assert.equal(JSON.parse(profiles[0].body).avatar, null);
  const html = await (await worker.fetch(new Request("https://api.example/p/4k7p9qx2"), env, ctx)).text();
  assert.match(html, /class="pf-banner cos-banner_plain"/);
  assert.match(html, /class="pf-avatar-wrap cos-frame_plain"/);
  assert.doesNotMatch(html, /<img src="https:\/\/evil/);
});

// The cos- rules of a stylesheet, selector -> declarations, with whitespace,
// comments and leading zeros folded and the launcher's tokens filled in.
function lookRules(css, tokens = {}) {
  const fold = (text) =>
    text
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/var\((--[a-z0-9-]+)\)/g, (all, name) => tokens[name] || all)
      .replace(/\s+/g, " ")
      .replace(/\s*([{}:;,>()])\s*/g, "$1")
      .replace(/(^|[^0-9.])0\./g, "$1.")
      .replace(/;$/, "")
      .trim();
  const rules = new Map();
  for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const key = fold(selector);
    if (key.includes(".cos-")) {
      rules.set(key, [rules.get(key), fold(body)].filter(Boolean).join(";"));
    }
  }
  return rules;
}

test("the profile page wears every look exactly as the launcher draws it", () => {
  const read = (path) => readFileSync(new URL(`../../../frontend/launcher/${path}`, import.meta.url), "utf8");
  const root = read("assets/ui/tokens.css").match(/:root\s*\{([^}]*)\}/)[1];
  const tokens = Object.fromEntries([...root.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)].map(([, name, value]) => [name, value.trim()]));
  const launcher = lookRules(read("renderer/styles.css"), tokens);
  assert.ok(launcher.size > 15);
  const html = renderProfilePage({ ...CARD, name: "x", avatar: null, achievements: [], stats: { app_games: 0, app_winrate: null }, mmr: null }, { id: "4k7p9qx2", url: "" });
  const page = lookRules([...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((match) => match[1]).join("\n"));
  assert.deepEqual(Object.fromEntries(page), Object.fromEntries(launcher));
});

test("a profile card is hidden with its token, by the device delete and after 180 days", async () => {
  const { env, profiles } = fakeEnv();
  await worker.fetch(putCard("4k7p9qx2"), env, ctx);
  let response = await worker.fetch(
    new Request("https://api.example/v1/profile/4k7p9qx2", { method: "DELETE", headers: { "x-profile-token": "f".repeat(32) } }),
    env,
    ctx
  );
  assert.equal(response.status, 403);
  response = await worker.fetch(
    new Request("https://api.example/v1/profile/4k7p9qx2", { method: "DELETE", headers: { "x-profile-token": TOKEN } }),
    env,
    ctx
  );
  assert.equal(response.status, 200);
  assert.equal(profiles.length, 0);
  await worker.fetch(putCard("4k7p9qx2"), env, ctx);
  await worker.fetch(new Request(`https://api.example/v1/device/${INSTALL}`, { method: "DELETE" }), env, ctx);
  assert.equal(profiles.length, 0);
  await worker.fetch(putCard("4k7p9qx2"), env, ctx);
  await cleanup(env, Date.now() + 181 * 24 * 3_600_000);
  assert.equal(profiles.length, 0);
});

test("bad profile requests are refused", async () => {
  const { env } = fakeEnv();
  assert.equal((await worker.fetch(putCard("UPPER123"), env, ctx)).status, 400);
  assert.equal((await worker.fetch(putCard("4k7p9qx2", { token: "short" }), env, ctx)).status, 400);
  assert.equal((await worker.fetch(putCard("4k7p9qx2", { card: { ...CARD, name: "" } }), env, ctx)).status, 400);
  const off = fakeEnv({ PROFILES_ENABLED: "false" });
  assert.equal((await worker.fetch(putCard("4k7p9qx2"), off.env, ctx)).status, 503);
  assert.equal(config(off.env).profiles, false);
});

// --- match recordings sent by consent (src/session.js) ----------------------

const META_LINE = { k: "meta", hero: "npc_dota_hero_juggernaut", payloads: 2, advice: 0, last_clock: 600, format: 1, upload: 1, anonymized: true };

function recordingBytes(meta = META_LINE) {
  const rows = [JSON.stringify(meta), JSON.stringify({ k: "gsi", w: 0, ts: "+0.000", p: { map: { clock_time: 1 } } })];
  return new Uint8Array(gzipSync(Buffer.from(`${rows.join("\n")}\n`)));
}

function sessionUpload(body = recordingBytes(), { ip = "203.0.113.5", install = REPORT.install_id, key = "a".repeat(64), extra = {} } = {}) {
  return new Request("https://api.example/v1/session", {
    method: "POST",
    headers: {
      "content-type": "application/gzip",
      "content-length": String(body.length),
      "cf-connecting-ip": ip,
      "x-install-id": install,
      "x-app-version": "0.63.0",
      "x-hero": "npc_dota_hero_juggernaut",
      "x-minutes": "42",
      ...(key ? { "x-device-key": key } : {}),
      ...extra
    },
    body
  });
}

test("a recording is stored in R2 with an index row and a note to the developer", async () => {
  const sent = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    sent.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response("{}");
  };
  try {
    const { env, sessions, objects } = fakeEnv({ TELEGRAM_BOT_TOKEN: "bot", TELEGRAM_CHAT_ID: "42" });
    const bytes = recordingBytes();
    const response = await worker.fetch(sessionUpload(bytes), env, ctx);
    assert.equal(response.status, 201);
    const answer = await response.json();
    assert.match(answer.id, /^S-[2-9A-HJ-NP-Z]{6}$/);
    assert.equal(answer.retention_days, 60);
    assert.equal(sessions.length, 1);
    const row = sessions[0];
    assert.deepEqual([row.hero, row.minutes, row.size, row.version], ["npc_dota_hero_juggernaut", 42, bytes.length, "0.63.0"]);
    assert.equal("install_id" in row, false, "the raw installation id is not stored");
    assert.match(row.install_hash, /^[a-f0-9]{32}$/);
    assert.ok(!JSON.stringify(row).includes(REPORT.install_id));
    assert.ok(["tune", "holdout"].includes(row.split));
    assert.match(row.r2_key, /^sessions\/\d{4}\/\d{2}\/S-[A-Z0-9]{6}\.jsonl\.gz$/);
    assert.equal(row.owner_hash.length, 32);
    assert.deepEqual([...objects.get(row.r2_key).body], [...bytes]);
    assert.equal(sent.length, 1);
    assert.ok(sent[0].url.endsWith("/sendMessage") && sent[0].body.text.includes(answer.id));
    assert.ok(!JSON.stringify(sent[0].body).includes(REPORT.install_id));
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("recordings can be switched off, need R2 and are announced in the config", async () => {
  const off = fakeEnv({ RECORDINGS_ENABLED: "false" });
  assert.equal(config(off.env).recordings, false);
  assert.deepEqual(await (await worker.fetch(sessionUpload(), off.env, ctx)).json(), { ok: false, code: "disabled" });
  assert.equal((await worker.fetch(sessionUpload(), off.env, ctx)).status, 503);
  const noR2 = fakeEnv({}, { r2: false });
  assert.equal(config(noR2.env).recordings, false);
  const response = await worker.fetch(sessionUpload(), noR2.env, ctx);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "storage_unavailable");
  assert.equal(config(fakeEnv({ RECORDINGS_SAMPLE: "0.25" }).env).recordings_sample, 0.25);
  assert.equal(config(fakeEnv({ RECORDINGS_SAMPLE: "7" }).env).recordings_sample, 1);
  assert.equal(config(fakeEnv({ RECORDINGS_SAMPLE: "-1" }).env).recordings_sample, 0);
  assert.equal(config(fakeEnv({ RECORDINGS_SAMPLE: "abc" }).env).recordings_sample, 1);
});

test("a bad recording is refused before anything is stored", async () => {
  const { env, sessions, objects } = fakeEnv();
  let n = 0;
  // Every attempt counts against the limits, so each comes from another installation.
  const refuse = async (body, status, code, extra = {}) => {
    n += 1;
    const request = sessionUpload(body, { install: `install-${n}-aaaaaaaa`, ip: `203.0.113.${n}`, extra });
    const response = await worker.fetch(request, env, ctx);
    assert.equal(response.status, status, code);
    assert.equal((await response.json()).code, code);
  };
  await refuse(recordingBytes(), 413, "too_large", { "content-length": String(21 * 1024 * 1024) });
  await refuse(new TextEncoder().encode("this is not a gzip file at all, only text"), 400, "bad_recording");
  await refuse(recordingBytes({ ...META_LINE, anonymized: false }), 400, "bad_recording");
  await refuse(recordingBytes({ ...META_LINE, matchid: "8012345678" }), 422, "not_anonymized");
  await refuse(recordingBytes({ ...META_LINE, steamid: "7656" }), 422, "not_anonymized");
  await refuse(recordingBytes(), 400, "bad_minutes", { "x-minutes": "999" });
  n += 1;
  const noKey = await worker.fetch(sessionUpload(recordingBytes(), { install: `install-${n}-aaaaaaaa`, ip: `203.0.113.${n}`, key: null }), env, ctx);
  assert.deepEqual([noKey.status, (await noKey.json()).code], [400, "no_device_key"]);
  n += 1;
  const badKey = await worker.fetch(sessionUpload(recordingBytes(), { install: `install-${n}-aaaaaaaa`, ip: `203.0.113.${n}`, key: "xyz" }), env, ctx);
  assert.deepEqual([badKey.status, (await badKey.json()).code], [400, "no_device_key"]);
  assert.equal((await worker.fetch(sessionUpload(recordingBytes(), { install: "x" }), env, ctx)).status, 400);
  assert.equal(sessions.length, 0);
  assert.equal(objects.size, 0);
});

test("recordings are limited per installation, per address and per day", async () => {
  const { env, sessions } = fakeEnv();
  for (let i = 0; i < 3; i += 1) {
    assert.equal((await worker.fetch(sessionUpload(recordingBytes(), { ip: `203.0.113.${i + 10}` }), env, ctx)).status, 201);
  }
  const fourth = await worker.fetch(sessionUpload(recordingBytes(), { ip: "203.0.113.99" }), env, ctx);
  assert.equal(fourth.status, 429);
  assert.equal((await fourth.json()).code, "rate_limited");
  // Another installation from one address: 10 an hour, then refused.
  const crowded = fakeEnv();
  for (let i = 0; i < 10; i += 1) {
    const install = `install-number-${i}-aaaa`;
    assert.equal((await worker.fetch(sessionUpload(recordingBytes(), { install }), crowded.env, ctx)).status, 201);
  }
  assert.equal((await worker.fetch(sessionUpload(recordingBytes(), { install: "install-number-x-aaaa" }), crowded.env, ctx)).status, 429);
  assert.equal(sessions.length, 3);
});

test("storage is capped by bytes per day and in total, this upload included", async () => {
  const { handleSession } = await import("../src/index.js");
  const { SESSION_DAILY_BYTES, SESSION_TOTAL_BYTES } = await import("../src/session.js");
  const bytes = recordingBytes();
  const hour = 3_600_000;
  // 1.5 GB in the last day: even a small file is refused, with a distinct code.
  const full = fakeEnv();
  full.sessions.push({ id: "S-FAKE22", created_at: Date.now() - hour, size: SESSION_DAILY_BYTES - bytes.length + 1, r2_key: "k" });
  const refused = await worker.fetch(sessionUpload(bytes, { install: "fresh-install-aaaa", ip: "198.51.100.7" }), full.env, ctx);
  assert.deepEqual([refused.status, (await refused.json()).code], [507, "storage_full"]);
  // Exactly up to the cap is taken.
  full.sessions[0].size = SESSION_DAILY_BYTES - bytes.length;
  assert.equal((await worker.fetch(sessionUpload(bytes, { install: "fresh-install-aaaa", ip: "198.51.100.7" }), full.env, ctx)).status, 201);
  // A day later the daily window is empty again.
  const later = Date.now() + 25 * hour;
  assert.equal((await handleSession(sessionUpload(bytes, { install: "fresh-install-bbbb", ip: "198.51.100.8" }), full.env, ctx, later)).status, 201);
  // 8 GB in total: old files count although they are older than a day.
  const total = fakeEnv();
  total.sessions.push({ id: "S-OLD222", created_at: Date.now() - 5 * 24 * hour, size: SESSION_TOTAL_BYTES - bytes.length + 1, r2_key: "k" });
  const second = await worker.fetch(sessionUpload(bytes), total.env, ctx);
  assert.deepEqual([second.status, (await second.json()).code], [507, "storage_full"]);
  assert.equal(total.objects.size, 0);
});

test("uploads refused before the limits do not use up the hourly limit", async () => {
  const { env, sessions } = fakeEnv();
  const same = { install: "one-install-aaaa", ip: "203.0.113.77" };
  const bad = [
    { extra: { "x-minutes": "999" } },
    { extra: { "x-hero": "Juggernaut; drop table" } },
    { key: null }
  ];
  for (const options of bad) {
    assert.equal((await worker.fetch(sessionUpload(recordingBytes(), { ...same, ...options }), env, ctx)).status, 400);
  }
  assert.equal((await worker.fetch(sessionUpload(recordingBytes(), same), env, ctx)).status, 201);
  assert.equal(sessions.length, 1);
});

test("a failed R2 put leaves no index row", async () => {
  const { env, sessions, objects } = fakeEnv({ FAIL_PUT: true });
  const response = await worker.fetch(sessionUpload(), env, ctx);
  assert.deepEqual([response.status, (await response.json()).code], [500, "storage_error"]);
  assert.equal(sessions.length, 0);
  assert.equal(objects.size, 0);
});

test("an id collision fails before any put and draws another id", async () => {
  const { handleSession } = await import("../src/index.js");
  const { env, sessions, objects } = fakeEnv();
  const taken = "S-222222";
  const theirs = new Uint8Array([9, 9, 9]);
  sessions.push({ id: taken, created_at: Date.now(), owner_hash: "other", size: 3, r2_key: sessionKeyFor(taken) });
  objects.set(sessionKeyFor(taken), { body: theirs });
  const draws = [new Uint8Array(6), new Uint8Array([1, 2, 3, 4, 5, 6])];
  const response = await handleSession(sessionUpload(), env, ctx, Date.now(), () => draws.shift());
  assert.equal(response.status, 201);
  const { id } = await response.json();
  assert.notEqual(id, taken);
  assert.deepEqual([...objects.get(sessionKeyFor(taken)).body], [...theirs], "the other file is untouched");
  assert.equal(sessions.length, 2);
  assert.equal(objects.size, 2);
  // Two collisions in a row give up without touching anything.
  const clash = fakeEnv();
  clash.sessions.push({ id: taken, created_at: Date.now(), owner_hash: "other", size: 3, r2_key: sessionKeyFor(taken) });
  const failed = await handleSession(sessionUpload(), clash.env, ctx, Date.now(), () => new Uint8Array(6));
  assert.equal(failed.status, 500);
  assert.equal(clash.objects.size, 0);
});

function sessionKeyFor(id) {
  const now = new Date();
  return `sessions/${now.getUTCFullYear()}/${String(now.getUTCMonth() + 1).padStart(2, "0")}/${id}.jsonl.gz`;
}

test("Delete my data removes recordings and their R2 objects with the device key only", async () => {
  const { env, sessions, objects } = fakeEnv();
  await worker.fetch(sessionUpload(recordingBytes(), { ip: "203.0.113.20" }), env, ctx);
  await worker.fetch(sessionUpload(recordingBytes(), { ip: "203.0.113.21", install: "other-install-1", key: "b".repeat(64) }), env, ctx);
  assert.equal(objects.size, 2);
  const del = (key) =>
    worker.fetch(new Request(`https://api.example/v1/device/${REPORT.install_id}`, { method: "DELETE", headers: key ? { "x-device-key": key } : {} }), env, ctx);
  // Without the key (an older launcher) rows that have an owner stay.
  assert.equal((await del(null)).status, 200);
  assert.equal(sessions.length, 2);
  assert.equal((await del("a".repeat(64))).status, 200);
  assert.deepEqual(sessions.map((r) => r.owner_hash.length), [32]);
  assert.ok(sessions.every((r) => !("install_id" in r)));
  assert.deepEqual([...objects.keys()], [sessions[0].r2_key]);
});

test("cleanup deletes recordings after 60 days, objects first, in batches", async () => {
  const { env, sessions, objects } = fakeEnv();
  for (let i = 0; i < 230; i += 1) {
    const key = `sessions/2026/01/S-OLD${i}.jsonl.gz`;
    sessions.push({ id: `S-OLD${i}`, created_at: 1, owner_hash: "old", r2_key: key });
    objects.set(key, { body: new Uint8Array() });
  }
  await worker.fetch(sessionUpload(), env, ctx);
  const fresh = sessions.at(-1);
  const now = Date.now();
  await cleanup(env, now + 59 * 24 * 3_600_000);
  assert.equal(sessions.length, 1, "the 230 old ones go, the new one is still there at 59 days");
  assert.equal(objects.size, 1);
  await cleanup(env, now + 61 * 24 * 3_600_000);
  assert.equal(sessions.length, 0);
  assert.equal(objects.has(fresh.r2_key), false);
});

test("the developer lists and downloads recordings with the admin token only", async () => {
  const { env } = fakeEnv({ ADMIN_TOKEN: "t0ken" });
  const bytes = recordingBytes();
  const id = (await (await worker.fetch(sessionUpload(bytes), env, ctx)).json()).id;
  const auth = { headers: { authorization: "Bearer t0ken" } };
  const list = await (await worker.fetch(new Request("https://api.example/v1/admin/sessions", auth), env, ctx)).json();
  assert.equal(list.sessions[0].id, id);
  assert.deepEqual(Object.keys(list.sessions[0]).sort(), ["created_at", "hero", "id", "minutes", "size", "split", "version"]);
  const side = list.sessions[0].split;
  const other = side === "tune" ? "holdout" : "tune";
  const mine = await (await worker.fetch(new Request(`https://api.example/v1/admin/sessions?split=${side}`, auth), env, ctx)).json();
  const rest = await (await worker.fetch(new Request(`https://api.example/v1/admin/sessions?split=${other}`, auth), env, ctx)).json();
  assert.deepEqual([mine.sessions.length, rest.sessions.length], [1, 0]);
  const file = await worker.fetch(new Request(`https://api.example/v1/admin/session/${id}`, auth), env, ctx);
  assert.equal(file.headers.get("content-type"), "application/gzip");
  assert.match(file.headers.get("content-disposition"), new RegExp(`${id}\\.jsonl\\.gz`));
  assert.deepEqual([...new Uint8Array(await file.arrayBuffer())], [...bytes]);
  assert.equal((await worker.fetch(new Request("https://api.example/v1/admin/session/S-AAAAAA", auth), env, ctx)).status, 404);
  for (const path of ["/v1/admin/sessions", `/v1/admin/session/${id}`]) {
    assert.equal((await worker.fetch(new Request(`https://api.example${path}`), env, ctx)).status, 404);
    assert.equal((await worker.fetch(new Request(`https://api.example${path}`, { headers: { authorization: "Bearer nope" } }), env, ctx)).status, 404);
  }
});
