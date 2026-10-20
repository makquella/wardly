// Direct publishing on the real Worker, workerd D1 and R2 (all migrations):
// /connect -> OAuth callback -> sealed account; approval -> deliveries; the
// five-minute cron uploads, polls and reports. The networks are answered by
// the outbound service.
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";
import { webhookSecret } from "../../src/promo.js";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const SOURCE = path.join(ROOT, "src");
const BOT = "123456:test-token";
const ADMIN = "4242";
const ID = "fedcba9876543210";

async function localWorker(t, extra = {}) {
  const calls = [];
  let igStatus = "IN_PROGRESS";
  let ytStatus = null; // the status the upload session was opened with
  const paths = (await readdir(SOURCE, { recursive: true })).filter((name) => name.endsWith(".js") && name !== "index.js");
  const modules = ["index.js", ...paths].map((name) => ({ type: "ESModule", path: path.join(SOURCE, name) }));
  const mf = new Miniflare(
    convertV4MiniflareOptions({
      modules,
      modulesRoot: ROOT,
      compatibilityDate: "2026-09-20",
      d1Databases: { DB: "wardly-social-integration" },
      r2Buckets: ["REPORTS"],
      bindings: {
        ADMIN_TOKEN: "admin-secret",
        TELEGRAM_BOT_TOKEN: BOT,
        TELEGRAM_CHAT_ID: ADMIN,
        TELEGRAM_CHANNEL: "@wardlydota",
        PROMO_PUBLIC_ORIGIN: "https://api.test",
        PROMO_NETWORKS: "instagram,tiktok,youtube",
        YOUTUBE_CLIENT_ID: "yt-id",
        YOUTUBE_CLIENT_SECRET: "yt-secret",
        INSTAGRAM_APP_ID: "ig-id",
        INSTAGRAM_APP_SECRET: "ig-secret",
        ...extra
      },
      outboundService: async (request) => {
        const body = request.method === "GET" ? null : await request.text();
        calls.push({ url: request.url, method: request.method, body, headers: Object.fromEntries(request.headers) });
        const url = new URL(request.url);
        const route = `${url.hostname}${url.pathname}`;
        if (url.hostname === "api.telegram.org") {
          if (url.pathname.endsWith("/sendVideo") && JSON.parse(body).chat_id === "@broken") {
            return Response.json({ ok: false, description: "chat not found" }, { status: 400 });
          }
          return Response.json({ ok: true, result: { message_id: 77 } });
        }
        if (route === "oauth2.googleapis.com/token") {
          return Response.json({ access_token: "yt-access", refresh_token: "yt-refresh-secret", expires_in: 3600 });
        }
        if (route === "www.googleapis.com/youtube/v3/channels") {
          return Response.json({ items: [{ id: "UC1", snippet: { title: "Wardly" } }] });
        }
        if (route === "www.googleapis.com/upload/youtube/v3/videos") {
          ytStatus = JSON.parse(body).status;
          return new Response("{}", { headers: { location: "https://upload.test/s1" } });
        }
        if (route === "upload.test/s1") {
          if (String(request.headers.get("content-range") || "").startsWith("bytes */")) return new Response(null, { status: 308 });
          return Response.json({ id: "vid1", status: { privacyStatus: ytStatus?.privacyStatus || "public", ...(ytStatus?.publishAt ? { publishAt: ytStatus.publishAt } : {}) } });
        }
        if (route === "api.instagram.com/oauth/access_token") return Response.json({ access_token: "ig-short", user_id: 555 });
        if (route === "graph.instagram.com/access_token") return Response.json({ access_token: "ig-long-secret", expires_in: 5184000 });
        if (route === "graph.instagram.com/v21.0/me") return Response.json({ user_id: "555", username: "wardly" });
        if (route === "graph.instagram.com/v21.0/555/media") return Response.json({ id: "cont1" });
        if (route === "graph.instagram.com/v21.0/cont1") return Response.json({ status_code: igStatus });
        if (route === "graph.instagram.com/v21.0/555/media_publish") return Response.json({ id: "reel1" });
        if (route === "graph.instagram.com/v21.0/reel1") return Response.json({ permalink: "https://www.instagram.com/reel/r1/" });
        return new Response("not found", { status: 404 });
      }
    })
  );
  t.after(() => mf.dispose());
  const db = await mf.getD1Database("DB");
  for (const file of (await readdir(path.join(ROOT, "migrations"))).filter((name) => name.endsWith(".sql")).sort()) {
    const sql = await readFile(path.join(ROOT, "migrations", file), "utf8");
    for (const statement of sql.replace(/--[^\n]*/g, "").split(";").map((part) => part.trim()).filter(Boolean)) {
      await db.prepare(statement).run();
    }
  }
  return { mf, db, calls, setIg: (value) => (igStatus = value) };
}

