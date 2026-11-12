// Shared cache of OpenDota reference data (docs/DATA_PLAN.md, stage 3).
//
// The cron fetches a fixed whitelist of public OpenDota paths into R2 and the
// route GET /v1/opendota/<path> serves them to the launcher, which asks us
// first and OpenDota only when we have nothing fresh (backend/app/opendota.py).
// Bodies are stored exactly as OpenDota sent them: the launcher keeps its own
// shaping code and a Worker has 10 ms of CPU, so only heroStats is parsed (for
// the hero ids). Nothing about a player ever reaches this module.

export const OPENDOTA_ORIGIN = "https://api.opendota.com/api";
export const OPENDOTA_BATCH = 8; // entries per cron run (every 5 minutes)
export const REFRESH_MS = 24 * 3_600_000;
export const BACKOFF_MS = 3_600_000; // after a failure, times the failures in a row (at most BACKOFF_MAX_STEPS)
export const BACKOFF_MAX_STEPS = 6;
export const MAX_BODY_BYTES = 8 * 1024 * 1024;
export const FETCH_TIMEOUT_MS = 60_000;
export const RUN_BUDGET_MS = 4 * 60_000; // no new fetch after this long: the next run starts at 5 minutes
export const HERO_ID_MAX = 300;
export const CACHE_CONTROL = "public, max-age=3600";
const USER_AGENT = "Wardly-OpenDota-Cache/1 (+https://luhovyimvp.dev)";

export const HERO_STATS = "/heroStats";
export const ITEMS = "/constants/items";
const SEEDS = [HERO_STATS, ITEMS];
const HERO_ID = /^[1-9]\d{0,2}$/;

/** "true"/unset = on; "0", "false", "off", "no" = off (like the other kill switches). */
export function cacheEnabled(env) {
  const value = env?.OPENDOTA_CACHE_ENABLED;
  if (value === undefined || value === null || value === "") {
    return true;
  }
  return !["0", "false", "off", "no"].includes(String(value).toLowerCase());
}

function heroId(text) {
  return HERO_ID.test(text) && Number(text) <= HERO_ID_MAX ? text : null;
}

/** R2 key and the kind of JSON expected for an OpenDota path ("/heroes/1/matchups"), or null. */
export function entryFor(path) {
  if (path === HERO_STATS) {
    return { path, key: "opendota/heroStats.json", expect: "array" };
  }
  if (path === ITEMS) {
    return { path, key: "opendota/constants/items.json", expect: "object" };
  }
  const hero = path.match(/^\/heroes\/(\d+)\/(itemPopularity|matchups)$/);
  if (hero && heroId(hero[1])) {
    return { path, key: `opendota/heroes/${hero[1]}/${hero[2]}.json`, expect: hero[2] === "matchups" ? "array" : "object" };
  }
  const timings = path.match(/^\/scenarios\/itemTimings\?hero_id=(\d+)$/);
  if (timings && heroId(timings[1])) {
    return { path, key: `opendota/scenarios/itemTimings/${timings[1]}.json`, expect: "array" };
  }
  return null;
}

/**
 * The entry a request URL asks for: /v1/opendota/heroStats, .../constants/items,
 * .../heroes/<id>/itemPopularity, .../heroes/<id>/matchups,
 * .../scenarios/itemTimings?hero_id=<id>. Anything else (other paths, other or
 * repeated query parameters, ids outside 1..300, leading zeros) is null.
 */
export function entryForRequest(url) {
  const prefix = "/v1/opendota";
  if (!url.pathname.startsWith(`${prefix}/`)) {
    return null;
  }
  const path = url.pathname.slice(prefix.length).replace(/\/+$/, "");
  if (path === "/scenarios/itemTimings") {
    const keys = [...url.searchParams.keys()];
    const ids = url.searchParams.getAll("hero_id");
    return keys.length === 1 && ids.length === 1 ? entryFor(`${path}?hero_id=${ids[0]}`) : null;
  }
  return url.search ? null : entryFor(path);
}

