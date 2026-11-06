const assert = require("node:assert/strict");
const test = require("node:test");

const {
  errorKey,
  inSample,
  parseConfig,
  pruneSent,
  rememberSent,
  sendRecording,
  uploadHeaders,
  uploadOffered
} = require("../match-upload");

const DAY = 86_400_000;
const NOW = Date.parse("2026-11-06T12:00:00Z");

test("the config switches recordings on only when the server says so", () => {
  assert.deepEqual(parseConfig({ recordings: true, recordings_sample: 0.5, recording_days: 60 }), { recordings: true, sample: 0.5, days: 60 });
  for (const body of [null, {}, { recordings: "true" }, { recordings: false, recordings_sample: 1 }, "x"]) {
    assert.equal(uploadOffered(parseConfig(body), "install-aaaaaaaa"), false);
  }
  assert.equal(parseConfig({ recordings: true, recordings_sample: "x" }).sample, 1);
  assert.equal(parseConfig({ recordings: true, recordings_sample: 9 }).sample, 1);
  assert.equal(parseConfig({ recordings: true, recordings_sample: -2 }).sample, 0);
});

test("the sample decision is stable per installation and follows the share", () => {
  assert.equal(inSample("install-aaaaaaaa", 1), true);
  assert.equal(inSample("install-aaaaaaaa", 0), false);
  assert.equal(inSample("install-aaaaaaaa", 0.3), inSample("install-aaaaaaaa", 0.3));
  let asked = 0;
  for (let i = 0; i < 2000; i += 1) asked += inSample(`install-${i}-aaaa`, 0.25) ? 1 : 0;
  assert.ok(asked > 400 && asked < 600, String(asked));
  // A bigger share keeps everyone who was asked before.
  for (let i = 0; i < 200; i += 1) {
    if (inSample(`install-${i}-aaaa`, 0.1)) assert.ok(inSample(`install-${i}-aaaa`, 0.5));
  }
});

test("sent recordings are remembered for 60 days only", () => {
  const sent = rememberSent({}, "rec-1", "S-ABCDEF", NOW - 61 * DAY);
  const next = rememberSent(sent, "rec-2", "S-GHJKLM", NOW);
  assert.deepEqual(Object.keys(next), ["rec-2"], "the old one was forgotten with the server's copy");
  assert.equal(next["rec-2"].id, "S-GHJKLM");
  assert.deepEqual(pruneSent({ a: { id: "S-ABCDEF", sentAt: new Date(NOW - 59 * DAY).toISOString() } }, NOW), {
    a: { id: "S-ABCDEF", sentAt: new Date(NOW - 59 * DAY).toISOString() }
  });
  for (const bad of [null, "x", { a: null }, { a: { id: "../x", sentAt: new Date(NOW).toISOString() } }, { a: { id: "S-ABCDEF", sentAt: "yesterday" } }]) {
    assert.deepEqual(pruneSent(bad, NOW), {});
  }
});

test("server codes map to a small set of messages", () => {
  for (const code of ["rate_limited", "too_large", "disabled", "storage_unavailable"]) assert.equal(errorKey(code), code);
  assert.equal(errorKey("offline"), "network");
  for (const code of ["bad_recording", "not_anonymized", "http_500", undefined, "unredacted"]) assert.equal(errorKey(code), "failed");
});

test("upload headers carry only the install, the version, the hero and the minutes", () => {
  const headers = uploadHeaders({ installId: "install-aaaaaaaa", version: "0.63.0", hero: "npc_dota_hero_axe", minutes: 400, device: { "x-device-key": "k" } });
  assert.deepEqual(headers, {
    "content-type": "application/gzip",
    "x-install-id": "install-aaaaaaaa",
    "x-app-version": "0.63.0",
    "x-hero": "npc_dota_hero_axe",
    "x-minutes": "240",
    "x-device-key": "k"
  });
});

test("a recording is sent once, and a failure keeps it unsent", async () => {
  const calls = [];
  const base = {
    localId: "2026-11-05_2100_8012345678",
    sent: {},
    installId: "install-aaaaaaaa",
    version: "0.63.0",
    now: NOW,
    getCopy: async (id) => {
      calls.push(["copy", id]);
      return { ok: true, body: Buffer.from("gzip"), hero: "npc_dota_hero_axe", minutes: 31 };
    }
  };
  const ok = await sendRecording({
    ...base,
    post: async (headers, body) => {
      calls.push(["post", headers["x-hero"], headers["x-minutes"], body.toString()]);
      return { ok: true, id: "S-ABCDEF" };
    }
  });
  assert.deepEqual(ok, { ok: true, id: "S-ABCDEF" });
  assert.deepEqual(calls.at(-1), ["post", "npc_dota_hero_axe", "31", "gzip"]);
  // The local file name (it carries the match id) never goes to the server.
  assert.ok(!JSON.stringify(calls.filter((c) => c[0] === "post")).includes("8012345678"));

  const before = calls.length;
  const again = await sendRecording({ ...base, sent: rememberSent({}, base.localId, "S-ABCDEF", NOW), post: async () => assert.fail("sent twice") });
  assert.deepEqual(again, { ok: true, already: true, id: "S-ABCDEF" });
  assert.equal(calls.length, before, "not even the copy is built again");

  assert.deepEqual(await sendRecording({ ...base, post: async () => ({ ok: false, code: "offline" }) }), { ok: false, code: "network" });
  assert.deepEqual(await sendRecording({ ...base, post: async () => ({ ok: false, code: "rate_limited" }) }), { ok: false, code: "rate_limited" });
  assert.deepEqual(
    await sendRecording({ ...base, getCopy: async () => ({ ok: false, code: "too_large" }), post: async () => assert.fail("no copy") }),
    { ok: false, code: "too_large" }
  );
});
