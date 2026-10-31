// Every product string on screen, copied from the Wardly codebase (paths in BRIEF.md), with the
// checks that keep the film honest. Nothing here is invented: if the app's wording changes, update
// it here and in BRIEF.md, never "improve" it.

/**
 * The live overlay card: the death screen (backend/app/death_screen.py, uk), the card the overlay
 * shows while the player waits to respawn (overlay/app.js showDeathScreen: class "plan
 * death-screen", the title as its label, the first line as the action, the item to buy as its icon
 * under it, the other lines as the reason). Black King Bar comes from situational_items.py: two
 * deaths held by stuns with no free second ("disabled"), the gold for it in hand.
 */
export const LIVE = {
  label: 'Відродження через 23 с', // TEXT.uk.title, s = 23
  action: "Купіть Black King Bar зараз: золота вистачає, кур'єр принесе.", // TEXT.uk.buy_item
  item: { key: 'black_king_bar', name: 'Black King Bar' }, // card["items"]: the icon of the item the buy line names
  reason: 'Чому Black King Bar: смертей під контролем — 2, з ним контроль вас не втримає.', // TEXT.uk.why_disabled, n = 2
};

/**
 * The opening's Dota material: a carry Juggernaut's inventory around minute 20, from his own plan
 * (data/heroes/item_plans/juggernaut.json: Power Treads, Battle Fury, Manta Style; Magic Wand and
 * Wraith Band from the start of the build_basis), the slot left empty for the choice, and the two
 * candidates: the plan's next damage item (Butterfly) and the item the card names (Black King Bar).
 * Icons: Valve's CDN (tools/fetch_dota.py), the same pictures the app shows.
 */
export const DOTA = {
  hero: 'juggernaut',
  slots: ['power_treads', 'bfury', 'manta', 'magic_wand', 'wraith_band', null] as (string | null)[],
  tp: 'tpscroll',
  damage: 'butterfly',
  answer: 'black_king_bar',
};

/** The post-match focus card: renderer/matches.js focusCard + findingItem, texts from analysis_texts.py. */
export const REVIEW = {
  head: 'Головне на наступну гру', // match-texts.js uk.focusTitle
  index: '1',
  title: 'Програли лінію за добиваннями', // FINDINGS.peer_lh10_behind.uk.title
  tag: 'Лінія', // SECTIONS.laning.uk
  // FINDINGS.peer_lh10_behind.uk.text with lh10 = 36, peer_lh10 = 65, role_label = PEER_ROLES.carry.uk,
  // heroes = Anti-Mage: the numbers of the app's demo review (site/assets/app/uk/review-ai.jpg).
  lh10: 36,
  peer: 65,
  text: '36 добивань до 10:00 проти 65 у керрі у цьому матчі (Anti-Mage).',
  drillLabel: 'Вправа', // match-texts.js uk.drill
  drill: 'На лінії стежте за HP кріпів і бийте, коли вистачить одного удару; тримайте суперника під тиском, коли він добиває.',
};

/** The end card: the site's address (README, site root is Ukrainian) and the README's "Free … for Windows". */
export const CTA = { url: 'luhovyimvp.dev', free: 'Безкоштовно для Windows' };

// --- checks: the film fails to load if the strings drift from what the product says ---
const assert = (ok: boolean, msg: string) => {
  if (!ok) throw new Error(`data.ts: ${msg}`);
};
assert(LIVE.action.startsWith(`Купіть ${LIVE.item.name} `) && LIVE.reason.startsWith(`Чому ${LIVE.item.name}:`), 'the card must name the item it shows');
assert(DOTA.answer === LIVE.item.key, 'the chosen icon is the one the card shows');
assert(REVIEW.text.startsWith(`${REVIEW.lh10} добивань`) && REVIEW.text.includes(`проти ${REVIEW.peer} `), 'review numbers and text disagree');
assert(REVIEW.lh10 < REVIEW.peer, 'the finding is «behind», so lh10 < peer');
// Ukrainian plural for 36: «добивань» (5-20 and x5-x9, x0 take the genitive plural).
assert(REVIEW.lh10 % 10 >= 5 || REVIEW.lh10 % 10 === 0, 'the number must take «добивань»');
