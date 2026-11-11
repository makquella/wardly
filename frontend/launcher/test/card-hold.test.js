const assert = require("node:assert/strict");
const test = require("node:test");

const { adviceModeOf, cardKeys, createCardHold } = require("../overlay/card-hold");

const RESET_HP = {
  decision_point: "LOW_HP",
  advice_mode: "urgent",
  recommendation: { action: "Reset HP before showing on another lane.", reason: "At this HP...", priority: "high" }
};
const ITEM = {
  decision_point: "ITEM_TIMING",
  advice_mode: "coaching",
  recommendation: { action: "Buy Black King Bar next.", reason: "Two stuns.", priority: "medium" }
};
const PULL = { id: "pull@315", title: "Pull at 5:15" };

function hold(clock) {
  return createCardHold({ holdMs: (mode) => (mode === "urgent" ? 12000 : 8000), now: () => clock.t });
}

const active = (card, extra = {}) => ({ ...card, status: "active_advice", ...extra });
const cooldown = (card = null) => ({ status: "cooldown", decision_point: "SAFE_FARMING", recommendation: null, ...card });

test("a held card leaves at its deadline and never comes back in the same cooldown", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  assert.equal(cards.pick(active(RESET_HP)).card.recommendation.action, RESET_HP.recommendation.action);

  // The backend's window is over and the situation changed (no card in the cooldown).
  clock.t = 1000;
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }).refreshTimer, true);
  clock.t = 12000;
  assert.ok(cards.pick(cooldown(), { last: RESET_HP }), "still within the urgent hold");
  clock.t = 13000;
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }), null);
  clock.t = 40000;
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }), null, "the 0.66.0 card stayed for the whole cooldown");
  // The backend repeating the same matching card in its cooldown does not revive it either.
  assert.equal(cards.pick(cooldown(RESET_HP)), null);
});

test("a status or a hint drawn in between does not extend the hold", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  cards.pick(active(RESET_HP));
  clock.t = 1000;
  cards.pick(cooldown(), { last: RESET_HP });
  clock.t = 5000;
  assert.equal(cards.pick({ status: "monitoring" }, { last: RESET_HP }), null);
  clock.t = 14000;
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }), null);
});

test("a calm held card gives way to a map hint; an urgent one keeps its hold", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  cards.pick(active(ITEM));
  clock.t = 1000;
  assert.ok(cards.pick(cooldown(), { last: ITEM }));
  assert.equal(cards.pick(cooldown(), { last: ITEM, hint: PULL }), null);
  assert.equal(cards.pick(cooldown(), { last: ITEM }), null, "the hint ended it: it does not return after the hint");

  const urgent = hold({ t: 0 });
  urgent.pick(active(RESET_HP));
  assert.ok(urgent.pick(cooldown(), { last: RESET_HP, hint: PULL }));
  // The backend's current card always shows, hint or not.
  assert.ok(cards.pick(active(ITEM), { hint: PULL }));
});

test("a card ended by a death does not return after the respawn", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  cards.pick(active(RESET_HP));
  cards.expire(RESET_HP);
  clock.t = 1000;
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }), null);
});

test("a new card with the words of an expired one shows again; the repeat hotkey reopens", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  cards.pick(active(RESET_HP));
  cards.expire(RESET_HP);
  // Still the old card's window (not new): it shows, the backend says it is current.
  assert.equal(cards.pick(active(RESET_HP)).fresh, false);
  const again = cards.pick(active(RESET_HP, { new_advice: true }));
  assert.equal(again.fresh, true);
  clock.t = 1000;
  assert.ok(cards.pick(cooldown(), { last: RESET_HP }), "held again after the new card");

  cards.expire(RESET_HP);
  assert.equal(cards.pick(cooldown(), { last: RESET_HP }), null);
  cards.reopen();
  assert.ok(cards.pick(cooldown(), { last: RESET_HP }));
});

test("a pinned card is held until the backend lets it go", () => {
  const clock = { t: 0 };
  const cards = hold(clock);
  const death = { ...RESET_HP, decision_point: "DEATH_REVIEW" };
  clock.t = 10 ** 9;
  assert.ok(cards.pick({ ...cooldown(), is_pinned: true }, { last: death }));
  // Let go: a normal hold from now.
  assert.ok(cards.pick(cooldown(), { last: death }));
  clock.t += 12001;
  assert.equal(cards.pick(cooldown(), { last: death }), null);
});

test("keys and modes", () => {
  assert.equal(adviceModeOf({ recommendation: { priority: "high" } }), "urgent");
  assert.equal(adviceModeOf({ advice_mode: "status", recommendation: { priority: "high" } }), "status");
  assert.equal(adviceModeOf({ recommendation: {} }), "coaching");
  const refreshed = { ...ITEM, recommendation: { ...ITEM.recommendation, reason: "Three stuns." } };
  assert.notEqual(cardKeys(ITEM).key, cardKeys(refreshed).key);
  assert.equal(cardKeys(ITEM).speechKey, cardKeys(refreshed).speechKey);
  assert.equal(cardKeys({}).key, "||||0|");
});
