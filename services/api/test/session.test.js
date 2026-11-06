import assert from "node:assert/strict";
import test from "node:test";
import { gzipSync } from "node:zlib";

import {
  SESSION_LIMITS,
  checkMetaLine,
  firstLine,
  hasGzipMagic,
  isSessionId,
  sessionId,
  sessionKey,
  sessionNote,
  sessionSplit,
  validateSessionHeaders
} from "../src/session.js";

const META = { k: "meta", hero: "npc_dota_hero_juggernaut", payloads: 2, advice: 0, last_clock: 600, format: 1, upload: 1, anonymized: true };

function recording(meta = META, lines = 3) {
  const rows = [JSON.stringify(meta)];
  for (let i = 0; i < lines; i += 1) rows.push(JSON.stringify({ k: "gsi", w: i, ts: `+${i}.000`, p: { map: { clock_time: i } } }));
  return new Uint8Array(gzipSync(Buffer.from(`${rows.join("\n")}\n`)));
}

function headers(extra = {}) {
  return new Headers({
    "x-install-id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
    "x-app-version": "0.63.0",
    "x-hero": "npc_dota_hero_juggernaut",
    "x-minutes": "42",
    "content-length": "1000",
    ...extra
  });
}

test("headers are validated like a report", () => {
  const ok = validateSessionHeaders(headers());
  assert.deepEqual(ok.meta, { installId: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", hero: "npc_dota_hero_juggernaut", minutes: 42, version: "0.63.0", length: 1000 });
  assert.equal(validateSessionHeaders(headers({ "x-hero": "" })).meta.hero, "");
  for (const [bad, code, status] of [
    [{ "x-install-id": "x" }, "bad_install_id", 400],
    [{ "x-hero": "Juggernaut; drop table" }, "bad_hero", 400],
    [{ "x-minutes": "241" }, "bad_minutes", 400],
    [{ "x-minutes": "-1" }, "bad_minutes", 400],
    [{ "x-minutes": "4.5" }, "bad_minutes", 400],
    [{ "content-length": "0" }, "length_required", 411],
    [{ "content-length": String(SESSION_LIMITS.bodyBytes + 1) }, "too_large", 413]
  ]) {
    const answer = validateSessionHeaders(headers(bad));
    assert.deepEqual([answer.ok, answer.code, answer.status], [false, code, status], code);
  }
  assert.equal(validateSessionHeaders(headers({ "x-app-version": "9".repeat(80) })).meta.version.length, 32);
});

test("ids, keys and the tune / holdout split are stable", async () => {
  const id = sessionId(new Uint8Array([0, 1, 2, 3, 4, 5]));
  assert.match(id, /^S-[2-9A-HJ-NP-Z]{6}$/);
  assert.ok(isSessionId(id) && !isSessionId("R-AAAAAA") && !isSessionId("S-0OIl11"));
  assert.equal(sessionKey("S-ABCDEF", new Date(Date.UTC(2026, 10, 6))), "sessions/2026/11/S-ABCDEF.jsonl.gz");
  assert.equal(await sessionSplit("S-ABCDEF"), await sessionSplit("S-ABCDEF"));
  const sides = { tune: 0, holdout: 0 };
  for (let i = 0; i < 400; i += 1) {
    sides[await sessionSplit(sessionId(new Uint8Array([i % 251, (i * 7) % 251, (i * 13) % 251, i >> 3, (i * 3) % 251, i % 97])))] += 1;
  }
  assert.ok(sides.holdout > 40 && sides.holdout < 160, JSON.stringify(sides));
});

test("only a gzip stream with an anonymized meta line passes", async () => {
  const bytes = recording();
  assert.ok(hasGzipMagic(bytes) && !hasGzipMagic(new TextEncoder().encode("plain text, not a gzip file")));
  assert.deepEqual(checkMetaLine(await firstLine(bytes)), { ok: true });
  assert.equal(checkMetaLine("not json").code, "bad_recording");
  assert.equal(checkMetaLine(JSON.stringify({ ...META, anonymized: false })).code, "bad_recording");
  assert.equal(checkMetaLine(JSON.stringify({ k: "gsi", anonymized: true })).code, "bad_recording");
  for (const key of ["steamid", "accountid", "matchid", "match_id", "auth"]) {
    const answer = checkMetaLine(JSON.stringify({ ...META, [key]: "1" }));
    assert.deepEqual([answer.ok, answer.code, answer.status], [false, "not_anonymized", 422], key);
  }
});

test("the first line is read from a cut stream and is bounded", async () => {
  // A recording much larger than the peeked slice: the cut stream still gives line one.
  const big = recording(META, 20000);
  assert.ok(big.length > SESSION_LIMITS.peekCompressed);
  assert.equal(JSON.parse(await firstLine(big)).k, "meta");
  // A meta line carrying an id is seen in the first line only.
  const bad = recording({ ...META, matchid: "8012345678" });
  assert.equal(checkMetaLine(await firstLine(bad)).code, "not_anonymized");
  // Garbage after the magic bytes gives nothing, not an exception.
  assert.equal(await firstLine(new Uint8Array([0x1f, 0x8b, 8, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])), "");
  // A line without a newline is cut at the limit.
  const long = new Uint8Array(gzipSync(Buffer.from("x".repeat(100000))));
  assert.ok((await firstLine(long)).length <= SESSION_LIMITS.firstLineChars + 70000);
});

test("the note for the developer has no file and no player data", () => {
  const note = sessionNote("S-ABCDEF", { hero: "npc_dota_hero_juggernaut", minutes: 42, version: "0.63.0" }, "tune", 3_500_000);
  assert.match(note, /S-ABCDEF \(tune\)/);
  assert.match(note, /42 хв/);
  assert.match(note, /3\.3 МБ/);
});
