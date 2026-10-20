// Wardly Marketing Engine, the cloud half (docs/MARKETING_ENGINE.md).
//
//   POST /v1/admin/promo                     -> registers a package (Bearer ADMIN_TOKEN), answers its media key
//   PUT  /v1/admin/promo/<id>/<file>         -> video.mp4 or cover.jpg into R2 (same token)
//   GET  /v1/admin/promo                     -> posts with their numbers (the workflow's format weights)
//   GET  /m/<media key>/<file>               -> the media, public while the post is not rejected or expired
//                                               (Metricool fetches the video from here)
//   POST /v1/telegram/webhook                -> the bot's updates; only with the webhook secret header
//   GET  /oauth/<network>/callback           -> the end of /connect <network> (YouTube, Instagram, TikTok)
//
// Direct publishing (src/social.js): «Всюди» queues one delivery per connected
// network; the five-minute cron (promoPublish) uploads, polls and reports back
// to the approval message. Networks without a connection go through Metricool
// when it is configured, else they are skipped.
//
// Nothing is published without the developer: a package is 'pending' until a
// button press in TELEGRAM_CHAT_ID moves it, once (a conditional UPDATE), to
// 'publishing'. «Всюди» schedules it in Metricool (as a draft while
// PROMO_METRICOOL_MODE is not "publish") and posts it to the Telegram channel;
// «Лише Telegram» only the channel; «Лише YouTube» only YouTube (direct, else
// Metricool), not the channel; «Відхилити» deletes the media.

import {
  NETWORK_CLIENTS,
  NETWORK_NAMES,
  NETWORK_SECRETS,
  SOCIAL_NETWORKS,
  connectedNetworks,
  loadAccount,
  saveAccount,
  socialConfigured
} from "./social.js";

export const PROMO_FORMATS = ["draft", "coach", "meta", "hero", "fact", "release"];
export const PROMO_FILES = { "video.mp4": "video/mp4", "cover.jpg": "image/jpeg" };
export const PROMO_MAX_VIDEO = 95 * 1024 * 1024; // under the Workers request limit
export const PROMO_MAX_COVER = 2 * 1024 * 1024;
export const PROMO_PENDING_DAYS = 7;
export const PROMO_MEDIA_DAYS = 30;
export const PROMO_STATS_DAYS = 30;
const CAPTION_MAX = 2200;
const TITLE_MAX = 100;
const NETWORKS = ["instagram", "tiktok", "youtube"];
const METRICOOL = "https://app.metricool.com/api";
const DAY = 86_400_000;
export const PROMO_CRON = "*/5 * * * *"; // wrangler.toml [triggers]
const OAUTH_MINUTES = 15;
const DELIVERY_TRIES = 6;
const DELIVERY_LEASE = 10 * 60_000;
const DELIVERY_DEADLINE = 6 * 3_600_000; // a network still processing after this is given up
const BACKOFF = [2, 5, 15, 30, 60].map((m) => m * 60_000);

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function webhookSecret(botToken) {
  // Derived from the bot token: whoever can set the webhook knows it, nobody else.
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`wardly-promo-webhook:${botToken}`));
  return hex(digest).slice(0, 48);
}

function randomKey() {
  return hex(crypto.getRandomValues(new Uint8Array(16)));
}

function text(value, max) {
  return typeof value === "string" && value.trim() && value.length <= max ? value : null;
}

export function validatePromo(data) {
  if (!data || typeof data !== "object") return null;
  const id = String(data.id || "");
  if (!/^[a-f0-9]{16}$/.test(id)) return null;
  if (!PROMO_FORMATS.includes(data.format)) return null;
  const caption = text(data.caption, CAPTION_MAX);
  const title = text(data.youtube_title, TITLE_MAX);
  const telegram = text(data.telegram_caption, 1024);
  const topic = text(String(data.topic ?? ""), 80);
  if (!caption || !title || !telegram || !topic) return null;
  const youtube = {};
  if (data.youtube_tags !== undefined) {
    if (!Array.isArray(data.youtube_tags) || !data.youtube_tags.length || data.youtube_tags.length > 30) return null;
    if (data.youtube_tags.some((tag) => !text(tag, 100) || /[<>\r\n]/.test(tag))) return null;
    // YouTube counts commas and quotes around multiword tags toward 500 chars.
    const length = data.youtube_tags.reduce((n, tag) => n + tag.length + (tag.includes(" ") ? 2 : 0), 0) + data.youtube_tags.length - 1;
    if (length > 450) return null;
    youtube.youtube_tags = [...new Set(data.youtube_tags.map((tag) => tag.trim()))];
  }
  if (data.youtube_language !== undefined) {
    if (!["uk", "en"].includes(data.youtube_language)) return null;
    youtube.youtube_language = data.youtube_language;
  }
  if (data.youtube_publish_at !== undefined) {
    // A UTC minute: YouTube opens the video itself then (social.js, private until).
    const at = data.youtube_publish_at;
    if (typeof at !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$/.test(at) || !Number.isFinite(Date.parse(at))) return null;
    youtube.youtube_publish_at = at;
  }
  return {
    id,
    format: data.format,
    topic,
    hook: Number.isInteger(data.hook) ? data.hook : 0,
    body: { caption, youtube_title: title, telegram_caption: telegram, title: text(data.title, 200) || title, ...youtube }
  };
}

