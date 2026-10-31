// Geometry shared by the scenes and the sound cues: where every object is, in screen px, so the
// story device (the «?» dot) can travel between them exactly. Product cards are laid out from the
// app's own CSS numbers (overlay/styles.css, renderer/styles.css), with lines wrapped here, so the
// positions are known before anything renders. Browser-only (measures with the loaded fonts).
import { FONT, TYPE } from '../brand/tokens';
import { CUE } from '../timeline';
import { E, prog, mix, clamp } from '../lib/anim';
import { glyphDot } from '../lib/glyph';
import { baselineOf, measureTracked } from '../lib/measure';
import { LIVE, REVIEW } from '../data';

// ---------- text wrapping (greedy, like the browser for plain text without hyphens) ----------
export const wrap = (text: string, width: number, size: number, weight: number, family = FONT.text, first = '') => {
  const words = text.split(' ');
  const lines: string[] = [];
  let line = first;
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (line && measureTracked(next, size, weight, 0, family) > width) {
      lines.push(line);
      line = w;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
};

// ---------- the questions of the review ----------
export const Q_SIZE = TYPE.question.size;
export const Q_LEAD = TYPE.lead.size;
export const Q_GAP = 6; // between the lead line and the keyword line
export const Q_KEY_TOP = Q_LEAD + Q_GAP; // keyword line top inside the block
export const QUESTIONS = [
  { lead: 'Що', key: 'купити' },
  { lead: 'Чому', key: 'відстаю' },
  { lead: 'Що', key: 'змінити' },
];
export const qFont = { size: Q_SIZE, weight: TYPE.question.weight, track: TYPE.question.track, family: FONT.text };

/** The «?» dot of question i in block coordinates (scale 1). */
export const qDotLocal = (i: number) => {
  const d = glyphDot('?', Q_SIZE, qFont.weight, qFont.family);
  const keyW = measureTracked(QUESTIONS[i].key, Q_SIZE, qFont.weight, qFont.track, qFont.family);
  const base = Q_KEY_TOP + baselineOf(Q_SIZE, qFont.weight, TYPE.question.lead, qFont.family);
  return { x: keyW + d.cx, y: base + d.cy, r: d.r, hookTop: Q_KEY_TOP, dotTop: base + d.top };
};

export type QPose = { x: number; y: number; s: number; o: number };

/** Where «Чому відстаю?» and «Що змінити?» enter from: just inside the top and bottom edges. */
export const Q_HOME = {
  q2Wait: { x: 112, y: 300, s: 0.37, o: 0 },
  q3Wait: { x: 112, y: 1396, s: 0.37, o: 0 },
};

// ---------- the live overlay card (overlay/styles.css at 404 px, scaled) ----------
export const LC = { x: 67, y: 740, S: 2.5, w: 356 }; // the overlay at a narrower window, scaled for a phone
export const LC_IN = { pad: 12, padX: 16, border: 1 };
/** The death-screen card (overlay/styles.css: .plan .action 14 px, .items-row 32x24 icons, .reason pre-line, 2 lines). */
export const lcLayout = () => {
  const content = LC.w - 2 * (LC_IN.padX + LC_IN.border);
  const action = wrap(LIVE.action, content, 14, 600);
  const reason = wrap(LIVE.reason, content, 13, 400).slice(0, 2);
  const rowTop = LC_IN.border + LC_IN.pad;
  const actionTop = rowTop + 15 + 4;
  const itemsTop = actionTop + action.length * 18.9 + 4;
  const reasonTop = itemsTop + 24 + 4;
  const h = Math.min(160, reasonTop + reason.length * 18.2 + LC_IN.pad + LC_IN.border); // .overlay-shell max-height
  const x0 = LC_IN.border + LC_IN.padX;
  return {
    action,
    reason,
    rowTop,
    actionTop,
    itemsTop,
    reasonTop,
    h,
    x0,
    dot: { x: x0 + 3, y: rowTop + 7.5, r: 3 },
    icon: { x: x0, y: itemsTop, w: 32, h: 24 },
  };
};

/** The live card's camera: a slow push while it is read; it recedes before the review. */
export const lcPose = (f: number) => {
  const push = 1 + 0.09 * prog(f, CUE.cardDone, CUE.away, E.linear); // never frozen while it is read
  const q = prog(f, CUE.away, CUE.away + 36, E.in);
  return { k: push * mix(1, 0.86, q), dy: mix(0, 60, q), o: 1 - prog(f, CUE.away + 6, CUE.away + 36, E.smooth) };
};

/** Card-local point → screen, for a card at (x, y), scale S·k about its centre (cx, cy), shifted dy. */
export const cardToScreen = (card: { x: number; y: number; S: number }, c: { x: number; y: number }, k: number, dy: number, p: { x: number; y: number }) => ({
  x: card.x + c.x * card.S + (p.x - c.x) * card.S * k,
  y: card.y + c.y * card.S + (p.y - c.y) * card.S * k + dy,
});

// ---------- the review focus card (renderer/styles.css .card + .finding, 370 px, scaled) ----------
export const RC = { x: 67, y: 690, S: 2.7, w: 330 }; // the review column, scaled for a phone
export const rcLayout = () => {
  const bodyX = 1 + 20 + 22 + 12; // border, padding, index, gap
  const bodyW = RC.w - 2 - 40 - 34;
  const titleW = measureTracked(REVIEW.title, 14, 600, 0);
  const tagW = measureTracked(REVIEW.tag, 12, 400, 0) + 12 + 2;
  const tagWraps = titleW + 8 + tagW > bodyW;
  const titleTop = 61;
  const titleH = tagWraps ? 20.3 + 8 + 21.4 : Math.max(20.3, 21.4);
  const text = wrap(REVIEW.text, bodyW, 13, 400);
  const textTop = titleTop + titleH + 2;
  const drillTop = textTop + text.length * 18.85 + 8;
  const drillTextW = bodyW - 24 - 16 - 8;
  const drill = wrap(REVIEW.drill, drillTextW, 13, 400, FONT.text, `${REVIEW.drillLabel}:`);
  const drillH = 16 + drill.length * 18.85;
  const h = drillTop + drillH + 20 + 1;
  return {
    bodyX,
    bodyW,
    tagWraps,
    titleTop,
    titleH,
    text,
    textTop,
    drill,
    drillTop,
    drillH,
    h,
    hNoDrill: drillTop - 8 + 20 + 1,
    index: { x: 1 + 20 + 11, y: titleTop + 11, r: 11 },
    redDot: { x: 1 + 20 + 11, y: drillTop + 8 + 18.85 / 2, r: 5 },
  };
};

/** Review camera: push onto the numbers on «відстали», then reframe onto the drill, then clear. */
export const rcCam = (f: number) => {
  const inP = prog(f, CUE.review - 10, CUE.review + 24, E.out);
  const push = prog(f, CUE.push - 6, CUE.push + 40, E.cam);
  const reframe = prog(f, CUE.drill - 4, CUE.drill + 50, E.cam);
  const drift = 1 + 0.05 * prog(f, CUE.review, CUE.push, E.linear); // never frozen while it is read
  const k = drift * mix(1, 1.07, push) * mix(1, 1 / 1.07, reframe) * (1 + 0.025 * prog(f, CUE.drill + 50, CUE.clear, E.dolly));
  const dy = mix(30, 0, inP) + mix(0, -170, reframe);
  const out = prog(f, CUE.clear, CUE.clear + 30, E.in);
  return { k: k * mix(1, 0.9, out), dy: dy + mix(0, 50, out), o: inP * (1 - prog(f, CUE.clear + 4, CUE.clear + 30, E.smooth)) };
};

export const clamp01 = clamp;