/** The per-hero entries (path and key) a heroStats body implies; ids come from the body, so they are checked. */
export function heroEntries(ids) {
  const seen = new Set();
  const rows = [];
  for (const raw of ids) {
    const id = String(raw);
    if (!heroId(id) || seen.has(id)) {
      continue;
    }
    seen.add(id);
    for (const path of [`/heroes/${id}/itemPopularity`, `/heroes/${id}/matchups`, `/scenarios/itemTimings?hero_id=${id}`]) {
      rows.push(entryFor(path));
    }
  }
  return rows;
}

/** Hero ids listed by a heroStats body (text), [] when it is not the expected list. */
export function heroIds(text) {
  try {
    const data = JSON.parse(text);
    return Array.isArray(data) ? data.map((hero) => hero?.id).filter((id) => Number.isInteger(id)) : [];
  } catch {
    return [];
  }
}

/**
 * Checks an answer without parsing it: HTTP 200, not empty, at most 8 MB, and it
 * starts with `[` or `{` as the path expects. Returns { ok } or { ok: false, reason }.
 */
export function checkBody(status, bytes, expect) {
  if (status !== 200) {
    return { ok: false, reason: `HTTP ${status}` };
  }
  if (!bytes || bytes.byteLength < 2) {
    return { ok: false, reason: "empty" };
  }
  if (bytes.byteLength > MAX_BODY_BYTES) {
    return { ok: false, reason: "too large" };
  }
  const view = new Uint8Array(bytes);
  let at = 0;
  while (at < view.length && (view[at] === 0x20 || view[at] === 0x0a || view[at] === 0x0d || view[at] === 0x09)) {
    at += 1;
  }
  const first = view[at];
  const want = expect === "array" ? 0x5b : 0x7b;
  return first === want ? { ok: true } : { ok: false, reason: "not json" };
}

// Statements. Everything a run needs is read in one batch and written in one
// batch: the free plan allows 50 subrequests per invocation.
const SEED_SQL = "INSERT OR IGNORE INTO opendota_cache (key, path) SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]') FROM json_each(?1)";
const DUE_SQL =
  "SELECT key, path FROM opendota_cache WHERE fetched_at < ?1 " +
  `AND (failed_at IS NULL OR failed_at + ${BACKOFF_MS} * MIN(MAX(fails, 1), ${BACKOFF_MAX_STEPS}) <= ?2) ` +
  "ORDER BY (path IN ('/heroStats', '/constants/items')) DESC, fetched_at ASC, key ASC LIMIT ?3";
const OK_SQL = "UPDATE opendota_cache SET fetched_at = ?2, size = ?3, failed_at = NULL, fails = 0 WHERE key = ?1";
const FAIL_SQL = "UPDATE opendota_cache SET failed_at = ?2, fails = fails + 1 WHERE key = ?1";

function rowsJson(entries) {
  return JSON.stringify(entries.map((entry) => [entry.key, entry.path]));
}

function sourceUrl(path, apiKey) {
  const url = new URL(`${OPENDOTA_ORIGIN}${path}`);
  if (apiKey) {
    url.searchParams.set("api_key", apiKey);
  }
  return url.toString();
}

/**
 * One cron run: at most OPENDOTA_BATCH due entries, one after another (OpenDota
 * allows 60 calls a minute without a key). A 429 ends the run; any other failure
 * marks that entry for backoff and the run goes on. A failed refresh keeps the
 * older object. Returns { fetched, failed, stopped } and never throws for a
 * single entry; storage errors propagate to the caller's catch.
 */
