// Brand tokens: the only place a colour, face or type size is written down. Acts import these;
// scripts/lint-film.mjs fails any hex colour that is not declared here.
// Wardly's own palette (frontend/launcher/assets/ui/tokens.css, site/styles.css): the dark page,
// the app's surfaces and text greys, and the logo's red as the one accent.
import type React from 'react';
import { safeInsets } from '../lib/safe';
import { H, W } from '../timeline';

export const C = {
  ink: '#0C0D10', // the page (--bg): the film's stage
  surface1: '#15161A', // app cards (--surface-1)
  surface2: '#1C1D22', // raised rows inside a card (--surface-2)
  text: '#F2F2F4', // --text
  text2: '#A3A5AD', // --text-2: secondary text
  text3: '#70737C', // --text-3: tertiary text, the chaos fragments
  idle: '#52525B', // --idle
  border: 'rgba(255, 255, 255, 0.065)', // --border
  borderStrong: 'rgba(255, 255, 255, 0.11)', // --border-strong
  overlayBg: 'rgba(12, 13, 16, 0.88)', // the overlay card's own background (overlay/styles.css)
  // The one accent, and what it means: "the next step". The logo's red (--accent on dark text,
  // --accent-fill for shapes). It arrives only when an answer turns into an action.
  accent: '#F05560',
  accentFill: '#D23A46',
  logoDot: '#D93740', // the red dot as drawn in site/assets/logo.png (measured)
  // Product UI states, reproduced exactly (BRIEF.md, brand-supplied exceptions):
  warn: '#E5B454', // cinetic:brand-supplied the overlay's amber «Порада» dot (--warn)
  cream: '#EFE5D4', // cinetic:brand-supplied the logo eye's cream (--cream)
  white: '#FFFFFF',
  mute: '#70737C', // = text3, the name the starter's helpers (Audit, Scramble) use
};

export const FONT = {
  text: '"Inter Variable", system-ui, sans-serif', // the app and overlay face; the questions
  display: '"Montserrat Variable", "Inter Variable", sans-serif', // site headlines, the wordmark, the slogan
  mono: '"Inter Variable", system-ui, sans-serif', // no mono in this film (tabular Inter instead)
};

/** Faces the FontGate waits for before anything renders or measures (one entry per weight in use). */
export const FACES = [
  '400 16px "Inter Variable"',
  '500 16px "Inter Variable"',
  '600 16px "Inter Variable"',
  '800 16px "Inter Variable"',
  '700 16px "Montserrat Variable"',
  '600 16px "Montserrat Variable"',
];

/** Layout unit: 1 at 1080p, scales every size with the short side of the frame. */
export const U = Math.min(W, H) / 1080;

// One token per role, reused everywhere (size in px at 1080 wide).
export const TYPE = {
  question: { size: 164, weight: 800, track: -0.035, lead: 1.0 }, // the keyword of a question
  lead: { size: 88, weight: 700, track: -0.03, lead: 1.0 }, // the small first word of a question
  display: { size: 92, weight: 700, track: -0.03, lead: 1.08 }, // the slogan as a statement
  line: { size: 54, weight: 600, track: -0.02, lead: 1.18 }, // the slogan on the end card
  wordmark: { size: 124, weight: 700, track: -0.02, lead: 1.0 }, // «Wardly»
  secondary: { size: 44, weight: 500, track: -0.01, lead: 1.2 }, // «Безкоштовно для Windows»
  url: { size: 64, weight: 600, track: -0.01, lead: 1.1 }, // the address
  ui: { size: 32, weight: 500, track: 0, lead: 1.3 }, // smallest readable size on screen
};

export type Role = keyof typeof TYPE;

/** CSS for a type role at a size (px). Tabular figures always, so numbers never jitter in width. */
export const typeStyle = (role: Role, size = TYPE[role].size * U, family = FONT.text): React.CSSProperties => ({
  fontFamily: family,
  fontSize: size,
  fontWeight: TYPE[role].weight,
  letterSpacing: `${TYPE[role].track}em`,
  lineHeight: TYPE[role].lead,
  fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'pre',
});

/** Symmetric safe margins for a frame (lib/safe.ts presets). */
export const safeArea = (w: number, h: number) => {
  const i = safeInsets(undefined, w, h);
  return { x: Math.max(i.left, i.right), y: Math.max(i.top, i.bottom) };
};
export const SAFE = safeArea(W, H);
