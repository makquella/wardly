// Which advice card the overlay shows on a poll (0.66.1). Pure, so the rules run
// in node tests; loaded as a plain script by the overlay (window.OverlayCardHold).
//
// The backend's current card (status active_advice) always shows. After its
// window the backend is in cooldown, and the overlay holds that card for its
// auto-hide time. The deadline is fixed on the card's first cooldown poll, so a
// status or a map hint drawn in between does not extend it. Once over, the
// card never comes back (a «Reset HP» card used to stay through the whole
// cooldown after HP was back, or came back after a respawn). A calm held card
// gives way to a map hint: the hint's window runs on game time and would
// otherwise pass behind a card that is already over (pull and item tips seen
// for 2 s).
(function attach(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.OverlayCardHold = api;
  }
})(typeof self !== "undefined" ? self : this, () => {
  function adviceModeOf(data) {
    return data.advice_mode || (data.recommendation?.priority === "high" ? "urgent" : "coaching");
  }

  // key: the card as drawn; speechKey: what the voice says (a held card whose
  // quoted numbers were refreshed, gold or Wand charges, is the same card).
  function cardKeys(data) {
    const recommendation = data.recommendation || {};
    const tail = [data.match_death_count || 0, data.last_death_minute || ""];
    return {
      key: [data.decision_point, recommendation.action, recommendation.reason, recommendation.priority, ...tail].join("|"),
      speechKey: [data.decision_point, recommendation.action, recommendation.priority, ...tail].join("|")
    };
  }

  // holdMs(adviceMode, card): how long a card stays after the backend's window.
  function createCardHold({ holdMs, now = () => Date.now() }) {
    let expiredKey = "";
    let heldKey = "";
    let heldUntil = 0;

    // data: this poll; last: the card drawn last; hint: the map hint of this
    // poll. Returns {card, refreshTimer, fresh} or null (no card this poll).
    function pick(data, { last = null, hint = null } = {}) {
      if (data.recommendation && data.status === "active_advice") {
        const fresh = Boolean(data.new_advice);
        if (fresh) {
          // A new card, even with the words of an expired one: shown again.
          expiredKey = "";
          heldKey = "";
        }
        return { card: data, refreshTimer: false, fresh };
      }
      if (data.status !== "cooldown") {
        return null;
      }
      const held = data.recommendation
        ? data
        : last?.recommendation
          ? { ...last, is_pinned: Boolean(data.is_pinned), active_advice_until: data.active_advice_until }
          : null;
      if (!held) {
        return null;
      }
      const { key } = cardKeys(held);
      if (key === expiredKey) {
        return null;
      }
      // A pinned card waits for the backend; once let go it gets a normal hold.
      if (key !== heldKey || (heldUntil === Infinity && !held.is_pinned)) {
        heldKey = key;
        heldUntil = held.is_pinned ? Infinity : now() + holdMs(adviceModeOf(held), held);
      }
      if (now() >= heldUntil || (hint && adviceModeOf(held) !== "urgent")) {
        expiredKey = key;
        return null;
      }
      return { card: held, refreshTimer: true, fresh: false };
    }

    // The card is over (its auto-hide ran, the hero died): not shown again.
    function expire(card) {
      if (card?.recommendation) {
        expiredKey = cardKeys(card).key;
      }
    }

    // Asked for again (the repeat hotkey): back for a new hold.
    function reopen() {
      expiredKey = "";
      heldKey = "";
    }

    return { pick, expire, reopen };
  }

  return { adviceModeOf, cardKeys, createCardHold };
});