export async function refreshOpenDotaCache(env, now = Date.now(), fetchImpl = fetch, clock = Date.now) {
  const result = { fetched: 0, failed: 0, stopped: false, skipped: null };
  if (!cacheEnabled(env)) {
    return { ...result, skipped: "disabled" };
  }
  if (!env.REPORTS) {
    return { ...result, skipped: "no_storage" };
  }
  const seeds = SEEDS.map(entryFor);
  const [, due] = await env.DB.batch([
    env.DB.prepare(SEED_SQL).bind(rowsJson(seeds)),
    env.DB.prepare(DUE_SQL).bind(now - REFRESH_MS, now, OPENDOTA_BATCH)
  ]);
  const writes = [];
  const started = clock();
  for (const row of due.results || []) {
    const entry = entryFor(row.path);
    if (!entry || entry.key !== row.key) {
      continue; // a row that is not on the whitelist is never fetched
    }
    if (clock() - started > RUN_BUDGET_MS) {
      break;
    }
    let status = 0;
    let bytes = null;
    let reason = "";
    try {
      const response = await fetchImpl(sourceUrl(entry.path, env.OPENDOTA_API_KEY), {
        headers: { "user-agent": USER_AGENT, accept: "application/json" },
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS)
      });
      status = response.status;
      if (status === 429) {
        result.stopped = true;
        console.log("opendota cache: rate limited, run stopped");
        break;
      }
      const length = Number(response.headers.get("content-length") || 0);
      bytes = status === 200 && length <= MAX_BODY_BYTES ? await response.arrayBuffer() : null;
      if (status === 200 && length > MAX_BODY_BYTES) {
        reason = "too large";
      }
    } catch (error) {
      // Only the error's name: a message can carry the address with the key.
      reason = error?.name === "TimeoutError" || error?.name === "AbortError" ? "timeout" : "network";
    }
    const checked = reason ? { ok: false, reason } : checkBody(status, bytes, entry.expect);
    if (checked.ok) {
      try {
        await env.REPORTS.put(entry.key, bytes, {
          httpMetadata: { contentType: "application/json; charset=utf-8" },
          customMetadata: { fetched_at: String(now) }
        });
        writes.push(env.DB.prepare(OK_SQL).bind(entry.key, now, bytes.byteLength));
        result.fetched += 1;
        if (entry.path === HERO_STATS) {
          const heroes = heroEntries(heroIds(new TextDecoder().decode(bytes)));
          if (heroes.length) {
            writes.push(env.DB.prepare(SEED_SQL).bind(rowsJson(heroes)));
          }
        }
        continue;
      } catch {
        checked.reason = "storage";
      }
    }
    console.log(`opendota cache: ${entry.path.split("?")[0]} failed (${checked.reason})`);
    writes.push(env.DB.prepare(FAIL_SQL).bind(entry.key, now));
    result.failed += 1;
  }
  if (writes.length) {
    await env.DB.batch(writes);
  }
  return result;
}

const JSON_ERROR_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function problem(status, code) {
  return new Response(JSON.stringify({ ok: false, code }), { status, headers: JSON_ERROR_HEADERS });
}

/**
 * GET/HEAD /v1/opendota/<whitelisted path>: the stored OpenDota body with
 * x-fetched-at (ms epoch). The Cache API keeps a copy for an hour so repeated
 * reads do not reach R2. Nothing is logged or counted: no addresses, no hero ids.
 */
export async function serveOpenDota(request, env, ctx, { cache } = {}) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return problem(405, "method_not_allowed");
  }
  if (!env.REPORTS) {
    return problem(503, "storage_unavailable");
  }
  if (!cacheEnabled(env)) {
    return problem(503, "disabled");
  }
  const url = new URL(request.url);
  const entry = entryForRequest(url);
  if (!entry) {
    return problem(404, "not_found");
  }
  const store = cache === undefined ? globalThis.caches?.default : cache;
  const cacheKey = new Request(`${url.origin}/v1/opendota${entry.path}`, { method: "GET" });
  try {
    const hit = await store?.match(cacheKey);
    if (hit) {
      return request.method === "HEAD" ? new Response(null, { status: 200, headers: hit.headers }) : hit;
    }
  } catch {
    // The cache is an optimization only.
  }
  const object = await env.REPORTS.get(entry.key);
  if (!object) {
    return problem(404, "not_cached");
  }
  const headers = {
    "content-type": "application/json; charset=utf-8",
    "cache-control": CACHE_CONTROL,
    "x-fetched-at": String(object.customMetadata?.fetched_at || "0"),
    "x-content-type-options": "nosniff"
  };
  const response = new Response(object.body, { status: 200, headers });
  if (store && ctx?.waitUntil) {
    ctx.waitUntil(Promise.resolve(store.put(cacheKey, response.clone())).catch(() => {}));
  }
  return request.method === "HEAD" ? new Response(null, { status: 200, headers }) : response;
}
