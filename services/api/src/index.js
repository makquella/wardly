// Wardly API (Cloudflare Worker). Stage 1 of docs/DATA_PLAN.md:
// problem reports sent from the launcher on the player's request.
//
//   GET    /health                  -> { ok }
//   GET    /v1/config               -> which uploads are switched on (a kill switch without a release)
//   POST   /v1/report               -> stores the report (R2 + a D1 row), answers { id: "R-XXXXXX" }
//   DELETE /v1/device/<install id>  -> deletes every report of that installation
//   POST   /v1/share                -> publishes a review (src/share.js), answers { id, url, delete_token }
//   GET    /v1/share/<id>           -> the shared review as JSON
//   DELETE /v1/share/<id>           -> deletes it (header x-delete-token)
//   GET    /r/<id>                  -> the shared review as a page (with an Open Graph preview)
//   POST   /v1/stats                -> the opt-in anonymous daily statistics (src/stats.js), one row per installation and day
//   PUT    /v1/transfer/<id>        -> keeps an encrypted history backup for 15 minutes (src/transfer.js)
//   POST   /v1/transfer/<id>/claim  -> hands it over (3 downloads at most)
//   DELETE /v1/transfer/<id>        -> the receiving launcher deletes it once imported
//   POST   /v1/session              -> keeps one anonymized match recording for 60 days in R2 (src/session.js; the body is the raw gzip,
//                                      the metadata in x-* headers; off without the REPORTS bucket), answers { id: "S-XXXXXX" }
//   GET    /v1/admin/sessions?split=tune|holdout -> latest recordings (same token)
//   GET    /v1/admin/session/<id>   -> one recording as gzip (same)
//   GET    /v1/admin/reports        -> latest reports (Bearer ADMIN_TOKEN; off without the secret)
//   GET    /v1/admin/report/<id>    -> one report as text (same)
//   GET    /v1/admin/stats?days=N   -> the statistics summed over the last N days (same)
//   POST   /v1/hit                  -> +1 visit of the site for a source (src/channels.js; the site sends it once per visit)
//   GET    /d/<source>[?os=linux|linux-pacman|linux-deb] -> +1 download for that source, then a redirect to the latest installer (Windows by default)
//   PUT    /v1/profile/<id>         -> publishes the player's profile card (src/profile.js; header x-profile-token)
//   POST   /v1/profiles             -> the cards of up to 50 friend codes { ids } -> { profiles: {id: card} }
//   DELETE /v1/profile/<id>         -> hides the card (same token)
//   GET    /p/<id>                  -> the card as a page to send to a chat
//   cron */5                        -> the OpenDota cache refresh (src/opendota-cache.js, up to 8 entries per run)
//   GET    /v1/opendota/<path>      -> public OpenDota reference data from R2 (heroStats, constants/items, heroes/<id>/itemPopularity,
//                                      heroes/<id>/matchups, scenarios/itemTimings?hero_id=<id>; nothing else; GET/HEAD; 503 without R2)
//   GET    /admin, /admin/app.js    -> the statistics page (src/admin-page.js; asks for the token, holds no data;
//                                      404 while ADMIN_TOKEN is not set)
//   cron                            -> deletes reports older than RETENTION_DAYS, expired shares, old rate counters,
//                                      statistics older than STATS_RETENTION_DAYS, source counts older than
//                                      CHANNEL_RETENTION_DAYS; on Mondays a stats note to Telegram
//
// Bindings: DB (D1), REPORTS (R2, optional: without it the gzipped report is
// kept in the D1 row, which is enough for the free tier's 5 GB; recordings
// need it: 20 MB does not fit a D1 row). Secrets (optional): TELEGRAM_BOT_TOKEN,
// TELEGRAM_CHAT_ID (a message with the report file to the developer), ADMIN_TOKEN.

import {
  LIMITS,
  RATE_PER_HOUR,
  RETENTION_DAYS,
  hourWindow,
  reportId,
  storageKey,
  summarize,
  telegramCaption,
  validateReport
} from "./report.js";
import {
  SHARE_DAYS,
  SHARE_LIMITS,
  SHARE_RATE_PER_HOUR,
  isShareId,
  renderMissingPage,
  renderSharePage,
  shareId,
  validateShare
} from "./share.js";
import {
  PROFILE_LIMITS,
  PROFILE_RATE_PER_HOUR,
  PROFILE_RETENTION_DAYS,
  friendCode,
  isProfileId,
  normalizeCode,
  renderMissingProfile,
  renderProfilePage,
  validateProfile
} from "./profile.js";
import {
  SESSION_DAILY_BYTES,
  SESSION_LIMITS,
  SESSION_RATE_PER_HOUR,
  SESSION_TOTAL_BYTES,
  SESSION_RETENTION_DAYS,
  checkMetaLine,
  firstLine,
  hasGzipMagic,
  isSessionId,
  sessionId,
  sessionKey,
  sessionNote,
  sessionSplit,
  validateSessionHeaders
} from "./session.js";
import { ADMIN_HEADERS, ADMIN_HTML, ADMIN_JS, ADMIN_SCRIPT_HEADERS } from "./admin-page.js";
import {
  STATS_ADMIN_MAX_DAYS,
  STATS_MAX_BYTES,
  STATS_RATE_PER_HOUR,
  STATS_RETENTION_DAYS,
  aggregateStats,
  isoDay,
  validateStats,
  weeklyStatsText
} from "./stats.js";
import {
  CHANNEL_MAX_SOURCES,
  CHANNEL_RATE_PER_HOUR,
  CHANNEL_RETENTION_DAYS,
  aggregateChannels,
  channelSource,
  latestInstaller
} from "./channels.js";
import { refreshOpenDotaCache, serveOpenDota } from "./opendota-cache.js";