async function update(mf, payload) {
  return mf.dispatchFetch("https://api.test/v1/telegram/webhook", {
    method: "POST",
    headers: { "content-type": "application/json", "x-telegram-bot-api-secret-token": await webhookSecret(BOT) },
    body: JSON.stringify({ update_id: 1, ...payload })
  });
}

function say(mf, text, from = ADMIN) {
  return update(mf, { message: { message_id: 1, text, chat: { id: Number(from), type: "private" }, from: { id: Number(from) } } });
}

function sent(calls, method) {
  return calls.filter((c) => c.url.endsWith(`/${method}`)).map((c) => JSON.parse(c.body));
}

async function connect(mf, calls, network, code) {
  await say(mf, `/connect ${network}`);
  const message = sent(calls, "sendMessage").at(-1);
  const link = new URL(message.reply_markup.inline_keyboard[0][0].url);
  assert.equal(link.searchParams.get("redirect_uri"), `https://api.test/oauth/${network}/callback`);
  const state = link.searchParams.get("state");
  const page = await mf.dispatchFetch(`https://api.test/oauth/${network}/callback?code=${code}&state=${state}`);
  return { page, state };
}

test("accounts connect through the bot, only for the developer, and are stored sealed", async (t) => {
  const { mf, db, calls } = await localWorker(t);
  await say(mf, "/connect youtube", "999"); // a stranger gets no link
  assert.ok(!sent(calls, "sendMessage").some((m) => m.reply_markup));
  const { page, state } = await connect(mf, calls, "youtube", "c1");
  assert.equal(page.status, 200);
  assert.match(await page.text(), /YouTube підключено/);
  const row = await db.prepare("SELECT sealed, account FROM promo_accounts WHERE network = 'youtube'").first();
  assert.equal(row.account, "Wardly");
  assert.ok(!row.sealed.includes("yt-refresh-secret") && !row.sealed.includes("yt-access"));
  // The link works once.
  const again = await mf.dispatchFetch(`https://api.test/oauth/youtube/callback?code=c1&state=${state}`);
  assert.equal(again.status, 400);
  // TikTok has no app secrets here: the bot says which to add.
  await say(mf, "/connect tiktok");
  assert.match(sent(calls, "sendMessage").at(-1).text, /TIKTOK_CLIENT_KEY/);
  await say(mf, "/accounts");
  const list = sent(calls, "sendMessage").at(-1).text;
  assert.match(list, /✅ YouTube: Wardly/);
  assert.match(list, /Instagram: не підключено/);
  assert.match(list, /TikTok: додайте секрети/);
});

async function approveAndRun(mf, db, calls, action = "all", metadata = {}) {
  const auth = { authorization: "Bearer admin-secret" };
  const created = await mf.dispatchFetch("https://api.test/v1/admin/promo", {
    method: "POST",
    headers: auth,
    body: JSON.stringify({
      id: ID,
      format: "meta",
      topic: "2026-10-12",
      title: "Мета тижня",
      youtube_title: "Мета тижня #shorts",
      caption: "Мета тижня — найбільше перемог:\n1. Wraith King",
      telegram_caption: "Мета тижня",
      ...metadata
    })
  });
  const registration = await created.json();
  const { media_key: key } = registration;
  if (metadata.youtube_language) {
    assert.equal(registration.youtube_language, metadata.youtube_language);
    assert.deepEqual(registration.youtube_tags, metadata.youtube_tags);
    assert.equal(registration.youtube_ready, true);
  }
  await mf.dispatchFetch(`https://api.test/v1/admin/promo/${ID}/video.mp4`, { method: "PUT", headers: auth, body: new Uint8Array(2048).fill(3) });
  await update(mf, {
    callback_query: {
      id: "cb",
      from: { id: Number(ADMIN) },
      data: `promo:${action}:${ID}`,
      message: { message_id: 9, chat: { id: Number(ADMIN), type: "private" }, video: { file_id: "F1" } }
    }
  });
  return key;
}

