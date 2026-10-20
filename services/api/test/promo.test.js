import assert from "node:assert/strict";
import test from "node:test";

import {
  kyivTime,
  localDateTime,
  matchItem,
  metricoolPost,
  numbers,
  promoNetworks,
  validatePromo,
  webhookSecret,
  weeklyPromoText,
  youtubeSchedule
} from "../src/promo.js";

const PACKAGE = {
  id: "0123456789abcdef",
  format: "meta",
  topic: "2026-10-12",
  hook: 2,
  title: "Мета тижня",
  youtube_title: "Мета тижня #shorts",
  caption: "Мета тижня (4–10 жовтня) — найбільше перемог:\n1. Wraith King",
  telegram_caption: "Мета тижня"
};

test("a package needs an id, a known format and captions within the limits", () => {
  assert.equal(validatePromo(PACKAGE).id, PACKAGE.id);
  assert.equal(validatePromo({ ...PACKAGE, id: "../../etc" }), null);
  assert.equal(validatePromo({ ...PACKAGE, format: "ad" }), null);
  assert.equal(validatePromo({ ...PACKAGE, format: "draft" }).id, PACKAGE.id);
  assert.equal(validatePromo({ ...PACKAGE, caption: "x".repeat(2201) }), null);
  assert.equal(validatePromo({ ...PACKAGE, youtube_title: "" }), null);
});

test("localized YouTube metadata is bounded and legacy packages retain their defaults", () => {
  assert.equal(validatePromo(PACKAGE).body.youtube_language, undefined);
  const metadata = { youtube_tags: ["Dota 2", "Wardly", "beta test"], youtube_language: "en" };
  const body = validatePromo({ ...PACKAGE, ...metadata }).body;
  assert.deepEqual(body.youtube_tags, metadata.youtube_tags);
  assert.equal(body.youtube_language, "en");
  for (const invalid of [[], [3], [" "], ["a\nb"], ["<bad>"], Array(31).fill("tag"), Array(8).fill("x".repeat(80))]) {
    assert.equal(validatePromo({ ...PACKAGE, youtube_tags: invalid }), null);
  }
  assert.equal(validatePromo({ ...PACKAGE, youtube_language: "invalid" }), null);
});

test("a YouTube publish time is a UTC minute, kept only when the button comes well before it", () => {
  const at = "2026-10-21T14:00:00Z";
  assert.equal(validatePromo(PACKAGE).body.youtube_publish_at, undefined);
  assert.equal(validatePromo({ ...PACKAGE, youtube_publish_at: at }).body.youtube_publish_at, at);
  for (const invalid of ["2026-10-21T14:00:00", "2026-10-21T14:00:30Z", "2026-10-21 14:00", "2026-13-40T14:00:00Z", 1761055200000, ""]) {
    assert.equal(validatePromo({ ...PACKAGE, youtube_publish_at: invalid }), null, String(invalid));
  }
  assert.equal(youtubeSchedule({}, 0), null);
  assert.equal(youtubeSchedule({ youtube_publish_at: at }, Date.parse(at) - 3_600_000), "scheduled");
  assert.equal(youtubeSchedule({ youtube_publish_at: at }, Date.parse(at) - 10 * 60_000), "late");
  assert.equal(youtubeSchedule({ youtube_publish_at: at }, Date.parse(at) + 60_000), "late");
  // Kyiv is UTC+3 in summer time and UTC+2 after the last Sunday of October.
  assert.equal(kyivTime(at), "21.10 17:00");
  assert.equal(kyivTime("2026-10-27T14:00:00Z"), "27.10 16:00");
});

test("the webhook secret comes from the bot token and fits Telegram's charset", async () => {
  const secret = await webhookSecret("123:abc");
  assert.match(secret, /^[a-f0-9]{48}$/);
  assert.notEqual(secret, await webhookSecret("123:abd"));
});

test("Metricool gets Kyiv wall time, a draft unless publishing is switched on", () => {
  const now = Date.UTC(2026, 9, 12, 21, 0, 0); // 00:00 next day in Kyiv (UTC+3)
  assert.equal(localDateTime(now, "Europe/Kyiv"), "2026-10-13T00:00:00");
  const body = { caption: "c", title: "t", youtube_title: "yt" };
  const draft = metricoolPost({}, body, "https://m/v.mp4", now);
  assert.equal(draft.post.draft, true);
  assert.equal(draft.post.autoPublish, false);
  assert.equal(draft.post.publicationDate.dateTime, "2026-10-13T00:15:00");
  assert.equal(draft.post.instagramData.type, "REEL");
  assert.equal(draft.post.youtubeData.title, "yt");
  const live = metricoolPost({ PROMO_METRICOOL_MODE: "publish", PROMO_NETWORKS: "tiktok" }, body, "u", now);
  assert.equal(live.post.autoPublish, true);
  assert.deepEqual(live.networks, ["tiktok"]);
  assert.equal(live.post.instagramData, undefined);
  assert.deepEqual(promoNetworks({ PROMO_NETWORKS: "facebook" }), ["instagram", "tiktok", "youtube"]);
});

test("statistics find the post by its URL or by the start of its caption", () => {
  const post = { body: PACKAGE };
  const reels = [
    { url: "https://ig/1", content: "Інше відео", views: 5 },
    { url: "https://ig/2", content: "Мета тижня (4–10 жовтня) — найбільше перемог: ...", views: 1200, likes: 40 }
  ];
  assert.equal(matchItem(reels, post, "instagram", null).url, "https://ig/2");
  assert.equal(matchItem(reels, post, "instagram", "https://ig/1").views, 5);
  const tiktok = [{ shareUrl: "s", videoDescription: "Мета тижня (4–10 жовтня) — найбільше", viewCount: 900, likeCount: 30, shareCount: 2 }];
  assert.deepEqual(numbers(matchItem(tiktok, post, "tiktok", null)), { views: 900, likes: 30, comments: 0, shares: 2 });
  const youtube = [{ title: "Мета тижня #shorts", views: 300 }];
  assert.equal(matchItem(youtube, post, "youtube", null).views, 300);
  assert.equal(matchItem([{ title: "Інше" }], post, "youtube", null), null);
});

test("the weekly note ranks formats by average views", () => {
  const text = weeklyPromoText([
    { format: "coach", topic: "sniper", status: "scheduled", views: 900, likes: 30 },
    { format: "coach", topic: "axe", status: "scheduled", views: 100, likes: 2 },
    { format: "meta", topic: "2026-10-12", status: "published", views: 300, likes: 9 },
    { format: "hero", topic: "lion", status: "rejected", views: 0, likes: 0 }
  ]);
  assert.match(text, /coach: 2 відео, у середньому 500 переглядів/);
  assert.ok(text.indexOf("coach") < text.indexOf("meta"));
  assert.match(text, /Найкраще: coach · sniper — 900/);
  assert.ok(!text.includes("hero"));
  assert.equal(weeklyPromoText([]), null);
});