export async function registerPromo(request, env, now = Date.now()) {
  if (!env.REPORTS) return json({ ok: false, code: "no_storage" }, 503);
  let data;
  try {
    data = await request.json();
  } catch {
    return json({ ok: false, code: "bad_json" }, 400);
  }
  const post = validatePromo(data);
  if (!post) return json({ ok: false, code: "bad_package" }, 400);
  const existing = await env.DB.prepare("SELECT media_key, status, body FROM promo_posts WHERE id = ?1").bind(post.id).first();
  // Echo persisted metadata so a new publisher cannot silently use an older
  // deployment that discards per-video tags/language. Never return OAuth tokens.
  const youtube = (body) => ({ youtube_tags: body.youtube_tags, youtube_language: body.youtube_language, youtube_publish_at: body.youtube_publish_at });
  const ready = Boolean((await connectedNetworks(env)).youtube && socialConfigured(env, "youtube"));
  if (existing) {
    return json({ ok: true, id: post.id, media_key: existing.media_key, status: existing.status, youtube_ready: ready, ...youtube(JSON.parse(existing.body)) });
  }
  const key = randomKey();
  await env.DB.prepare(
    "INSERT INTO promo_posts (id, media_key, created_at, format, topic, hook, body, status) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'pending')"
  )
    .bind(post.id, key, now, post.format, post.topic, post.hook, JSON.stringify(post.body))
    .run();
  return json({ ok: true, id: post.id, media_key: key, status: "pending", youtube_ready: ready, ...youtube(post.body) }, 201);
}

export async function putPromoFile(request, id, file, env) {
  if (!env.REPORTS) return json({ ok: false, code: "no_storage" }, 503);
  if (!PROMO_FILES[file] || !/^[a-f0-9]{16}$/.test(id)) return json({ ok: false, code: "not_found" }, 404);
  const row = await env.DB.prepare("SELECT media_key, status FROM promo_posts WHERE id = ?1").bind(id).first();
  if (!row || row.status !== "pending") return json({ ok: false, code: "not_pending" }, 409);
  const bytes = await request.arrayBuffer();
  const limit = file === "video.mp4" ? PROMO_MAX_VIDEO : PROMO_MAX_COVER;
  if (!bytes.byteLength || bytes.byteLength > limit) return json({ ok: false, code: "bad_size" }, 413);
  await env.REPORTS.put(`promo/${row.media_key}/${file}`, bytes, { httpMetadata: { contentType: PROMO_FILES[file] } });
  return json({ ok: true, bytes: bytes.byteLength });
}

export async function promoMedia(request, key, file, env) {
  if (!env.REPORTS || !PROMO_FILES[file] || !/^[a-f0-9]{32}$/.test(key)) return json({ ok: false, code: "not_found" }, 404);
  const row = await env.DB.prepare("SELECT status FROM promo_posts WHERE media_key = ?1").bind(key).first();
  if (!row || ["rejected", "expired"].includes(row.status)) return json({ ok: false, code: "not_found" }, 404);
  const range = request.headers.get("range");
  const match = range && range.match(/^bytes=(\d+)-(\d*)$/);
  const options = match
    ? { range: match[2] ? { offset: +match[1], length: +match[2] - +match[1] + 1 } : { offset: +match[1] } }
    : undefined;
  const object = await env.REPORTS.get(`promo/${key}/${file}`, options);
  if (!object) return json({ ok: false, code: "not_found" }, 404);
  const headers = {
    "content-type": PROMO_FILES[file],
    "cache-control": "public, max-age=86400",
    "accept-ranges": "bytes",
    "x-content-type-options": "nosniff"
  };
  if (match && object.range) {
    const start = object.range.offset ?? +match[1];
    const length = object.range.length ?? object.size - start;
    headers["content-range"] = `bytes ${start}-${start + length - 1}/${object.size}`;
    headers["content-length"] = String(length);
    return new Response(request.method === "HEAD" ? null : object.body, { status: 206, headers });
  }
  headers["content-length"] = String(object.size);
  return new Response(request.method === "HEAD" ? null : object.body, { headers });
}

// --- Telegram ---------------------------------------------------------------------------

async function telegram(env, method, body) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  return { ok: response.ok && data?.ok !== false, data };
}

export async function telegramWebhook(request, env, now = Date.now()) {
  if (!env.TELEGRAM_BOT_TOKEN) return json({ ok: false, code: "not_found" }, 404);
  const secret = request.headers.get("x-telegram-bot-api-secret-token") || "";
  if (secret !== (await webhookSecret(env.TELEGRAM_BOT_TOKEN))) return json({ ok: false, code: "not_found" }, 404);
  let update;
  try {
    update = await request.json();
  } catch {
    return json({ ok: true });
  }
  const admin = String(env.TELEGRAM_CHAT_ID || "");
  const origin = publicOrigin(env, request);
  const message = update.message;
  const command = String(message?.text || "").trim();
  if (message?.chat?.type === "private" && admin && String(message.chat.id) === admin && String(message.from?.id) === admin) {
    const handled = await adminCommand(env, command, message.chat.id, origin, now);
    if (handled) return json({ ok: true });
  }
  if (message?.chat?.type === "private" && /^\/(start|id)\b/.test(command)) {
    // The chat id to put in TELEGRAM_CHAT_ID; harmless to anyone: it is their own.
    await telegram(env, "sendMessage", {
      chat_id: message.chat.id,
      text: `Ваш chat id: ${message.chat.id}${String(message.chat.id) === admin ? " (це розробник Wardly)" : ""}`
    });
    return json({ ok: true });
  }
  const callback = update.callback_query;
  if (!callback) return json({ ok: true });
  const match = String(callback.data || "").match(/^promo:(all|tg|yt|no):([a-f0-9]{16})$/);
  const fromAdmin = admin && String(callback.from?.id) === admin && String(callback.message?.chat?.id) === admin;
  if (!match || !fromAdmin) {
    await telegram(env, "answerCallbackQuery", { callback_query_id: callback.id, text: "Недоступно" });
    return json({ ok: true });
  }
  // Answered after the work (Telegram waits; a redelivery finds the post decided).
  await decide(env, match[2], match[1], callback, now, origin);
  return json({ ok: true });
}