const deliveries = async (db) =>
  (await db.prepare("SELECT network, status, url FROM promo_deliveries WHERE post_id = ? ORDER BY network").bind(ID).all()).results;

test("an approved video goes to YouTube and Instagram by the cron, once, and is reported", async (t) => {
  const { mf, db, calls, setIg } = await localWorker(t);
  await connect(mf, calls, "youtube", "c1");
  await connect(mf, calls, "instagram", "c2");
  const key = await approveAndRun(mf, db, calls);
  assert.deepEqual((await deliveries(db)).map((r) => `${r.network}:${r.status}`), ["instagram:queued", "youtube:queued"]);
  const report = sent(calls, "sendMessage").at(-1).text;
  assert.match(report, /Instagram, YouTube: у черзі/);
  assert.match(report, /TikTok: не підключено/);

  const worker = await mf.getWorker();
  const run = () => worker.scheduled({ cron: "*/5 * * * *" });
  await run(); // YouTube: session kept; Instagram: container made
  assert.deepEqual((await deliveries(db)).map((r) => `${r.network}:${r.status}`), ["instagram:processing", "youtube:processing"]);
  const container = calls.find((c) => c.url.includes("/555/media") && !c.url.includes("publish"));
  assert.equal(new URLSearchParams(container.body).get("video_url"), `https://api.test/m/${key}/video.mp4`);
  assert.equal(calls.filter((c) => c.url.includes("upload.test/s1")).length, 0);

  await run(); // YouTube: checked and uploaded; Instagram not due yet
  let rows = await deliveries(db);
  assert.deepEqual(rows.map((r) => `${r.network}:${r.status}`), ["instagram:processing", "youtube:published"]);
  assert.equal(rows[1].url, "https://youtube.com/shorts/vid1");
  assert.equal(calls.filter((c) => c.url.includes("/cont1")).length, 0);
  const uploads = calls.filter((c) => c.url.includes("upload.test/s1"));
  assert.equal(uploads.length, 2);
  assert.ok(uploads.every((c) => c.headers.authorization === "Bearer yt-access"));
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "publishing");

  await db.prepare("UPDATE promo_deliveries SET next_at = 0 WHERE post_id = ?").bind(ID).run();
  setIg("FINISHED");
  await run();
  await run();
  rows = await deliveries(db);
  assert.deepEqual(rows.map((r) => `${r.network}:${r.status}`), ["instagram:published", "youtube:published"]);
  assert.equal(calls.filter((c) => c.url.includes("/media_publish")).length, 1);
  assert.equal(calls.filter((c) => c.url.includes("upload.test/s1")).length, 2);
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "published");
  const final = sent(calls, "sendMessage").at(-1);
  assert.equal(final.reply_to_message_id, 9);
  assert.match(final.text, /✅ Instagram: опубліковано — https:\/\/www.instagram.com\/reel\/r1\//);
  assert.match(final.text, /✅ YouTube: опубліковано — https:\/\/youtube.com\/shorts\/vid1/);
});

test("a failed channel post does not stop the networks or their report", async (t) => {
  const { mf, db, calls } = await localWorker(t, { TELEGRAM_CHANNEL: "@broken" });
  await connect(mf, calls, "youtube", "c1");
  await approveAndRun(mf, db, calls);
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "publishing");
  assert.match(sent(calls, "sendMessage").at(-1).text, /Telegram-канал: chat not found/);
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: "*/5 * * * *" });
  await worker.scheduled({ cron: "*/5 * * * *" });
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "published");
  assert.match(sent(calls, "sendMessage").at(-1).text, /✅ YouTube: опубліковано/);
});