const OPENDOTA_CRON = "*/5 * * * *"; // wrangler.toml [triggers]
import {
  TRANSFER_MAX_BYTES,
  TRANSFER_MINUTES,
  TRANSFER_RATE_PER_HOUR,
  TRANSFER_TRIES,
  isSealed,
  isTransferId
} from "./transfer.js";

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };
const HTML_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  // Styles are inline; images come from the site, Valve's CDN and Steam avatars; no scripts at all.
  "content-security-policy":
    "default-src 'none'; style-src 'unsafe-inline'; img-src https://luhovyimvp.dev https://cdn.cloudflare.steamstatic.com https://avatars.steamstatic.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function flag(value, fallback) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  return !["0", "false", "off", "no"].includes(String(value).toLowerCase());
}

// The share of installations that is asked to send recordings, 0..1.
function sample(value) {
  const number = Number(value);
  return value === undefined || value === null || value === "" || !Number.isFinite(number)
    ? 1
    : Math.min(Math.max(number, 0), 1);
}

export function config(env) {
  return {
    reports: flag(env.REPORTS_ENABLED, true),
    shares: flag(env.SHARES_ENABLED, true),
    transfers: flag(env.TRANSFERS_ENABLED, true),
    transfer_minutes: TRANSFER_MINUTES,
    share_days: SHARE_DAYS,
    stats: flag(env.STATS_ENABLED, true),
    channels: flag(env.CHANNELS_ENABLED, true),
    profiles: flag(env.PROFILES_ENABLED, true),
    // Recordings need R2 (20 MB does not fit a D1 row). The launcher asks a
    // `recordings_sample` share of installations, decided from its install id.
    recordings: flag(env.RECORDINGS_ENABLED, true) && Boolean(env.REPORTS),
    recordings_sample: sample(env.RECORDINGS_SAMPLE),
    recording_days: SESSION_RETENTION_DAYS,
    retention_days: RETENTION_DAYS
  };
}

// The device key (x-device-key, 64 hex) proves ownership of what a launcher
// uploaded; only its hash is stored. Older launchers send none: null.
const DEVICE_KEY = /^[a-f0-9]{64}$/;