const ANSWERS = {
  all: "Публікую всюди…",
  tg: "Публікую в Telegram-каналі…",
  yt: "Публікую лише на YouTube…",
  no: "Відхилено"
};

export async function decide(env, id, action, callback, now = Date.now(), origin = "") {
  const next = action === "no" ? "rejected" : "publishing";
  const moved = await env.DB.prepare(
    "UPDATE promo_posts SET status = ?2, decided_at = ?3 WHERE id = ?1 AND status = 'pending'"
  )
    .bind(id, next, now)
    .run();
  if (!moved.meta?.changes) {
    await telegram(env, "answerCallbackQuery", { callback_query_id: callback.id, text: "Вже вирішено раніше" });
    return { ok: false, code: "already_decided" };
  }
  await telegram(env, "answerCallbackQuery", { callback_query_id: callback.id, text: ANSWERS[action] });
  const row = await env.DB.prepare("SELECT media_key, body FROM promo_posts WHERE id = ?1").bind(id).first();
  const body = JSON.parse(row.body);
  if (action === "no") {
    await deleteMedia(env, row.media_key);
    await report(env, callback, "❌ Відхилено. Медіа видалено.");
    return { ok: true, status: "rejected" };
  }
  const result = {};
  const channel = String(env.TELEGRAM_CHANNEL || "").trim();
  const fileId = callback.message?.video?.file_id;
  if (action === "yt") {
    // YouTube only: the channel stays as it is
  } else if (channel && fileId) {
    const sent = await telegram(env, "sendVideo", {
      chat_id: channel,
      video: fileId,
      caption: body.telegram_caption,
      supports_streaming: true
    });
    result.telegram = sent.ok ? { status: "PUBLISHED", id: sent.data?.result?.message_id } : { status: "ERROR", error: sent.data?.description || "telegram" };
  } else {
    result.telegram = { status: "SKIPPED", error: channel ? "no video in the approval message" : "TELEGRAM_CHANNEL is not set" };
  }
  let metricoolId = null;
  let publishAt = null;
  const queued = [];
  if (action === "all" || action === "yt") {
    const connected = await connectedNetworks(env);
    const wanted = action === "yt" ? ["youtube"] : promoNetworks(env);
    const direct = wanted.filter((n) => connected[n] && socialConfigured(env, n));
    const rest = wanted.filter((n) => !direct.includes(n));
    for (const network of direct) {
      await env.DB.prepare(
        "INSERT OR IGNORE INTO promo_deliveries (post_id, network, status, attempts, next_at, updated_at) VALUES (?1, ?2, 'queued', 0, ?3, ?3)"
      )
        .bind(id, network, now)
        .run();
      queued.push(network);
    }
    if (rest.length && metricoolReady(env)) {
      const scheduled = await scheduleMetricool({ ...env, PROMO_NETWORKS: rest.join(",") }, body, `${origin}/m/${row.media_key}/video.mp4`, now);
      result.metricool = scheduled;
      metricoolId = scheduled.id || null;
      publishAt = scheduled.publish_at || null;
    } else if (rest.length) {
      result.skipped = rest;
    }
  }
  // «Лише YouTube» with YouTube neither connected nor in Metricool published nothing.
  const failed =
    Object.values(result).some((r) => r?.status === "ERROR") || (action === "yt" && !queued.length && !metricoolId);
  // Queued deliveries decide the end (finishPost); a channel or Metricool error
  // stays in `result` and in the report.
  const status = queued.length ? "publishing" : failed ? "failed" : metricoolId ? "scheduled" : "published";
  await env.DB.prepare(
    "UPDATE promo_posts SET status = ?2, publish_at = ?3, metricool_id = ?4, result = ?5, approval_chat = ?6, approval_message = ?7 WHERE id = ?1"
  )
    .bind(id, status, publishAt, metricoolId, JSON.stringify(result), String(callback.message?.chat?.id ?? ""), callback.message?.message_id ?? null)
    .run();
  if (queued.length) result.queued = queued;
  await report(env, callback, statusText(result, env));
  return { ok: !failed, status, result };
}

function statusText(result, env) {
  const lines = [];
  const t = result.telegram;
  if (t) lines.push(t.status === "PUBLISHED" ? "✅ Telegram-канал: опубліковано" : `⚠️ Telegram-канал: ${t.error || t.status}`);
  const m = result.metricool;
  if (m) {
    if (m.status === "SCHEDULED" || m.status === "DRAFT") {
      const draft = m.status === "DRAFT";
      lines.push(
        `${draft ? "📝" : "✅"} Metricool: ${draft ? "чернетка" : "заплановано"} на ${m.publish_at} (${(m.networks || []).join(", ")})`
      );
      if (draft) lines.push("Чернетки публікуються з Metricool; автопублікація — змінна PROMO_METRICOOL_MODE=publish.");
    } else {
      lines.push(`⚠️ Metricool: ${m.error || m.status}`);
    }
  }
  if (result.queued?.length) {
    lines.push(`⏳ ${result.queued.map((n) => NETWORK_NAMES[n]).join(", ")}: у черзі, звіт — за кілька хвилин`);
  }
  if (result.skipped?.length) {
    lines.push(
      `➖ ${result.skipped.map((n) => NETWORK_NAMES[n]).join(", ")}: не підключено (${result.skipped.map((n) => `/connect ${n}`).join(", ")})`
    );
  }
  return lines.join("\n") || "Готово";
}

