"use strict";

// Sending one match recording to the developer (docs/DATA_PLAN.md, stage 5).
// Only the player's click on «Send» for that one recording starts it; nothing
// here runs by itself. The pure parts (who is asked, what is remembered, which
// message an error code gets) are tested in test/match-upload.test.js; main.js
// supplies the two network calls.

const crypto = require("node:crypto");

const SENT_KEEP_DAYS = 60; // the server deletes a recording after 60 days
const DAY_MS = 86_400_000;

// What /v1/config says about recordings; anything odd means «not offered».
function parseConfig(body) {
  const config = body && typeof body === "object" ? body : {};
  const sample = Number(config.recordings_sample);
  return {
    recordings: config.recordings === true,
    sample: Number.isFinite(sample) ? Math.min(Math.max(sample, 0), 1) : 1,
    days: Number.isFinite(config.recording_days) ? config.recording_days : SENT_KEEP_DAYS
  };
}

// The server asks a share of installations. The choice comes from the install
// id, so an installation does not flip between «asked» and «not asked» by day.
function inSample(installId, sample) {
  if (!(sample > 0)) {
    return false;
  }
  if (sample >= 1) {
    return true;
  }
  const digest = crypto.createHash("sha256").update(`dac-sample:${installId}`).digest();
  return digest.readUInt32BE(0) / 2 ** 32 < sample;
}

function uploadOffered(config, installId) {
  return Boolean(config.recordings) && inSample(installId, config.sample);
}

// {localId: {id, sentAt}} without entries older than the server keeps files.
function pruneSent(sent, now = Date.now()) {
  const kept = {};
  for (const [localId, entry] of Object.entries(sent && typeof sent === "object" ? sent : {})) {
    const at = Date.parse(entry && entry.sentAt);
    if (entry && /^S-[A-Z0-9]{6}$/.test(String(entry.id)) && Number.isFinite(at) && now - at < SENT_KEEP_DAYS * DAY_MS) {
      kept[localId] = { id: entry.id, sentAt: entry.sentAt };
    }
  }
  return kept;
}

function rememberSent(sent, localId, id, now = Date.now()) {
  return { ...pruneSent(sent, now), [localId]: { id, sentAt: new Date(now).toISOString() } };
}

// The text key the renderer shows for a failure.
function errorKey(code) {
  switch (code) {
    case "rate_limited":
    case "too_large":
    case "disabled":
    case "storage_unavailable":
    case "storage_full":
    case "recording_active":
      return code;
    case "offline":
    case "network":
      return "network";
    default:
      return "failed";
  }
}

function uploadHeaders({ installId, version, hero, minutes, device = {} }) {
  return {
    "content-type": "application/gzip",
    "x-install-id": installId,
    "x-app-version": String(version || ""),
    "x-hero": hero || "",
    "x-minutes": String(Math.max(0, Math.min(240, Number(minutes) || 0))),
    ...device
  };
}

// One send. `getCopy(localId)` → {ok, body, hero, minutes} | {ok: false, code}
// (the local backend's anonymized copy); `post(headers, body)` → {ok, id} |
// {ok: false, code}. A recording that was sent is not sent twice.
async function sendRecording({ localId, sent, installId, version, device, getCopy, post, now = Date.now() }) {
  const known = pruneSent(sent, now)[localId];
  if (known) {
    return { ok: true, already: true, id: known.id };
  }
  const copy = await getCopy(localId);
  if (!copy.ok) {
    return { ok: false, code: errorKey(copy.code) };
  }
  const answer = await post(uploadHeaders({ installId, version, hero: copy.hero, minutes: copy.minutes, device }), copy.body);
  return answer.ok ? { ok: true, id: answer.id } : { ok: false, code: errorKey(answer.code) };
}

module.exports = { SENT_KEEP_DAYS, errorKey, inSample, parseConfig, pruneSent, rememberSent, sendRecording, uploadHeaders, uploadOffered };
