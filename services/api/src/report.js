// Problem reports: validation, key removal and ids. Pure functions, so they
// are tested with plain `node --test` (no Workers runtime needed).

// The launcher already removes keys (frontend/launcher/problem-report.js);
// the server does it once more, with the same patterns, before storing.
const SECRET_PATTERNS = [
  /AIza[\w-]{20,}/g, // Google / Gemini
  /AQ\.[\w-]{20,}/g, // Google AI Studio (new format)
  /gsk_[\w-]{16,}/g, // Groq
  /sk-[\w-]{16,}/g, // OpenRouter and other OpenAI-style keys
  /Bearer\s+[\w.-]{12,}/g,
  /(?<=api_key=)[^&\s'"]+/g // OpenDota key in a URL
];
const KEY_FIELD = /("api_?key"\s*:\s*")[^"]*"/gi;

export const LIMITS = {
  textChars: 1_500_000, // the report file (logs, diagnostics)
  noteChars: 2000, // what the player wrote: a problem or an idea
  bodyBytes: 2 * 1024 * 1024,
  rowBytes: 1_900_000 // gzipped report kept in D1 (max 2 MB per value)
};
// Reports per hour from one installation and from one address.
export const RATE_PER_HOUR = { install: 5, address: 20 };
export const RETENTION_DAYS = 180;

const INSTALL_ID = /^[a-z0-9-]{8,64}$/;
const ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"; // no 0/O, 1/I

export function redact(text) {
  let result = String(text ?? "").replace(KEY_FIELD, '$1[redacted]"');
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, "[redacted]");
  }
  return result;
}

function shortText(value, max) {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

/**
 * Checks a report upload. Returns { ok: true, report } or { ok: false, status, code }.
 * Unknown fields are dropped; every kept string is length-limited and redacted.
 */
export function validateReport(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { ok: false, status: 400, code: "bad_json" };
  }
  const installId = String(body.install_id || "").toLowerCase();
  if (!INSTALL_ID.test(installId)) {
    return { ok: false, status: 400, code: "bad_install_id" };
  }
  if (typeof body.text !== "string" || !body.text.trim()) {
    return { ok: false, status: 400, code: "empty_report" };
  }
  if (body.text.length > LIMITS.textChars) {
    return { ok: false, status: 413, code: "too_large" };
  }
  return {
    ok: true,
    report: {
      installId,
      version: shortText(body.version, 32),
      os: shortText(body.os, 64),
      lang: shortText(body.lang, 8),
      note: redact(shortText(body.note, LIMITS.noteChars)),
      text: redact(body.text)
    }
  };
}

/** "R-7F3KQ2" from random bytes (6 symbols, ~1 billion ids). */
export function reportId(bytes) {
  let id = "";
  for (let i = 0; i < 6; i += 1) {
    id += ID_ALPHABET[bytes[i] % ID_ALPHABET.length];
  }
  return `R-${id}`;
}

export function storageKey(id, date) {
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `reports/${date.getUTCFullYear()}/${month}/${id}.txt.gz`;
}

/** One line for the developer: the player's note, else the first error in the report. */
export function summarize(report) {
  if (report.note) {
    return report.note.split("\n")[0].slice(0, 200);
  }
  const line = report.text
    .split("\n")
    .find((row) => /\b(error|failed|exception|traceback)\b/i.test(row) && !/^=====/.test(row));
  return line ? line.trim().slice(0, 200) : "";
}

// Telegram allows 1024 characters in a document caption.
const CAPTION_MAX = 1024;
const CAPTION_CUT = "… (далі у файлі)";

/** The message with the report file: the player's whole note when it fits. */
export function telegramCaption(id, report) {
  const head = [`Звіт ${id}`, [report.version, report.os, report.lang].filter(Boolean).join(" · ")]
    .filter(Boolean)
    .join("\n");
  if (report.note) {
    const label = `${head}\nГравець: `;
    const note = report.note.trim();
    const room = CAPTION_MAX - label.length;
    return label + (note.length <= room ? note : note.slice(0, room - CAPTION_CUT.length).trimEnd() + CAPTION_CUT);
  }
  const summary = summarize(report);
  return (summary ? `${head}\nПомилка: ${summary}` : head).slice(0, CAPTION_MAX);
}

export function hourWindow(now) {
  return Math.floor(now / 3_600_000);
}