async function report(env, callback, line) {
  const chat = callback.message?.chat?.id;
  const messageId = callback.message?.message_id;
  if (!chat || !messageId) return;
  await telegram(env, "editMessageReplyMarkup", { chat_id: chat, message_id: messageId, reply_markup: { inline_keyboard: [] } });
  await telegram(env, "sendMessage", { chat_id: chat, text: line, reply_to_message_id: messageId });
}

async function deleteMedia(env, key) {
  if (!env.REPORTS || !key) return;
  await env.REPORTS.delete(Object.keys(PROMO_FILES).map((file) => `promo/${key}/${file}`));
}

// --- Metricool --------------------------------------------------------------------------

export function metricoolReady(env) {
  return Boolean(env.METRICOOL_TOKEN && env.METRICOOL_USER_ID && env.METRICOOL_BLOG_ID);
}

function metricoolUrl(env, path, params = {}) {
  const url = new URL(`${METRICOOL}${path}`);
  url.searchParams.set("userId", String(env.METRICOOL_USER_ID).trim());
  url.searchParams.set("blogId", String(env.METRICOOL_BLOG_ID).trim());
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
  return url.toString();
}

async function metricool(env, method, path, { params, body } = {}) {
  const response = await fetch(metricoolUrl(env, path, params), {
    method,
    headers: { "X-Mc-Auth": String(env.METRICOOL_TOKEN).trim(), ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined
  });
  const raw = await response.text();
  let data = raw;
  try {
    data = JSON.parse(raw);
  } catch {
    // a plain string (the normalize call answers the URL as text)
  }
  return { ok: response.ok, status: response.status, data };
}

// The local wall time in a time zone, as Metricool wants it ("YYYY-MM-DDTHH:mm:ss").
export function localDateTime(ms, timeZone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    })
      .formatToParts(new Date(ms))
      .map((p) => [p.type, p.value])
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

export function promoNetworks(env) {
  const wanted = String(env.PROMO_NETWORKS || NETWORKS.join(","))
    .split(",")
    .map((n) => n.trim().toLowerCase())
    .filter((n) => NETWORKS.includes(n));
  return wanted.length ? wanted : NETWORKS;
}

export function metricoolPost(env, body, media, now) {
  const timeZone = String(env.PROMO_TIMEZONE || "Europe/Kyiv");
  const delay = Math.max(5, Number(env.PROMO_DELAY_MINUTES) || 15);
  const publish = String(env.PROMO_METRICOOL_MODE || "draft").toLowerCase() === "publish";
  const networks = promoNetworks(env);
  const post = {
    publicationDate: { dateTime: localDateTime(now + delay * 60_000, timeZone), timezone: timeZone },
    text: body.caption,
    providers: networks.map((network) => ({ network })),
    media: [media],
    autoPublish: publish,
    draft: !publish,
    shortener: false
  };
  if (networks.includes("instagram")) post.instagramData = { type: "REEL", showReelOnFeed: true, autoPublish: publish };
  if (networks.includes("tiktok")) {
    post.tiktokData = {
      privacyOption: "PUBLIC_TO_EVERYONE",
      disableComment: false,
      disableDuet: false,
      disableStitch: false,
      autoAddMusic: false,
      commercialContentOwnBrand: true,
      commercialContentThirdParty: false,
      title: body.title.slice(0, 90)
    };
  }
  if (networks.includes("youtube")) {
    post.youtubeData = { title: body.youtube_title, type: "SHORT", privacy: "PUBLIC", madeForKids: false, category: "20" };
  }
  return { post, networks, publish };
}

export async function scheduleMetricool(env, body, mediaUrl, now = Date.now()) {
  const normalized = await metricool(env, "GET", "/actions/normalize/image/url", { params: { url: mediaUrl } });
  if (!normalized.ok) return { status: "ERROR", error: `normalize ${normalized.status}` };
  const media =
    typeof normalized.data === "string"
      ? normalized.data.replace(/^"|"$/g, "")
      : normalized.data?.url || normalized.data?.mediaUrl || normalized.data?.data || mediaUrl;
  const { post, networks, publish } = metricoolPost(env, body, media, now);
  const created = await metricool(env, "POST", "/v2/scheduler/posts", { body: post });
  if (!created.ok) {
    const detail = typeof created.data === "string" ? created.data : JSON.stringify(created.data);
    return { status: "ERROR", error: `scheduler ${created.status}: ${String(detail).slice(0, 300)}` };
  }
  const data = created.data?.data || created.data || {};
  return {
    status: publish ? "SCHEDULED" : "DRAFT",
    id: data.id != null ? String(data.id) : null,
    uuid: data.uuid || null,
    publish_at: post.publicationDate.dateTime.replace("T", " ").slice(0, 16),
    networks
  };
}

// --- statistics -------------------------------------------------------------------------

