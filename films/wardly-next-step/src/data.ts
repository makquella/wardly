// Every product string on screen, copied from the Wardly codebase (paths in BRIEF.md), with the
// checks that keep the film honest. Nothing here is invented: if the app's wording changes, update
// it here and in BRIEF.md, never "improve" it.

/** The live overlay card: advice_i18n.py (spend parts) with gold = 1800, as in site/assets/overlay/uk/spend.webp. */
export const LIVE = {
  label: 'Порада', // overlay/app.js uk.tip, the medium-priority card
  action: 'Купіть частини наступного предмета на 1800 золота зараз — заберете їх біля фонтана.',
  reason: 'Невитрачене золото частково втрачається при наступній смерті.',
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

/** Strings that are visible in the app's own screenshots: the noise of the opening. */
export const NOISE = [
  '390 / 430',
  '−210',
  'через 15 с',
  'Торментор',
  '3 / 9 / 6',
  'добивань до 10 −20',
  'золото/хв −179',
  '11 500',
  '38:00',
  'смертей: 9',
  '4:00',
  '−29',
  'Рошан',
  '1800',
  'смертей +6',
  'Maelstrom до 26:00',
  '9 000',
  '160 / 3',
];

/** The end card: the site's address (README, site root is Ukrainian) and the README's "Free … for Windows". */
export const CTA = { url: 'luhovyimvp.dev', free: 'Безкоштовно для Windows' };

// --- checks: the film fails to load if the strings drift from what the product says ---
const assert = (ok: boolean, msg: string) => {
  if (!ok) throw new Error(`data.ts: ${msg}`);
};
assert(LIVE.action.startsWith('Купіть '), 'the live card must start with «Купіть» (the morph lands on it)');
assert(REVIEW.text.startsWith(`${REVIEW.lh10} добивань`) && REVIEW.text.includes(`проти ${REVIEW.peer} `), 'review numbers and text disagree');
assert(REVIEW.lh10 < REVIEW.peer, 'the finding is «behind», so lh10 < peer');
// Ukrainian plural for 36: «добивань» (5-20 and x5-x9, x0 take the genitive plural).
assert(REVIEW.lh10 % 10 >= 5 || REVIEW.lh10 % 10 === 0, 'the number must take «добивань»');
