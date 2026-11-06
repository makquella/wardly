// Match recordings sent by the player's consent (docs/DATA_PLAN.md, stage 5).
// Pure functions, tested with plain `node --test`. The body is the raw gzip
// stream the launcher built (backend/app/match_record_upload.py); the metadata
// travels in headers, so nothing is base64-encoded or parsed as JSON.

export const SESSION_LIMITS = {
  bodyBytes: 20 * 1024 * 1024, // the gzip copy; the launcher refuses larger ones too
  peekCompressed: 8192, // the part of the stream that is decompressed to read the first line
  firstLineChars: 16_384
};
// Recordings per hour from one installation and from one address. Everyone
// together is capped by bytes (sizes stored in D1) to stay inside R2's free
// 10 GB: at most 1.5 GB in the last 24 hours and 8 GB in total, the upload
// being checked included.
export const SESSION_RATE_PER_HOUR = { install: 3, address: 10 };
export const SESSION_DAILY_BYTES = 1.5 * 1024 ** 3;
export const SESSION_TOTAL_BYTES = 8 * 1024 ** 3;
export const SESSION_RETENTION_DAYS = 60;
// About a quarter of the recordings is kept apart to check rules that were
// tuned on the rest (scripts/fetch_recordings.py, docs/LIVE_ADVICE_AUDIT.md).
const HOLDOUT_BELOW = 64; // of 256

const INSTALL_ID = /^[a-z0-9-]{8,64}$/;
const HERO = /^npc_dota_hero_[a-z_]{1,40}$/;
const ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"; // no 0/O, 1/I
// A recording that still carries one of these is a broken or old client's.
const PRIVATE_KEY = /"(?:steamid|accountid|matchid|match_id|auth)"/i;

/** "S-7F3KQ2" from random bytes. */
export function sessionId(bytes) {
  let id = "";
  for (let i = 0; i < 6; i += 1) {
    id += ID_ALPHABET[bytes[i] % ID_ALPHABET.length];
  }
  return `S-${id}`;
}

export function isSessionId(id) {
  return /^S-[2-9A-HJ-NP-Z]{6}$/.test(String(id));
}

export function sessionKey(id, date) {
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `sessions/${date.getUTCFullYear()}/${month}/${id}.jsonl.gz`;
}

/** The same recording is always on the same side: tune or holdout. */
export async function sessionSplit(id) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`dac-split:${id}`));
  return new Uint8Array(digest)[0] < HOLDOUT_BELOW ? "holdout" : "tune";
}

/**
 * Checks the headers of an upload (a `Headers`). Returns { ok: true, meta } or
 * { ok: false, status, code }. Unknown headers are ignored; strings are limited.
 */
export function validateSessionHeaders(headers) {
  const installId = String(headers.get("x-install-id") || "").toLowerCase();
  if (!INSTALL_ID.test(installId)) {
    return { ok: false, status: 400, code: "bad_install_id" };
  }
  const hero = String(headers.get("x-hero") || "").trim();
  if (hero && !HERO.test(hero)) {
    return { ok: false, status: 400, code: "bad_hero" };
  }
  const minutesText = String(headers.get("x-minutes") || "0").trim();
  const minutes = /^\d{1,3}$/.test(minutesText) ? Number(minutesText) : -1;
  if (minutes < 0 || minutes > 240) {
    return { ok: false, status: 400, code: "bad_minutes" };
  }
  const length = Number(headers.get("content-length") || 0);
  if (!Number.isFinite(length) || length <= 0) {
    return { ok: false, status: 411, code: "length_required" };
  }
  if (length > SESSION_LIMITS.bodyBytes) {
    return { ok: false, status: 413, code: "too_large" };
  }
  const version = String(headers.get("x-app-version") || "").trim().slice(0, 32);
  return { ok: true, meta: { installId, hero, minutes, version, length } };
}

export function hasGzipMagic(bytes) {
  return bytes.length > 18 && bytes[0] === 0x1f && bytes[1] === 0x8b;
}

/**
 * Reads the first line of a gzip stream without decompressing the rest: the
 * free tier gives a Worker 10 ms of CPU, far too little for 20 MB. Client-side
 * redaction is the real guarantee; this look catches a broken or old client.
 */
export async function firstLine(bytes) {
  const head = bytes.subarray(0, SESSION_LIMITS.peekCompressed);
  const reader = new Blob([head]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();
  const decoder = new TextDecoder();
  let text = "";
  try {
    while (!text.includes("\n") && text.length < SESSION_LIMITS.firstLineChars) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      text += decoder.decode(value, { stream: true });
    }
  } catch {
    // The slice ends in the middle of the stream: what was read is enough.
  } finally {
    reader.cancel().catch(() => {});
  }
  const end = text.indexOf("\n");
  return end >= 0 ? text.slice(0, end) : text.slice(0, SESSION_LIMITS.firstLineChars);
}

/** Checks the upload's first line. Returns { ok: true } or { ok: false, status, code }. */
export function checkMetaLine(line) {
  let meta;
  try {
    meta = JSON.parse(line);
  } catch {
    return { ok: false, status: 400, code: "bad_recording" };
  }
  if (!meta || meta.k !== "meta" || meta.anonymized !== true) {
    return { ok: false, status: 400, code: "bad_recording" };
  }
  if (PRIVATE_KEY.test(line)) {
    return { ok: false, status: 422, code: "not_anonymized" };
  }
  return { ok: true };
}

/** One message for the developer, without the file. */
export function sessionNote(id, meta, split, size) {
  const mb = (size / 1024 / 1024).toFixed(1);
  return [
    `Запис матчу ${id} (${split})`,
    [meta.hero || "герой невідомий", `${meta.minutes} хв`, meta.version, `${mb} МБ`].filter(Boolean).join(" · ")
  ].join("\n");
}