const METRIC_KEYS = {
  views: ["views", "viewCount", "videoViews", "plays"],
  likes: ["likes", "likeCount"],
  comments: ["comments", "commentCount"],
  shares: ["shares", "shareCount"]
};

export function numbers(item) {
  const out = {};
  for (const [name, keys] of Object.entries(METRIC_KEYS)) {
    const key = keys.find((k) => Number.isFinite(Number(item?.[k])));
    out[name] = key ? Math.round(Number(item[key])) : 0;
  }
  return out;
}

const SOURCES = {
  instagram: { path: "/v2/analytics/reels/instagram", text: ["content"], url: ["url"] },
  tiktok: { path: "/v2/analytics/posts/tiktok", text: ["videoDescription", "title"], url: ["shareUrl", "embedLink"] },
  youtube: { path: "/v2/analytics/posts/youtube", text: ["title", "description"], url: ["watchUrl"] }
};

// A published item belongs to a post when its text starts like the post's
// caption (the first line is unique: hero, week or version) or it has the URL
// Metricool reported for the post.
export function matchItem(items, post, network, url) {
  const first = String(post.body.caption || "").split("\n")[0].trim().slice(0, 40).toLowerCase();
  const title = String(post.body.youtube_title || "").toLowerCase();
  const source = SOURCES[network];
  return (
    items.find((item) => url && source.url.some((key) => item?.[key] && String(item[key]) === url)) ||
    items.find((item) =>
      source.text.some((key) => {
        const value = String(item?.[key] || "").toLowerCase();
        if (!value) return false;
        // Networks may cut a description: the shorter of the two starts the other.
        const prefix = first && (value.startsWith(first) || (value.length >= 20 && first.startsWith(value)));
        return prefix || (network === "youtube" && title && value === title);
      })
    ) ||
    null
  );
}

export async function refreshStats(env, now = Date.now()) {
  if (!metricoolReady(env)) return 0;
  const { results } = await env.DB.prepare(
    "SELECT id, body, metricool_id, result FROM promo_posts WHERE status IN ('scheduled', 'published') AND decided_at >= ?1"
  )
    .bind(now - PROMO_STATS_DAYS * DAY)
    .all();
  const posts = (results || []).filter((row) => row.metricool_id).map((row) => ({ ...row, body: JSON.parse(row.body) }));
  if (!posts.length) return 0;
  const timeZone = String(env.PROMO_TIMEZONE || "Europe/Kyiv");
  const range = {
    from: `${localDateTime(now - PROMO_STATS_DAYS * DAY, timeZone).slice(0, 10)}T00:00:00`,
    to: `${localDateTime(now, timeZone).slice(0, 10)}T23:59:59`,
    timezone: timeZone
  };
  const urls = {};
  for (const post of posts) {
    const detail = await metricool(env, "GET", `/v2/scheduler/posts/${encodeURIComponent(post.metricool_id)}`);
    const providers = detail.ok ? detail.data?.data?.providers || detail.data?.providers || [] : [];
    urls[post.id] = Object.fromEntries(providers.map((p) => [String(p.network || "").toLowerCase(), p.publicUrl || null]));
  }
  let stored = 0;
  for (const network of promoNetworks(env)) {
    const answer = await metricool(env, "GET", SOURCES[network].path, { params: range });
    if (!answer.ok) continue;
    const items = Array.isArray(answer.data) ? answer.data : answer.data?.data || [];
    for (const post of posts) {
      const url = urls[post.id]?.[network] || null;
      const item = matchItem(items, post, network, url);
      if (!item) continue;
      const n = numbers(item);
      await env.DB.prepare(
        "INSERT INTO promo_stats (post_id, network, updated_at, url, views, likes, comments, shares) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8) " +
          "ON CONFLICT (post_id, network) DO UPDATE SET updated_at = ?3, url = ?4, views = ?5, likes = ?6, comments = ?7, shares = ?8"
      )
        .bind(post.id, network, now, url, n.views, n.likes, n.comments, n.shares)
        .run();
      stored += 1;
    }
  }
  return stored;
}

export async function promoList(env, now = Date.now()) {
  const { results } = await env.DB.prepare(
    "SELECT p.id, p.created_at, p.format, p.topic, p.hook, p.status, p.publish_at, " +
      "COALESCE(SUM(s.views), 0) AS views, COALESCE(SUM(s.likes), 0) AS likes, " +
      "COALESCE(SUM(s.comments), 0) AS comments, COALESCE(SUM(s.shares), 0) AS shares " +
      "FROM promo_posts p LEFT JOIN promo_stats s ON s.post_id = p.id WHERE p.created_at >= ?1 " +
      "GROUP BY p.id ORDER BY p.created_at DESC LIMIT 200"
  )
    .bind(now - 120 * DAY)
    .all();
  return json({ ok: true, posts: results || [] });
}

export function weeklyPromoText(posts) {
  const published = posts.filter((p) => ["scheduled", "published", "publishing"].includes(p.status));
  if (!published.length) return null;
  const byFormat = {};
  for (const post of published) {
    const entry = (byFormat[post.format] ||= { count: 0, views: 0, likes: 0 });
    entry.count += 1;
    entry.views += post.views;
    entry.likes += post.likes;
  }
  const best = [...published].sort((a, b) => b.views - a.views)[0];
  const lines = [
    "📈 Промо за 30 днів",
    ...Object.entries(byFormat)
      .sort((a, b) => b[1].views / b[1].count - a[1].views / a[1].count)
      .map(([format, e]) => `• ${format}: ${e.count} відео, у середньому ${Math.round(e.views / e.count)} переглядів, ${Math.round(e.likes / e.count)} лайків`),
    `Найкраще: ${best.format} · ${best.topic} — ${best.views} переглядів`
  ];
  return lines.join("\n");
}