async function ownerHash(request) {
  const key = String(request.headers.get("x-device-key") || "").toLowerCase();
  return DEVICE_KEY.test(key) ? sha256(`dac-device:${key}`) : null;
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

/** +1 for this hour; true while under the limit. */
async function allow(env, key, limit, now) {
  const row = await env.DB.prepare(
    "INSERT INTO rate (key, hour, count) VALUES (?1, ?2, 1) " +
      "ON CONFLICT(key, hour) DO UPDATE SET count = count + 1 RETURNING count"
  )
    .bind(key, hourWindow(now))
    .first();
  return Number(row?.count || 0) <= limit;
}

async function gzip(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function gunzipText(body) {
  const stream = body.pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

/** Removes the R2 objects of these rows (rows stored in D1 have no key). */
async function deleteObjects(env, rows) {
  const keys = rows.map((row) => row.r2_key).filter(Boolean);
  if (!env.REPORTS) {
    return;
  }
  for (let i = 0; i < keys.length; i += 1000) {
    await env.REPORTS.delete(keys.slice(i, i + 1000));
  }
}

async function notifyTelegram(env, id, report) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) {
    return;
  }
  const form = new FormData();
  form.append("chat_id", String(env.TELEGRAM_CHAT_ID));
  form.append("caption", telegramCaption(id, report));
  const file = `${report.note ? `Player note:\n${report.note}\n\n` : ""}${report.text}`;
  form.append("document", new Blob([file], { type: "text/plain" }), `${id}.txt`);
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`, {
    method: "POST",
    body: form
  });
  if (!response.ok) {
    console.log(`telegram: HTTP ${response.status}`);
  }
}

export async function handleReport(request, env, ctx, now = Date.now()) {
  if (!config(env).reports) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  const length = Number(request.headers.get("content-length") || 0);
  if (length > LIMITS.bodyBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  const raw = await request.text();
  if (raw.length > LIMITS.bodyBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const checked = validateReport(body);
  if (!checked.ok) {
    return json({ ok: false, code: checked.code }, checked.status);
  }
  const report = checked.report;
  const address = await sha256(`dac-rate:${request.headers.get("cf-connecting-ip") || "unknown"}`);
  const underLimit =
    (await allow(env, `report:install:${report.installId}`, RATE_PER_HOUR.install, now)) &&
    (await allow(env, `report:address:${address}`, RATE_PER_HOUR.address, now));
  if (!underLimit) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }

  const id = reportId(crypto.getRandomValues(new Uint8Array(6)));
  const date = new Date(now);
  const stored = `${report.note ? `Player note:\n${report.note}\n\n` : ""}${report.text}`;
  const packed = await gzip(stored);
  let key = null;
  let inline = null;
  if (env.REPORTS) {
    key = storageKey(id, date);
    await env.REPORTS.put(key, packed, {
      httpMetadata: { contentType: "text/plain; charset=utf-8", contentEncoding: "gzip" },
      customMetadata: { id, version: report.version, install: report.installId }
    });
  } else if (packed.byteLength > LIMITS.rowBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  } else {
    inline = packed;
  }
  await env.DB.prepare(
    "INSERT INTO reports (id, created_at, install_id, version, os, lang, size, summary, r2_key, body, owner_hash) " +
      "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)"
  )
    .bind(id, now, report.installId, report.version, report.os, report.lang, stored.length, summarize(report), key, inline, await ownerHash(request))
    .run();
  ctx.waitUntil(notifyTelegram(env, id, report).catch((error) => console.log(`telegram: ${error.message}`)));
  return json({ ok: true, id, retention_days: RETENTION_DAYS }, 201);
}

async function notifySession(env, text) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) {
    return;
  }
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: String(env.TELEGRAM_CHAT_ID), text })
  });
  if (!response.ok) {
    console.log(`telegram: HTTP ${response.status}`);
  }
}

// A salted hash of the installation id, only for the hourly rate limit: the
// raw id is never stored with a recording, so it cannot be joined to a profile.
function sessionInstallHash(installId) {
  return sha256(`dac-session:${installId}`);
}

const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));

export async function handleSession(request, env, ctx, now = Date.now(), random = randomBytes) {
  if (!config(env).recordings) {
    return json({ ok: false, code: env.REPORTS ? "disabled" : "storage_unavailable" }, 503);
  }
  // 1. Headers and metadata: nothing here costs a query or counts against a limit.
  const checked = validateSessionHeaders(request.headers);
  if (!checked.ok) {
    return json({ ok: false, code: checked.code }, checked.status);
  }
  const { meta } = checked;
  // 2. The device key: it owns the recording ("Delete my data"). Launchers from
  // 0.53.54 on always send it.
  const owner = await ownerHash(request);
  if (!owner) {
    return json({ ok: false, code: "no_device_key" }, 400);
  }
  // 3. Storage caps from the stored sizes, this upload included. Uploads that
  // run at the same moment all see the same totals, so the caps can be
  // exceeded by a few files: acceptable against R2's free 10 GB.
  const stored = await env.DB.prepare(
    "SELECT COALESCE(SUM(CASE WHEN created_at >= ?1 THEN size END), 0) AS day, COALESCE(SUM(size), 0) AS total FROM sessions"
  )
    .bind(now - 24 * 3_600_000)
    .first();
  if (
    Number(stored?.day || 0) + meta.length > SESSION_DAILY_BYTES ||
    Number(stored?.total || 0) + meta.length > SESSION_TOTAL_BYTES
  ) {
    return json({ ok: false, code: "storage_full" }, 507);
  }
  // 4. Rate limits; only an upload that can actually be taken uses them up.
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  const installHash = await sessionInstallHash(meta.installId);
  const underLimit =
    (await allow(env, `session:install:${installHash}`, SESSION_RATE_PER_HOUR.install, now)) &&
    (await allow(env, `session:address:${address}`, SESSION_RATE_PER_HOUR.address, now));
  if (!underLimit) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  // 5. The body.
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length > SESSION_LIMITS.bodyBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  // 6. The gzip stream and its first line.
  if (!hasGzipMagic(body)) {
    return json({ ok: false, code: "bad_recording" }, 400);
  }
  const line = checkMetaLine(await firstLine(body));
  if (!line.ok) {
    return json({ ok: false, code: line.code }, line.status);
  }
  // The index row goes first: a primary-key collision fails before any put and
  // never overwrites another player's file. The id is drawn once more on a collision.
  let id = "";
  let key = "";
  let split = "";
  let indexed = false;
  for (let attempt = 0; attempt < 2 && !indexed; attempt += 1) {
    id = sessionId(random(6));
    key = sessionKey(id, new Date(now));
    split = await sessionSplit(id);
    try {
      await env.DB.prepare(
        "INSERT INTO sessions (id, created_at, owner_hash, install_hash, version, hero, minutes, size, r2_key, split) " +
          "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)"
      )
        .bind(id, now, owner, installHash, meta.version, meta.hero, meta.minutes, body.length, key, split)
        .run();
      indexed = true;
    } catch (error) {
      console.log(`session: insert failed (${error.message})`);
    }
  }
  if (!indexed) {
    return json({ ok: false, code: "storage_error" }, 500);
  }
  try {
    await env.REPORTS.put(key, body, {
      httpMetadata: { contentType: "application/gzip" },
      customMetadata: { id, version: meta.version }
    });
  } catch (error) {
    console.log(`session: put failed (${error.message})`);
    await env.DB.prepare("DELETE FROM sessions WHERE id = ?1").bind(id).run().catch(() => {});
    return json({ ok: false, code: "storage_error" }, 500);
  }
  ctx.waitUntil(notifySession(env, sessionNote(id, meta, split, body.length)).catch((error) => console.log(`telegram: ${error.message}`)));
  return json({ ok: true, id, retention_days: SESSION_RETENTION_DAYS }, 201);
}

async function readShare(env, id, now) {
  const row = await env.DB.prepare("SELECT body, expires_at, lang FROM shares WHERE id = ?1").bind(id).first();
  if (!row || Number(row.expires_at) <= now) {
    return null;
  }
  const text = await gunzipText(new Blob([new Uint8Array(row.body)]).stream());
  return { review: JSON.parse(text), expiresAt: Number(row.expires_at) };
}

export async function handleShare(request, env, now = Date.now()) {
  if (!config(env).shares) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  const raw = await request.text();
  if (raw.length > SHARE_LIMITS.bodyBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const checked = validateShare(body);
  if (!checked.ok) {
    return json({ ok: false, code: checked.code }, checked.status);
  }
  const { installId, version, review } = checked.share;
  const address = await sha256(`dac-rate:${request.headers.get("cf-connecting-ip") || "unknown"}`);
  const underLimit =
    (await allow(env, `share:install:${installId}`, SHARE_RATE_PER_HOUR.install, now)) &&
    (await allow(env, `share:address:${address}`, SHARE_RATE_PER_HOUR.address, now));
  if (!underLimit) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  const id = shareId(crypto.getRandomValues(new Uint8Array(10)));
  const token = [...crypto.getRandomValues(new Uint8Array(24))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const expiresAt = now + SHARE_DAYS * 24 * 3_600_000;
  await env.DB.prepare(
    "INSERT INTO shares (id, created_at, expires_at, install_id, delete_hash, lang, version, body, owner_hash) " +
      "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"
  )
    .bind(id, now, expiresAt, installId, await sha256(`dac-share:${token}`), review.lang, version, await gzip(JSON.stringify(review)), await ownerHash(request))
    .run();
  // SHARE_ORIGIN: the site's own address when a Workers route sends /r/* there
  // (luhovyimvp.dev/r/<id>); the pages work on the API's address too.
  // Launchers before 0.9.0 open only links on the API's own address.
  const siteLinks = /^https:\/\/[a-z0-9.-]+$/.test(String(env.SHARE_ORIGIN || "")) && versionAtLeast(version, SITE_LINKS_SINCE);
  const origin = siteLinks ? env.SHARE_ORIGIN : new URL(request.url).origin;
  const url = `${origin}/r/${id}`;
  return json({ ok: true, id, url, delete_token: token, expires_at: expiresAt }, 201);
}

const SITE_LINKS_SINCE = [0, 9, 0];

/** "0.9.1" >= [0, 9, 0]; anything that is not a version is older. */
export function versionAtLeast(version, [major, minor, patch]) {
  const parts = String(version || "").match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!parts) {
    return false;
  }
  const [a, b, c] = parts.slice(1).map(Number);
  return a !== major ? a > major : b !== minor ? b > minor : c >= patch;
}

export async function deleteShare(request, id, env) {
  const token = request.headers.get("x-delete-token") || "";
  const row = await env.DB.prepare("SELECT delete_hash FROM shares WHERE id = ?1").bind(id).first();
  if (!row) {
    return json({ ok: false, code: "not_found" }, 404);
  }
  if (!token || (await sha256(`dac-share:${token}`)) !== row.delete_hash) {
    return json({ ok: false, code: "forbidden" }, 403);
  }
  await env.DB.prepare("DELETE FROM shares WHERE id = ?1").bind(id).run();
  return json({ ok: true });
}

export async function sharePage(request, id, env, now = Date.now()) {
  const shared = isShareId(id) ? await readShare(env, id, now) : null;
  // Ukrainian for a Ukrainian, Russian or Belarusian browser, as in the launcher.
  const lang = /^(uk|ru|be)(-|,|;|$)/i.test(request.headers.get("accept-language") || "") ? "uk" : "en";
  if (!shared) {
    return new Response(renderMissingPage(lang), { status: 404, headers: { ...HTML_HEADERS, "cache-control": "no-store" } });
  }
  const html = renderSharePage(shared.review, { url: request.url, expiresAt: shared.expiresAt });
  return new Response(html, { headers: { ...HTML_HEADERS, "cache-control": "public, max-age=300" } });
}

export async function putProfile(request, id, env, now = Date.now()) {
  if (!config(env).profiles) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  if (!isProfileId(id)) {
    return json({ ok: false, code: "bad_id" }, 400);
  }
  const token = request.headers.get("x-profile-token") || "";
  if (!/^[a-f0-9]{32,64}$/.test(token)) {
    return json({ ok: false, code: "bad_token" }, 400);
  }
  const raw = await request.text();
  if (raw.length > PROFILE_LIMITS.bodyBytes) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const checked = validateProfile(body);
  if (!checked.ok) {
    return json({ ok: false, code: checked.code }, checked.status);
  }
  const { installId, version, profile } = checked.put;
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  const underLimit =
    (await allow(env, `profile:install:${installId}`, PROFILE_RATE_PER_HOUR.install, now)) &&
    (await allow(env, `profile:address:${address}`, PROFILE_RATE_PER_HOUR.address, now));
  if (!underLimit) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  const hash = await sha256(`dac-profile:${token}`);
  const row = await env.DB.prepare("SELECT token_hash FROM profiles WHERE id = ?1").bind(id).first();
  if (row && row.token_hash !== hash) {
    // Someone else's code (or a lost token): the launcher picks a new id.
    return json({ ok: false, code: "taken" }, 409);
  }
  const owner = await ownerHash(request);
  if (row) {
    // A card published before device keys gets its owner on the next publish.
    await env.DB.prepare(
      "UPDATE profiles SET updated_at = ?2, version = ?3, body = ?4, owner_hash = COALESCE(owner_hash, ?5) WHERE id = ?1"
    )
      .bind(id, now, version, JSON.stringify(profile), owner)
      .run();
  } else {
    await env.DB.prepare(
      "INSERT INTO profiles (id, created_at, updated_at, install_id, token_hash, version, body, owner_hash) VALUES (?1, ?2, ?2, ?3, ?4, ?5, ?6, ?7)"
    )
      .bind(id, now, installId, hash, version, JSON.stringify(profile), owner)
      .run();
  }
  // The API's own address: /p/* on the site needs a Workers route like /r/*
  // (PROFILE_ORIGIN once it is added in the Cloudflare dashboard).
  const origin = /^https:\/\/[a-z0-9.-]+$/.test(String(env.PROFILE_ORIGIN || "")) ? env.PROFILE_ORIGIN : new URL(request.url).origin;
  return json({ ok: true, id, code: friendCode(id), url: `${origin}/p/${id}` }, row ? 200 : 201);
}

export async function readProfiles(request, env, now = Date.now()) {
  if (!config(env).profiles) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  let body;
  try {
    body = JSON.parse(await request.text());
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const ids = [...new Set((Array.isArray(body?.ids) ? body.ids : []).map(normalizeCode).filter(Boolean))].slice(
    0,
    PROFILE_LIMITS.batch
  );
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  if (!(await allow(env, `profile:read:${address}`, PROFILE_RATE_PER_HOUR.read, now))) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  const profiles = {};
  if (ids.length) {
    const marks = ids.map((_, i) => `?${i + 1}`).join(", ");
    const { results } = await env.DB.prepare(`SELECT id, updated_at, body FROM profiles WHERE id IN (${marks})`)
      .bind(...ids)
      .all();
    for (const row of results || []) {
      profiles[row.id] = { ...JSON.parse(row.body), updated_at: Number(row.updated_at), code: friendCode(row.id) };
    }
  }
  return json({ ok: true, profiles });
}

export async function deleteProfile(request, id, env) {
  const token = request.headers.get("x-profile-token") || "";
  const row = isProfileId(id) ? await env.DB.prepare("SELECT token_hash FROM profiles WHERE id = ?1").bind(id).first() : null;
  if (!row) {
    return json({ ok: false, code: "not_found" }, 404);
  }
  if (!token || (await sha256(`dac-profile:${token}`)) !== row.token_hash) {
    return json({ ok: false, code: "forbidden" }, 403);
  }
  await env.DB.prepare("DELETE FROM profiles WHERE id = ?1").bind(id).run();
  return json({ ok: true });
}

export async function profilePage(request, id, env) {
  const lang = (request.headers.get("accept-language") || "").toLowerCase().startsWith("en") ? "en" : "uk";
  const row = isProfileId(id) ? await env.DB.prepare("SELECT body FROM profiles WHERE id = ?1").bind(id).first() : null;
  if (!row) {
    return new Response(renderMissingProfile(lang), { status: 404, headers: { ...HTML_HEADERS, "cache-control": "no-store" } });
  }
  const html = renderProfilePage(JSON.parse(row.body), { id, url: request.url });
  return new Response(html, { headers: { ...HTML_HEADERS, "cache-control": "public, max-age=300" } });
}

function clientAddress(request) {
  return request.headers.get("cf-connecting-ip") || "unknown";
}

export async function putTransfer(request, id, env, now = Date.now()) {
  if (!config(env).transfers) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  if (!isTransferId(id)) {
    return json({ ok: false, code: "bad_id" }, 400);
  }
  const installId = String(request.headers.get("x-install-id") || "").toLowerCase();
  if (!/^[a-z0-9-]{8,64}$/.test(installId)) {
    return json({ ok: false, code: "bad_install_id" }, 400);
  }
  const length = Number(request.headers.get("content-length") || 0);
  if (length > TRANSFER_MAX_BYTES) {
    return json({ ok: false, code: "too_big" }, 413);
  }
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length > TRANSFER_MAX_BYTES) {
    return json({ ok: false, code: "too_big" }, 413);
  }
  if (!isSealed(body)) {
    return json({ ok: false, code: "bad_body" }, 400);
  }
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  const allowed =
    (await allow(env, `transfer:install:${installId}`, TRANSFER_RATE_PER_HOUR.install, now)) &&
    (await allow(env, `transfer:address:${address}`, TRANSFER_RATE_PER_HOUR.address, now));
  if (!allowed) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  await env.DB.prepare("DELETE FROM transfers WHERE expires_at < ?1").bind(now).run();
  const expiresAt = now + TRANSFER_MINUTES * 60_000;
  const deleteToken = String(request.headers.get("x-delete-token") || "").toLowerCase();
  const deleteHash = TRANSFER_DELETE_TOKEN.test(deleteToken) ? await sha256(`dac-transfer:${deleteToken}`) : null;
  const inserted = await env.DB.prepare(
    "INSERT INTO transfers (id, created_at, expires_at, install_id, size, body, owner_hash, delete_hash) " +
      "VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8) ON CONFLICT(id) DO NOTHING RETURNING id"
  )
    .bind(id, now, expiresAt, installId, body.length, body, await ownerHash(request), deleteHash)
    .first();
  if (!inserted) {
    return json({ ok: false, code: "taken" }, 409);
  }
  return json({ ok: true, id, expires_at: expiresAt }, 201);
}

export async function claimTransfer(request, id, env, now = Date.now()) {
  if (!config(env).transfers) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  // Every claim counts, found or not: guessing ids is slow.
  if (!(await allow(env, `transfer:claim:${address}`, TRANSFER_RATE_PER_HOUR.claim, now))) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  if (!isTransferId(id)) {
    return json({ ok: false, code: "not_found" }, 404);
  }
  // Claim and increment are one D1 statement; only a successful claimant gets
  // ciphertext. Cleanup must not delete a fresh replacement with the same id.
  const row = await env.DB.prepare(
    "UPDATE transfers SET tries = tries + 1 WHERE id = ?1 AND tries < ?2 AND expires_at >= ?3 RETURNING body, tries"
  ).bind(id, TRANSFER_TRIES, now).first();
  if (!row) {
    await env.DB.prepare(
      "DELETE FROM transfers WHERE id = ?1 AND (expires_at < ?2 OR tries >= ?3)"
    ).bind(id, now, TRANSFER_TRIES).run();
    return json({ ok: false, code: "not_found" }, 404);
  }
  if (Number(row.tries) >= TRANSFER_TRIES) {
    await env.DB.prepare("DELETE FROM transfers WHERE id = ?1 AND tries >= ?2")
      .bind(id, TRANSFER_TRIES).run();
  }
  return new Response(new Uint8Array(row.body), {
    headers: { "content-type": "application/octet-stream", "cache-control": "no-store" }
  });
}

// A transfer sent with a delete token is cancelled only with that token (the
// receiver derives it from the whole code); one from an older launcher keeps the
// id-only delete under the claim rate limit.
const TRANSFER_DELETE_TOKEN = /^[a-f0-9]{64}$/;

export async function deleteTransfer(request, id, env, now = Date.now()) {
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  if (!(await allow(env, `transfer:claim:${address}`, TRANSFER_RATE_PER_HOUR.claim, now))) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  if (!isTransferId(id)) {
    return json({ ok: true });
  }
  const token = String(request.headers.get("x-delete-token") || "").toLowerCase();
  const hash = TRANSFER_DELETE_TOKEN.test(token) ? await sha256(`dac-transfer:${token}`) : "";
  await env.DB.prepare("DELETE FROM transfers WHERE id = ?1 AND (delete_hash IS NULL OR delete_hash = ?2)")
    .bind(id, hash)
    .run();
  const kept = await env.DB.prepare("SELECT 1 AS kept FROM transfers WHERE id = ?1").bind(id).first();
  return kept ? json({ ok: false, code: "forbidden" }, 403) : json({ ok: true });
}

function statsHash(installId) {
  return sha256(`dac-stats:${installId}`);
}

export async function handleStats(request, env, now = Date.now()) {
  if (!config(env).stats) {
    return json({ ok: false, code: "disabled" }, 503);
  }
  const raw = await request.text();
  if (raw.length > STATS_MAX_BYTES) {
    return json({ ok: false, code: "too_large" }, 413);
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const checked = validateStats(body, now);
  if (!checked.ok) {
    return json({ ok: false, code: checked.code }, checked.status);
  }
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  // The install id is kept only as the salted hash, the rate counter included.
  const installHash = await statsHash(checked.installId);
  const underLimit =
    (await allow(env, `stats:install:${installHash}`, STATS_RATE_PER_HOUR.install, now)) &&
    (await allow(env, `stats:address:${address}`, STATS_RATE_PER_HOUR.address, now));
  if (!underLimit) {
    return json({ ok: false, code: "rate_limited" }, 429);
  }
  // One row per installation and day: sending the same day again replaces it.
  await env.DB.prepare(
    "INSERT INTO daily_stats (install_hash, day, created_at, version, body) VALUES (?1, ?2, ?3, ?4, ?5) " +
      "ON CONFLICT(install_hash, day) DO UPDATE SET created_at = excluded.created_at, version = excluded.version, body = excluded.body"
  )
    .bind(installHash, checked.day, now, checked.version, JSON.stringify(checked.row))
    .run();
  return json({ ok: true, day: checked.day, retention_days: STATS_RETENTION_DAYS }, 201);
}

/** +1 visit or download for a source today; a flood of new names counts as "other". */
async function countChannel(env, src, kind, now) {
  const day = isoDay(now);
  const seen = await env.DB.prepare(
    "SELECT COUNT(*) AS sources, SUM(src = ?2) AS known FROM channel_counts WHERE day = ?1"
  )
    .bind(day, src)
    .first();
  const name = !Number(seen?.known) && Number(seen?.sources) >= CHANNEL_MAX_SOURCES ? "other" : src;
  await env.DB.prepare(
    "INSERT INTO channel_counts (day, src, visits, downloads) VALUES (?1, ?2, ?3, ?4) " +
      "ON CONFLICT(day, src) DO UPDATE SET visits = visits + excluded.visits, downloads = downloads + excluded.downloads"
  )
    .bind(day, name, kind === "visit" ? 1 : 0, kind === "download" ? 1 : 0)
    .run();
}

async function underChannelLimit(request, env, kind, now) {
  const address = await sha256(`dac-rate:${clientAddress(request)}`);
  return allow(env, `channel:${kind}:${address}`, CHANNEL_RATE_PER_HOUR[kind], now);
}

// The site sends { src } with navigator.sendBeacon (text/plain: no preflight),
// so the answer carries no data and needs no CORS headers.
export async function handleHit(request, env, now = Date.now()) {
  if (!config(env).channels) {
    return new Response(null, { status: 204 });
  }
  const raw = await request.text();
  let src = null;
  if (raw.length <= 200) {
    try {
      src = channelSource(JSON.parse(raw).src);
    } catch {
      src = null;
    }
  }
  if (!src) {
    return json({ ok: false, code: "bad_source" }, 400);
  }
  if (await underChannelLimit(request, env, "visit", now)) {
    await countChannel(env, src, "visit", now);
  }
  return new Response(null, { status: 204 });
}

// Always redirects: counting is best effort and never blocks the download.
// Only a GET counts: a HEAD (link checkers, previews) gets the redirect alone.
export async function handleDownload(request, src, env, now = Date.now(), fetchImpl = fetch) {
  const name = channelSource(src) || "site";
  if (config(env).channels && request.method === "GET") {
    try {
      if (await underChannelLimit(request, env, "download", now)) {
        await countChannel(env, name, "download", now);
      }
    } catch (error) {
      console.log(`download count: ${error.message}`);
    }
  }
  return new Response(null, {
    status: 302,
    headers: { location: await latestInstaller(fetchImpl, now, new URL(request.url).searchParams.get("os")), "cache-control": "no-store", "referrer-policy": "no-referrer" }
  });
}

// The daily statistics hold finished days only (the launcher sends yesterday),
// so `days` back from today covers `days` of them. Source counts start today:
// the admin page shows the last `days` dates with today; the weekly note
// (`finished`) the `days` dates before today, the same week as the statistics.
async function statsSummary(env, days, now, { finished = false } = {}) {
  const DAY = 24 * 3_600_000;
  const { results } = await env.DB.prepare("SELECT install_hash, day, version, body FROM daily_stats WHERE day >= ?1")
    .bind(isoDay(now - days * DAY))
    .all();
  const summary = aggregateStats(results || []);
  const from = isoDay(now - (finished ? days : days - 1) * DAY);
  const until = isoDay(now + (finished ? 0 : DAY));
  const channels = await env.DB.prepare(
    "SELECT day, src, visits, downloads FROM channel_counts WHERE day >= ?1 AND day < ?2"
  )
    .bind(from, until)
    .all();
  summary.channels = aggregateChannels(channels.results || []);
  return summary;
}

async function adminStats(url, env, now = Date.now()) {
  const days = Math.min(Math.max(Number.parseInt(url.searchParams.get("days") || "30", 10) || 30, 1), STATS_ADMIN_MAX_DAYS);
  return json({ ok: true, days, stats: await statsSummary(env, days, now) });
}

export async function sendWeeklyStats(env, now = Date.now()) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID || new Date(now).getUTCDay() !== 1) {
    return false;
  }
  const summary = await statsSummary(env, 7, now, { finished: true });
  if (!summary.rows && !summary.channels.length) {
    return false;
  }
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: String(env.TELEGRAM_CHAT_ID), text: weeklyStatsText(summary) })
  });
  return response.ok;
}

// «Видалити мої дані на сервері». With the device key: everything that key
// uploaded plus this installation's rows from before device keys. Without it
// (older launchers): only the rows without an owner, as before.
const OWNED = "(owner_hash = ?2 OR (install_id = ?1 AND owner_hash IS NULL))";

export async function deleteDevice(request, installId, env) {
  const id = String(installId || "").toLowerCase();
  if (!/^[a-z0-9-]{8,64}$/.test(id)) {
    return json({ ok: false, code: "bad_install_id" }, 400);
  }
  // "" never equals a stored hash, so a request without a key matches only
  // the rows without an owner.
  const owner = (await ownerHash(request)) || "";
  const { results } = await env.DB.prepare(`SELECT r2_key FROM reports WHERE ${OWNED}`).bind(id, owner).all();
  const rows = results || [];
  await deleteObjects(env, rows);
  // Recordings carry no installation id: only the device key finds them, and
  // their R2 objects go before the index rows.
  if (owner) {
    const recordings = (await env.DB.prepare("SELECT r2_key FROM sessions WHERE owner_hash = ?1").bind(owner).all()).results || [];
    await deleteObjects(env, recordings);
    await env.DB.prepare("DELETE FROM sessions WHERE owner_hash = ?1").bind(owner).run();
  }
  for (const table of ["reports", "shares", "transfers", "profiles"]) {
    await env.DB.prepare(`DELETE FROM ${table} WHERE ${OWNED}`).bind(id, owner).run();
  }
  await env.DB.prepare("DELETE FROM daily_stats WHERE install_hash = ?1").bind(await statsHash(id)).run();
  return json({ ok: true, deleted: rows.length });
}

// The secret comes from a repository secret pasted by hand, which can carry a
// trailing newline or space; the admin page trims what is typed. Both sides are
// compared without the whitespace around them.
function isAdmin(request, env) {
  const token = String(env.ADMIN_TOKEN || "").trim();
  const header = String(request.headers.get("authorization") || "");
  return Boolean(token) && header.startsWith("Bearer ") && header.slice(7).trim() === token;
}

async function adminList(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, created_at, version, os, lang, size, summary FROM reports ORDER BY created_at DESC LIMIT 50"
  ).all();
  return json({ ok: true, reports: results || [] });
}

async function adminReport(id, env) {
  const row = await env.DB.prepare("SELECT r2_key, body FROM reports WHERE id = ?1").bind(id).first();
  let packed = null;
  if (row?.body) {
    packed = new Blob([new Uint8Array(row.body)]).stream();
  } else if (row?.r2_key && env.REPORTS) {
    packed = (await env.REPORTS.get(row.r2_key))?.body || null;
  }
  if (!packed) {
    return json({ ok: false, code: "not_found" }, 404);
  }
  return new Response(await gunzipText(packed), {
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" }
  });
}

async function adminSessions(url, env) {
  const split = url.searchParams.get("split");
  const filtered = split === "tune" || split === "holdout";
  const statement = env.DB.prepare(
    "SELECT id, created_at, version, hero, minutes, size, split FROM sessions " +
      `${filtered ? "WHERE split = ?1 " : ""}ORDER BY created_at DESC LIMIT 200`
  );
  const { results } = await (filtered ? statement.bind(split) : statement).all();
  return json({ ok: true, sessions: results || [] });
}

async function adminSession(id, env) {
  const row = await env.DB.prepare("SELECT r2_key FROM sessions WHERE id = ?1").bind(id).first();
  const object = row?.r2_key && env.REPORTS ? await env.REPORTS.get(row.r2_key) : null;
  if (!object) {
    return json({ ok: false, code: "not_found" }, 404);
  }
  return new Response(object.body, {
    headers: {
      "content-type": "application/gzip",
      "content-disposition": `attachment; filename="${id}.jsonl.gz"`,
      "cache-control": "no-store"
    }
  });
}

// D1 binds at most 100 parameters per statement, so old reports go in batches.
const CLEANUP_BATCH = 100;
const CLEANUP_MAX_BATCHES = 50;

// Rows of `table` older than `cutoff` with their R2 objects; returns how many.
async function purgeOld(env, table, cutoff) {
  let removed = 0;
  for (let batch = 0; batch < CLEANUP_MAX_BATCHES; batch += 1) {
    const { results } = await env.DB.prepare(
      `SELECT id, r2_key FROM ${table} WHERE created_at < ?1 LIMIT ${CLEANUP_BATCH}`
    )
      .bind(cutoff)
      .all();
    const rows = results || [];
    if (!rows.length) {
      break;
    }
    // Objects first, then exactly those index rows: a failure in between
    // leaves rows that the next run deletes again, never unindexed objects.
    await deleteObjects(env, rows);
    const marks = rows.map((_, i) => `?${i + 1}`).join(", ");
    await env.DB.prepare(`DELETE FROM ${table} WHERE id IN (${marks})`)
      .bind(...rows.map((row) => row.id))
      .run();
    removed += rows.length;
    if (rows.length < CLEANUP_BATCH) {
      break;
    }
  }
  return removed;
}

export async function cleanup(env, now = Date.now()) {
  const removed = await purgeOld(env, "reports", now - RETENTION_DAYS * 24 * 3_600_000);
  await purgeOld(env, "sessions", now - SESSION_RETENTION_DAYS * 24 * 3_600_000);
  await env.DB.prepare("DELETE FROM shares WHERE expires_at < ?1").bind(now).run();
  await env.DB.prepare("DELETE FROM transfers WHERE expires_at < ?1").bind(now).run();
  await env.DB.prepare("DELETE FROM profiles WHERE updated_at < ?1")
    .bind(now - PROFILE_RETENTION_DAYS * 24 * 3_600_000)
    .run();
  await env.DB.prepare("DELETE FROM daily_stats WHERE day < ?1")
    .bind(isoDay(now - STATS_RETENTION_DAYS * 24 * 3_600_000))
    .run();
  await env.DB.prepare("DELETE FROM channel_counts WHERE day < ?1")
    .bind(isoDay(now - CHANNEL_RETENTION_DAYS * 24 * 3_600_000))
    .run();
  await env.DB.prepare("DELETE FROM rate WHERE hour < ?1").bind(hourWindow(now) - 48).run();
  return removed;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    try {
      if (request.method === "GET" && (path === "/" || path === "/health")) {
        return json({ ok: true, service: "dota-ai-coach-api" });
      }
      if (request.method === "GET" && path === "/v1/config") {
        return json(config(env));
      }
      if (request.method === "POST" && path === "/v1/report") {
        return await handleReport(request, env, ctx);
      }
      if (request.method === "POST" && path === "/v1/session") {
        return await handleSession(request, env, ctx);
      }
      if (request.method === "POST" && path === "/v1/stats") {
        return await handleStats(request, env);
      }
      if (request.method === "POST" && path === "/v1/hit") {
        return await handleHit(request, env);
      }
      if (path.startsWith("/v1/opendota/")) {
        return await serveOpenDota(request, env, ctx);
      }
      const download = path.match(/^\/d(?:\/([^/]{1,40}))?$/);
      if (download && (request.method === "GET" || request.method === "HEAD")) {
        return await handleDownload(request, download[1], env);
      }
      if (request.method === "POST" && path === "/v1/share") {
        return await handleShare(request, env);
      }
      const share = path.match(/^\/v1\/share\/([a-z0-9]{1,20})$/);
      if (share && request.method === "DELETE") {
        return await deleteShare(request, share[1], env);
      }
      if (share && request.method === "GET") {
        const shared = isShareId(share[1]) ? await readShare(env, share[1], Date.now()) : null;
        return shared
          ? json({ ok: true, review: shared.review, expires_at: shared.expiresAt })
          : json({ ok: false, code: "not_found" }, 404);
      }
      const transfer = path.match(/^\/v1\/transfer\/([^/]{1,8})(\/claim)?$/);
      if (transfer && request.method === "PUT" && !transfer[2]) {
        return await putTransfer(request, transfer[1], env);
      }
      if (transfer && request.method === "POST" && transfer[2]) {
        return await claimTransfer(request, transfer[1], env);
      }
      if (transfer && request.method === "DELETE" && !transfer[2]) {
        return await deleteTransfer(request, transfer[1], env);
      }
      const profile = path.match(/^\/v1\/profile\/([^/]{1,20})$/);
      if (profile && request.method === "PUT") {
        return await putProfile(request, profile[1], env);
      }
      if (profile && request.method === "DELETE") {
        return await deleteProfile(request, profile[1], env);
      }
      if (request.method === "POST" && path === "/v1/profiles") {
        return await readProfiles(request, env);
      }
      const profileMatch = path.match(/^\/p\/([^/]{1,20})$/);
      if (profileMatch && (request.method === "GET" || request.method === "HEAD")) {
        return await profilePage(request, profileMatch[1], env);
      }
      const pageMatch = path.match(/^\/r\/([^/]{1,40})$/);
      if (pageMatch && (request.method === "GET" || request.method === "HEAD")) {
        return await sharePage(request, pageMatch[1], env);
      }
      const device = path.match(/^\/v1\/device\/([^/]+)$/);
      if (request.method === "DELETE" && device) {
        return await deleteDevice(request, decodeURIComponent(device[1]), env);
      }
      if (request.method === "GET" && (path === "/admin" || path === "/admin/app.js")) {
        if (!env.ADMIN_TOKEN) {
          return json({ ok: false, code: "not_found" }, 404);
        }
        return path === "/admin"
          ? new Response(ADMIN_HTML, { headers: ADMIN_HEADERS })
          : new Response(ADMIN_JS, { headers: ADMIN_SCRIPT_HEADERS });
      }
      if (path.startsWith("/v1/admin/")) {
        if (!isAdmin(request, env)) {
          return json({ ok: false, code: "not_found" }, 404);
        }
        if (request.method === "GET" && path === "/v1/admin/reports") {
          return await adminList(env);
        }
        if (request.method === "GET" && path === "/v1/admin/sessions") {
          return await adminSessions(url, env);
        }
        const recording = path.match(/^\/v1\/admin\/session\/(S-[A-Z0-9]{6})$/);
        if (request.method === "GET" && recording && isSessionId(recording[1])) {
          return await adminSession(recording[1], env);
        }
        if (request.method === "GET" && path === "/v1/admin/stats") {
          return await adminStats(url, env);
        }
        const one = path.match(/^\/v1\/admin\/report\/(R-[A-Z0-9]{6})$/);
        if (request.method === "GET" && one) {
          return await adminReport(one[1], env);
        }
      }
      return json({ ok: false, code: "not_found" }, 404);
    } catch (error) {
      console.log(`error: ${error.stack || error.message}`);
      return json({ ok: false, code: "internal" }, 500);
    }
  },

  async scheduled(event, env, ctx) {
    if (event?.cron === OPENDOTA_CRON) {
      // Every five minutes: the shared OpenDota reference cache (src/opendota-cache.js).
      ctx.waitUntil(refreshOpenDotaCache(env).catch((error) => console.log(`opendota cache: ${error.name}`)));
      return;
    }
    ctx.waitUntil(cleanup(env).then((count) => console.log(`cleanup: ${count} old reports`)));
    ctx.waitUntil(sendWeeklyStats(env).catch((error) => console.log(`weekly stats: ${error.message}`)));
  }
};
