// Where players come from: visits to the site and installer downloads per
// source and day (the posts link to luhovyimvp.dev/?ref=<source>; the site's
// download buttons go through GET /d/<source>). Numbers only: no cookies,
// URLs, IP addresses or ids are stored — one row per day and source.

export const CHANNEL_RETENTION_DAYS = 365;
// Per IP and hour: more is still redirected, just not counted.
export const CHANNEL_RATE_PER_HOUR = { visit: 30, download: 10 };
// A day holds at most this many sources; later new ones count as "other".
export const CHANNEL_MAX_SOURCES = 60;

const REPO = "makquella/wardly";
export const RELEASES_PAGE = `https://github.com/${REPO}/releases/latest`;
const SOURCE = /^[a-z0-9][a-z0-9_-]{0,23}$/;

// Crawlers, link previews, monitors and HTTP libraries by what they call
// themselves. A program that hides behind a browser's name passes this one and
// is caught by the navigation headers below (downloads) or not at all (visits).
const AUTOMATED_AGENT =
  /bot\b|crawl|spider|slurp|preview|scan|monitor|uptime|pingdom|headless|lighthouse|pagespeed|phantomjs|puppeteer|playwright|selenium|facebookexternalhit|whatsapp|embedly|vkshare|skypeuri|feedfetcher|mediapartners|google-|googleother|apis-google|ahrefs|semrush|dataforseo|curl|wget|python|httpx|aiohttp|urllib|go-http|okhttp|java\/|libwww|node|undici|axios|postman|insomnia|httpie|ruby|perl|php|scrapy|wardly/i;

/**
 * True for a request no person made: an empty or self-declared automated user
 * agent, a bot Cloudflare verified, or a browser fetching a page ahead of time.
 * Such requests get their answer and are not counted.
 */
export function automated(request) {
  const agent = String(request.headers.get("user-agent") || "").trim();
  if (!agent || AUTOMATED_AGENT.test(agent)) {
    return true;
  }
  if (request.cf?.verifiedBotCategory || request.cf?.botManagement?.verifiedBot) {
    return true;
  }
  const purpose = `${request.headers.get("sec-purpose") || ""} ${request.headers.get("purpose") || ""} ${request.headers.get("x-moz") || ""}`;
  return /prefetch|prerender|preview/i.test(purpose);
}

/**
 * A download a person asked for. Browsers that describe the request
 * (Sec-Fetch-*) must be opening a page, and Chrome, Edge and Firefox mark a
 * click or a typed address with Sec-Fetch-User: a rendering crawler that
 * follows every link has none. Safari and old browsers send less and pass.
 */
export function clickedDownload(request) {
  if (automated(request) || new URL(request.url).searchParams.get("count") === "off") {
    return false;
  }
  const mode = request.headers.get("sec-fetch-mode");
  if (!mode) {
    return true;
  }
  if (mode !== "navigate") {
    return false;
  }
  const agent = request.headers.get("user-agent") || "";
  return !/Chrome\/|Chromium\/|Firefox\//.test(agent) || request.headers.get("sec-fetch-user") === "?1";
}

/** The source name as stored, or null (the caller then counts nothing). */
export function channelSource(value) {
  const src = String(value || "").trim().toLowerCase();
  return SOURCE.test(src) ? src : null;
}

// What /d/<source>?os=<kind> can send: the Windows installer (default) or a Linux package.
export const DOWNLOAD_KINDS = {
  windows: (v) => `Wardly-Setup-${v}.exe`,
  linux: (v) => `Wardly-${v}-x86_64.AppImage`,
  "linux-pacman": (v) => `Wardly-${v}-x86_64.pacman`,
  "linux-deb": (v) => `Wardly_${v}_amd64.deb`
};

/** A known download kind from the `os` query value; the Windows installer otherwise. */
export function downloadKind(value) {
  const kind = String(value || "").trim().toLowerCase();
  return Object.hasOwn(DOWNLOAD_KINDS, kind) ? kind : "windows";
}

/** The asset of the release `releases/latest` redirects to (…/releases/tag/v1.2.3). */
export function installerUrl(location, kind = "windows") {
  const tag = String(location || "").match(/\/releases\/tag\/v(\d{1,3}\.\d{1,3}\.\d{1,3})$/);
  const name = DOWNLOAD_KINDS[downloadKind(kind)];
  return tag ? `https://github.com/${REPO}/releases/download/v${tag[1]}/${name(tag[1])}` : null;
}

const latest = new Map();

/**
 * The latest download's URL per kind, looked up at most every 10 minutes; the
 * releases page when unknown. A Linux package is built after the Windows
 * installer, so its URL is only used once GitHub serves that asset.
 */
export async function latestInstaller(fetchImpl = fetch, now = Date.now(), kind = "windows") {
  kind = downloadKind(kind);
  const cached = latest.get(kind);
  if (cached && now - cached.at < 10 * 60_000) {
    return cached.url;
  }
  try {
    const response = await fetchImpl(RELEASES_PAGE, {
      method: "HEAD",
      redirect: "manual",
      headers: { "user-agent": "wardly-api" }
    });
    const url = installerUrl(response.headers.get("location"), kind);
    if (url && (kind === "windows" || (await assetExists(fetchImpl, url)))) {
      latest.set(kind, { url, at: now });
      return url;
    }
  } catch {
    // GitHub unreachable: the releases page still works.
  }
  return cached?.url || RELEASES_PAGE;
}

async function assetExists(fetchImpl, url) {
  const response = await fetchImpl(url, { method: "HEAD", redirect: "manual", headers: { "user-agent": "wardly-api" } });
  return response.status >= 200 && response.status < 400;
}

export function resetInstallerCache() {
  latest.clear();
}

/** Sums over stored rows ({ day, src, visits, downloads }), most visits first. */
export function aggregateChannels(rows) {
  const bySource = new Map();
  for (const row of rows) {
    const item = bySource.get(row.src) || { src: row.src, visits: 0, downloads: 0 };
    item.visits += Number(row.visits) || 0;
    item.downloads += Number(row.downloads) || 0;
    bySource.set(row.src, item);
  }
  return [...bySource.values()]
    .map((item) => ({ ...item, rate: item.visits ? Math.round((100 * item.downloads) / item.visits) : null }))
    .sort((a, b) => b.visits - a.visits || b.downloads - a.downloads || a.src.localeCompare(b.src));
}