export async function promoMaintenance(env, now = Date.now()) {
  // Undecided packages expire; published media go after PROMO_MEDIA_DAYS
  // (Metricool keeps its own copy from the normalize call).
  const { results } = await env.DB.prepare(
    "SELECT id, media_key, status FROM promo_posts WHERE (status = 'pending' AND created_at < ?1) OR " +
      "(status IN ('scheduled', 'published', 'failed') AND decided_at < ?2 AND result NOT LIKE '%\"media_deleted\"%')"
  )
    .bind(now - PROMO_PENDING_DAYS * DAY, now - PROMO_MEDIA_DAYS * DAY)
    .all();
  for (const row of results || []) {
    await deleteMedia(env, row.media_key);
    if (row.status === "pending") {
      await env.DB.prepare("UPDATE promo_posts SET status = 'expired' WHERE id = ?1 AND status = 'pending'").bind(row.id).run();
    } else {
      await env.DB.prepare(
        "UPDATE promo_posts SET result = json_set(COALESCE(result, '{}'), '$.media_deleted', 1) WHERE id = ?1"
      )
        .bind(row.id)
        .run();
    }
  }
  const stored =
    (await refreshStats(env, now).catch((error) => {
      console.log(`promo stats: ${error.message}`);
      return 0;
    })) +
    (await refreshDirectStats(env, now).catch((error) => {
      console.log(`promo direct stats: ${error.message}`);
      return 0;
    }));
  if (new Date(now).getUTCDay() === 1 && env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    const list = await (await promoList(env, now)).json();
    const recent = list.posts.filter((p) => p.created_at >= now - PROMO_STATS_DAYS * DAY);
    const message = weeklyPromoText(recent);
    if (message) await telegram(env, "sendMessage", { chat_id: String(env.TELEGRAM_CHAT_ID), text: message });
  }
  return { cleaned: (results || []).length, stored };
}

// --- connecting accounts (the bot's /connect) -------------------------------------------

export function publicOrigin(env, request) {
  const set = String(env.PROMO_PUBLIC_ORIGIN || env.PROMO_MEDIA_ORIGIN || "").trim();
  return (set || (request ? new URL(request.url).origin : "")).replace(/\/+$/, "");
}

function redirectFor(origin, network) {
  return `${origin}/oauth/${network}/callback`;
}

const COMMAND = /^\/(connect|disconnect|accounts)(?:@\w+)?(?:\s+(\w+))?\s*$/i;

async function adminCommand(env, text, chat, origin, now) {
  const match = text.match(COMMAND);
  if (!match) return false;
  const verb = match[1].toLowerCase();
  const network = String(match[2] || "").toLowerCase();
  const say = (message, extra = {}) => telegram(env, "sendMessage", { chat_id: chat, text: message, ...extra });
  if (verb === "accounts") {
    const connected = await connectedNetworks(env);
    const lines = SOCIAL_NETWORKS.map((n) => {
      if (connected[n]) return `✅ ${NETWORK_NAMES[n]}: ${connected[n].name || "підключено"}`;
      if (socialConfigured(env, n)) return `➖ ${NETWORK_NAMES[n]}: не підключено — /connect ${n}`;
      return `⚙️ ${NETWORK_NAMES[n]}: додайте секрети ${NETWORK_SECRETS[n].join(", ")}`;
    });
    await say(`Акаунти для промо:\n${lines.join("\n")}`);
    return true;
  }
  if (!SOCIAL_NETWORKS.includes(network)) {
    await say(`Вкажіть мережу: /${verb} youtube | instagram | tiktok`);
    return true;
  }
  if (verb === "disconnect") {
    await env.DB.prepare("DELETE FROM promo_accounts WHERE network = ?1").bind(network).run();
    await say(`${NETWORK_NAMES[network]} відключено. Нові відео туди не підуть.`);
    return true;
  }
  if (!socialConfigured(env, network)) {
    await say(
      `Спершу додайте в секрети репозиторію ${NETWORK_SECRETS[network].join(" і ")} і запустіть workflow «API». ` +
        `Адреса повернення для застосунку: ${redirectFor(origin, network)}`
    );
    return true;
  }
  const state = crypto.getRandomValues(new Uint8Array(16)).reduce((s, b) => s + b.toString(16).padStart(2, "0"), "");
  await env.DB.prepare("DELETE FROM promo_oauth WHERE created_at < ?1").bind(now - OAUTH_MINUTES * 60_000).run();
  await env.DB.prepare("INSERT INTO promo_oauth (state, network, created_at) VALUES (?1, ?2, ?3)").bind(state, network, now).run();
  const url = NETWORK_CLIENTS[network].authUrl(env, redirectFor(origin, network), state);
  await say(`Підключення ${NETWORK_NAMES[network]}: відкрийте посилання й дозвольте доступ (діє ${OAUTH_MINUTES} хв).`, {
    reply_markup: { inline_keyboard: [[{ text: `Увійти в ${NETWORK_NAMES[network]}`, url }]] }
  });
  return true;
}

const PAGE_HEADERS = {
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
};