test("«Лише YouTube» queues YouTube only and leaves the channel alone", async (t) => {
  const { mf, db, calls } = await localWorker(t);
  await connect(mf, calls, "youtube", "c1");
  await connect(mf, calls, "instagram", "c2");
  const metadata = {
    youtube_title: "Dota 2 beta testers wanted",
    caption: "Comment BETA. #Dota2 #Wardly #Shorts",
    youtube_tags: ["Dota 2", "Wardly", "beta test"],
    youtube_language: "en"
  };
  await approveAndRun(mf, db, calls, "yt", metadata);
  assert.deepEqual((await deliveries(db)).map((r) => `${r.network}:${r.status}`), ["youtube:queued"]);
  assert.equal(sent(calls, "sendVideo").length, 0); // no channel post
  assert.match(sent(calls, "sendMessage").at(-1).text, /YouTube: у черзі/);
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "publishing");
  const stored = JSON.parse((await db.prepare("SELECT body FROM promo_posts WHERE id = ?").bind(ID).first()).body);
  assert.deepEqual(stored.youtube_tags, metadata.youtube_tags);
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: "*/5 * * * *" });
  const request = calls.find((c) => c.url.includes("upload/youtube/v3/videos"));
  const sentMetadata = JSON.parse(request.body);
  assert.equal(sentMetadata.snippet.title, metadata.youtube_title);
  assert.equal(sentMetadata.snippet.description, metadata.caption);
  assert.equal(sentMetadata.snippet.defaultLanguage, "en");
  assert.equal(sentMetadata.snippet.defaultAudioLanguage, "en");
  assert.deepEqual(sentMetadata.snippet.tags, metadata.youtube_tags);
  assert.equal(sentMetadata.snippet.categoryId, "20");
  await worker.scheduled({ cron: "*/5 * * * *" });
  assert.deepEqual((await deliveries(db)).map((r) => `${r.network}:${r.status}`), ["youtube:published"]);
  assert.equal(sent(calls, "sendVideo").length, 0);
});

test("«Лише YouTube» without YouTube connected publishes nothing and says so", async (t) => {
  const { mf, db, calls } = await localWorker(t);
  await approveAndRun(mf, db, calls, "yt");
  assert.deepEqual(await deliveries(db), []);
  assert.equal(sent(calls, "sendVideo").length, 0);
  assert.match(sent(calls, "sendMessage").at(-1).text, /YouTube: не підключено/);
  assert.equal((await db.prepare("SELECT status FROM promo_posts WHERE id = ?").bind(ID).first()).status, "failed");
});

// A UTC minute `minutes` from now, as the packages carry it.
const minuteFromNow = (minutes) => new Date(Math.ceil((Date.now() + minutes * 60_000) / 60_000) * 60_000).toISOString().replace(".000Z", "Z");

async function scheduledYoutube(t, minutes) {
  const { mf, db, calls } = await localWorker(t);
  await connect(mf, calls, "youtube", "c1");
  const at = minuteFromNow(minutes);
  const metadata = { youtube_tags: ["Dota 2", "Wardly"], youtube_language: "uk", youtube_publish_at: at };
  await approveAndRun(mf, db, calls, "yt", metadata);
  const stored = JSON.parse((await db.prepare("SELECT body FROM promo_posts WHERE id = ?").bind(ID).first()).body);
  assert.equal(stored.youtube_publish_at, at);
  const worker = await mf.getWorker();
  await worker.scheduled({ cron: "*/5 * * * *" });
  await worker.scheduled({ cron: "*/5 * * * *" });
  assert.deepEqual((await deliveries(db)).map((r) => `${r.network}:${r.status}`), ["youtube:published"]);
  const init = JSON.parse(calls.find((c) => c.url.includes("upload/youtube/v3/videos")).body);
  return { at, init, report: sent(calls, "sendMessage").at(-1).text };
}

test("a package with a YouTube time is uploaded private and scheduled by YouTube", async (t) => {
  const { at, init, report } = await scheduledYoutube(t, 180);
  assert.equal(init.status.privacyStatus, "private");
  assert.equal(init.status.publishAt, at);
  assert.match(report, /✅ YouTube: опубліковано — https:\/\/youtube.com\/shorts\/vid1 · заплановано на \d\d\.\d\d \d\d:\d\d \(Київ\)/);
  assert.doesNotMatch(report, /зробив відео/);
});

test("a button pressed too close to the YouTube time publishes at once and says so", async (t) => {
  const { init, report } = await scheduledYoutube(t, 5);
  assert.equal(init.status.privacyStatus, "public");
  assert.equal(init.status.publishAt, undefined);
  assert.match(report, /час публікації вже минув — опубліковано одразу/);
});