function page(title, text, status = 200) {
  const e = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return new Response(
    `<!doctype html><html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
      `<title>${e(title)}</title><body style="font:18px/1.5 system-ui,sans-serif;background:#0c0d0f;color:#f3f3f4;padding:40px 24px;max-width:560px;margin:auto">` +
      `<h1 style="font-size:26px">${e(title)}</h1><p>${e(text)}</p></body></html>`,
    { status, headers: PAGE_HEADERS }
  );
}

export async function oauthCallback(request, network, env, now = Date.now()) {
  if (!SOCIAL_NETWORKS.includes(network) || !socialConfigured(env, network)) return page("Не знайдено", "Немає такої мережі.", 404);
  const url = new URL(request.url);
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code") || url.searchParams.get("auth_code") || "";
  if (!/^[a-f0-9]{32}$/.test(state)) return page("Посилання недійсне", "Почніть знову: /connect у боті.", 400);
  // One use: the row goes before the exchange, so a replayed link does nothing.
  const row = await env.DB.prepare("DELETE FROM promo_oauth WHERE state = ?1 AND network = ?2 AND created_at >= ?3 RETURNING network")
    .bind(state, network, now - OAUTH_MINUTES * 60_000)
    .first();
  if (!row) return page("Посилання застаріло", "Почніть знову: /connect у боті.", 400);
  if (!code) return page("Доступ не надано", url.searchParams.get("error_description") || url.searchParams.get("error") || "Спробуйте ще раз.", 400);
  let account;
  try {
    account = await NETWORK_CLIENTS[network].exchange(env, code, redirectFor(publicOrigin(env, request), network), now);
    await saveAccount(env, network, account, now);
  } catch (error) {
    console.log(`oauth ${network}: ${error.message}`);
    if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
      await telegram(env, "sendMessage", { chat_id: String(env.TELEGRAM_CHAT_ID), text: `⚠️ ${NETWORK_NAMES[network]}: не вдалося підключити — ${error.message}` });
    }
    return page("Не вдалося підключити", error.message, 502);
  }
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID) {
    await telegram(env, "sendMessage", {
      chat_id: String(env.TELEGRAM_CHAT_ID),
      text: `✅ ${NETWORK_NAMES[network]} підключено: ${account.name}. Наступні схвалені відео підуть і туди.`
    });
  }
  return page(`${NETWORK_NAMES[network]} підключено`, `${account.name}. Це вікно можна закрити.`);
}

// --- the delivery queue (cron every five minutes) ----------------------------------------

function media(env, row, origin) {
  return {
    url: `${origin}/m/${row.media_key}/video.mp4`,
    cover_url: null,
    size: 0,
    async open(offset = 0) {
      const object = await env.REPORTS.get(`promo/${row.media_key}/video.mp4`, offset ? { range: { offset } } : undefined);
      if (!object) throw new Error("the video is gone from storage");
      return object.body;
    }
  };
}

const DELIVERY_WORDS = {
  published: "опубліковано",
  draft: "чернетка",
  error: "помилка"
};

// A package's YouTube time is kept only when the button was pressed well before
// it (the upload starts within a few cron runs); pressed later, the video goes
// out at once. The decision time is fixed, so every step of one upload agrees.
export const SCHEDULE_MARGIN = 15 * 60 * 1000;

export function youtubeSchedule(body, decidedAt) {
  if (!body?.youtube_publish_at) return null;
  return Date.parse(body.youtube_publish_at) > decidedAt + SCHEDULE_MARGIN ? "scheduled" : "late";
}

export function kyivTime(at) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Kyiv", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(at))
      .map((p) => [p.type, p.value])
  );
  return `${parts.day}.${parts.month} ${parts.hour}:${parts.minute}`;
}

export async function promoPublish(env, now = Date.now()) {
  if (!env.REPORTS) return { worked: 0 };
  const origin = publicOrigin(env, null);
  const { results } = await env.DB.prepare(
    "SELECT d.post_id, d.network, d.status, d.attempts, d.external_id, p.media_key, p.body, p.decided_at " +
      "FROM promo_deliveries d JOIN promo_posts p ON p.id = d.post_id " +
      "WHERE d.status IN ('queued', 'processing') AND d.next_at <= ?1 ORDER BY d.next_at LIMIT 6"
  )
    .bind(now)
    .all();
  let worked = 0;
  const touched = new Set();
  for (const row of results || []) {
    // A lease: two overlapping runs never work the same delivery.
    const claimed = await env.DB.prepare(
      "UPDATE promo_deliveries SET next_at = ?4 WHERE post_id = ?1 AND network = ?2 AND next_at <= ?3 AND status IN ('queued', 'processing')"
    )
      .bind(row.post_id, row.network, now, now + DELIVERY_LEASE)
      .run();
    if (!claimed.meta?.changes) continue;
    worked += 1;
    touched.add(row.post_id);
    let outcome;
    try {
      let account = await loadAccount(env, row.network);
      if (!account) throw new Error(`${NETWORK_NAMES[row.network]} не підключено`);
      const client = NETWORK_CLIENTS[row.network];
      const refreshed = await client.fresh(env, account, now);
      if (refreshed.changed) await saveAccount(env, row.network, refreshed.account, now);
      account = refreshed.account;
      const head = await env.REPORTS.head(`promo/${row.media_key}/video.mp4`);
      if (!head) throw new Error("the video is gone from storage");
      const job = { body: JSON.parse(row.body), external_id: row.external_id, media: { ...media(env, row, origin), size: head.size } };
      const late = row.network === "youtube" && youtubeSchedule(job.body, row.decided_at ?? now) === "late";
      if (row.network === "youtube" && !late && job.body.youtube_publish_at) job.publish_at = job.body.youtube_publish_at;
      outcome = await client.step(env, account, job, now);
      if (outcome.status === "published" && outcome.scheduled_publish_at) {
        outcome.detail = [outcome.detail, `заплановано на ${kyivTime(outcome.scheduled_publish_at)} (Київ)`].filter(Boolean).join(" · ");
      } else if (outcome.status === "published" && late) {
        outcome.detail = [outcome.detail, "час публікації вже минув — опубліковано одразу"].filter(Boolean).join(" · ");
      }
    } catch (error) {
      outcome = { status: "retry", detail: error.message };
    }
    const attempts = row.attempts + (outcome.status === "retry" ? 1 : 0);
    let status = outcome.status;
    let nextAt = now + (outcome.retry_in || 0);
    if (status === "retry") {
      status = attempts >= DELIVERY_TRIES ? "error" : row.status;
      nextAt = now + BACKOFF[Math.min(attempts - 1, BACKOFF.length - 1)];
    }
    if (status === "processing" && row.decided_at && now - row.decided_at > DELIVERY_DEADLINE) {
      status = "error";
      outcome.detail = `${NETWORK_NAMES[row.network]} не завершив обробку за 6 годин`;
    }
    // A lost upload session starts over: the stored id is cleared.
    const keepId = outcome.restart ? "" : outcome.external_id || null;
    await env.DB.prepare(
      "UPDATE promo_deliveries SET status = ?3, attempts = ?4, next_at = ?5, external_id = CASE WHEN ?6 = '' THEN NULL ELSE COALESCE(?6, external_id) END, " +
        "url = COALESCE(?7, url), detail = ?8, updated_at = ?9 WHERE post_id = ?1 AND network = ?2"
    )
      .bind(row.post_id, row.network, status, attempts, nextAt, keepId, outcome.url || null, outcome.detail || null, now)
      .run();
  }
  for (const postId of touched) await finishPost(env, postId);
  return { worked };
}

async function finishPost(env, postId) {
  const { results } = await env.DB.prepare("SELECT network, status, url, detail FROM promo_deliveries WHERE post_id = ?1").bind(postId).all();
  const rows = results || [];
  if (!rows.length || rows.some((r) => ["queued", "processing"].includes(r.status))) return;
  const failed = rows.every((r) => r.status === "error");
  const moved = await env.DB.prepare("UPDATE promo_posts SET status = ?2 WHERE id = ?1 AND status = 'publishing'")
    .bind(postId, failed ? "failed" : "published")
    .run();
  if (!moved.meta?.changes || !env.TELEGRAM_BOT_TOKEN) return;
  const post = await env.DB.prepare("SELECT approval_chat, approval_message FROM promo_posts WHERE id = ?1").bind(postId).first();
  const chat = post?.approval_chat || String(env.TELEGRAM_CHAT_ID || "");
  if (!chat) return;
  const lines = rows.map((r) => {
    const icon = r.status === "published" ? "✅" : r.status === "draft" ? "📝" : "⚠️";
    const tail = [r.url, r.detail].filter(Boolean).join(" · ");
    return `${icon} ${NETWORK_NAMES[r.network]}: ${DELIVERY_WORDS[r.status] || r.status}${tail ? ` — ${tail}` : ""}`;
  });
  await telegram(env, "sendMessage", {
    chat_id: chat,
    text: lines.join("\n"),
    disable_web_page_preview: true,
    ...(post?.approval_message ? { reply_to_message_id: post.approval_message } : {})
  });
}

// Numbers straight from the networks for the directly published videos.
export async function refreshDirectStats(env, now = Date.now()) {
  const { results } = await env.DB.prepare(
    "SELECT d.post_id, d.network, d.external_id, d.url, p.body FROM promo_deliveries d JOIN promo_posts p ON p.id = d.post_id " +
      "WHERE d.status IN ('published', 'draft') AND d.updated_at >= ?1"
  )
    .bind(now - PROMO_STATS_DAYS * DAY)
    .all();
  let stored = 0;
  for (const network of SOCIAL_NETWORKS) {
    const items = (results || [])
      .filter((r) => r.network === network && r.external_id)
      .map((r) => ({ ...r, caption: JSON.parse(r.body).caption }));
    if (!items.length || !socialConfigured(env, network)) continue;
    let account = await loadAccount(env, network);
    if (!account) continue;
    const refreshed = await NETWORK_CLIENTS[network].fresh(env, account, now);
    if (refreshed.changed) await saveAccount(env, network, refreshed.account, now);
    account = refreshed.account;
    for (const n of await NETWORK_CLIENTS[network].stats(env, account, items)) {
      const item = items.find((i) => i.external_id === n.external_id);
      if (!item) continue;
      await env.DB.prepare(
        "INSERT INTO promo_stats (post_id, network, updated_at, url, views, likes, comments, shares) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8) " +
          "ON CONFLICT (post_id, network) DO UPDATE SET updated_at = ?3, url = ?4, views = ?5, likes = ?6, comments = ?7, shares = ?8"
      )
        .bind(item.post_id, network, now, n.url || item.url || null, n.views, n.likes, n.comments, n.shares)
        .run();
      stored += 1;
    }
  }
  return stored;
}
