// Geometry shared by the scenes and the sound cues: where every object is, in screen px, so the
// story device (the «?» dot) can travel between them exactly. Product cards are laid out from the
// app's own CSS numbers (overlay/styles.css, renderer/styles.css), with lines wrapped here, so the
// positions are known before anything renders. Browser-only (measures with the loaded fonts).
import { FONT, TYPE } from '../brand/tokens';
import { CUE } from '../timeline';
import { E, prog, mix, clamp, hitPulse } from '../lib/anim';
import { glyphDot } from '../lib/glyph';
import { baselineOf, measureTracked } from '../lib/measure';
import { track } from '../lib/track';
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

// ---------- the questions ----------
export const Q_SIZE = TYPE.question.size;
export const Q_LEAD = TYPE.lead.size;
export const Q_GAP = 6; // between the lead line and the keyword line
export const Q_KEY_TOP = Q_LEAD + Q_GAP; // keyword line top inside the block
export const QUESTIONS = [
  { lead: 'Що', key: 'купити', cue: CUE.q1 },
  { lead: 'Чому', key: 'відстаю', cue: CUE.q2 },
  { lead: 'Що', key: 'змінити', cue: CUE.q3 },
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
const SLAM = 6; // frames from the spoken word to the contact
export const slamOf = (i: number) => QUESTIONS[i].cue + SLAM;

// Chaos layout: each question slams in, shoving the earlier ones back; the storm tightens the pile;
// the break sends Q2 and Q3 to the edges to wait and leaves Q1 in the centre.
export const Q_HOME = {
  q1: { x: 112, y: 671 }, // the morph happens here: «купити» is already level with the card's first line
  q2Wait: { x: 112, y: 300, s: 0.36, o: 0.3 },
  q3Wait: { x: 112, y: 1396, s: 0.36, o: 0.3 },
};
const DIM = 0.36;
const BRK0 = CUE.brk + 6; // a six-frame freeze, then the break moves

export const qPose = (i: number, f: number): QPose => {
  const s1 = slamOf(0);
  const s2 = slamOf(1);
  const s3 = slamOf(2);
  const keys: Record<number, Parameters<typeof track<QPose>>[1]> = {
    0: [
      { f: QUESTIONS[0].cue, v: { x: 104, y: 700, s: 1.34, o: 0 } },
      { f: s1, v: { x: 104, y: 760, s: 1, o: 1 }, e: E.contact },
      { f: s2 + 20, v: { x: 96, y: 900, s: 0.84, o: DIM }, dur: 20 },
      { f: s3 + 20, v: { x: 180, y: 800, s: 0.74, o: DIM }, dur: 20 },
      { f: CUE.brk, v: { x: 150, y: 780, s: 0.8, o: DIM }, e: E.smooth, dur: 40 },
      { f: CUE.settle + 10, v: { x: Q_HOME.q1.x, y: Q_HOME.q1.y, s: 1, o: 1 }, e: E.rest, dur: CUE.settle + 10 - BRK0 },
    ],
    1: [
      { f: QUESTIONS[1].cue, v: { x: 150, y: 500, s: 1.34, o: 0 } },
      { f: s2, v: { x: 150, y: 560, s: 1, o: 1 }, e: E.contact },
      { f: s3 + 20, v: { x: 120, y: 520, s: 0.82, o: DIM }, dur: 20 },
      { f: CUE.brk, v: { x: 110, y: 600, s: 0.86, o: DIM }, e: E.smooth, dur: 40 },
      { f: CUE.settle + 10, v: Q_HOME.q2Wait, e: E.rest, dur: CUE.settle + 10 - BRK0 },
    ],
    2: [
      { f: QUESTIONS[2].cue, v: { x: 110, y: 960, s: 1.34, o: 0 } },
      { f: s3, v: { x: 110, y: 1010, s: 1, o: 1 }, e: E.contact },
      { f: CUE.brk, v: { x: 116, y: 960, s: 0.94, o: 1 }, e: E.smooth, dur: 40 },
      { f: CUE.settle + 10, v: Q_HOME.q3Wait, e: E.rest, dur: CUE.settle + 10 - BRK0 },
    ],
  };
  const p = track(f, keys[i]);
  // The storm: from CUE.storm the questions interrupt each other on 8ths, then 16ths; the one that
  // speaks is sharp and forward, the others drop back. It ends on Q1 a beat before the break.
  if (f >= CUE.storm - 14 && f < BRK0 + 4) {
    const focus = stormFocus(f);
    const mine = focus[i];
    const on = prog(f, CUE.storm - 14, CUE.storm + 2, E.smooth) * (1 - prog(f, BRK0, BRK0 + 4, E.out)); // the storm takes over smoothly, no pop
    p.o = mix(p.o, mix(DIM, 1, mine), on);
    p.s *= 1 + 0.05 * mine;
  }
  return p;
};

/** Frames after CUE.storm where the storm switches speaker: 8ths, then 16ths, accelerating. */
export const STORM_T = [0, 15, 30, 38, 45, 49, 53, 56, 58, 60];

/** The storm's switch frames and who speaks: 8ths, then 16ths, ending on Q1. */
export const STORM = (() => {
  const out: { f: number; q: number }[] = [];
  const seq = [0, 1, 2, 0, 1, 2, 0, 1, 2, 0];
  const t = STORM_T;
  t.forEach((d, j) => out.push({ f: CUE.storm + d, q: seq[j] }));
  return out;
})();

const stormFocus = (f: number) => {
  const w = [0, 0, 0];
  for (const s of STORM) {
    if (f < s.f) break;
    w.fill(0);
    const k = prog(f, s.f, s.f + 3, E.out);
    w[s.q] = k;
  }
  // after the last switch, Q1 holds the focus into the break
  return w;
};

/** The chaos camera: a slow creep in, a kick on every slam and storm switch; back to rest at the break. */
export const chaosCam = (f: number) => {
  const creep = mix(1, 1.08, prog(f, 0, CUE.brk, E.linear));
  const back = prog(f, BRK0, CUE.settle + 10, E.rest);
  let kick = 0;
  for (let i = 0; i < 3; i++) kick += hitPulse(f - slamOf(i), 1, 6) * (i % 2 ? -1 : 1);
  let skick = 0;
  for (const s of STORM) skick += hitPulse(f - s.f, 1, 4) * 0.4 * (s.q - 1);
  const frozen = f >= CUE.brk && f < BRK0;
  return { k: mix(creep, 1, back), ox: (kick * 9 + skick * 7) * (frozen ? 0 : 1), oy: (kick * 5) * (frozen ? 0 : 1) };
};

/** Question block pose in screen px (camera applied). */
export const qScreen = (i: number, f: number) => {
  const p = qPose(i, f);
  const c = chaosCam(f);
  const pf = f >= CUE.brk && f < BRK0 ? qPose(i, CUE.brk) : p; // the freeze holds the pose
  return { x: 540 + (pf.x - 540) * c.k + c.ox, y: 960 + (pf.y - 960) * c.k + c.oy, s: pf.s * c.k, o: pf.o };
};

// ---------- the live overlay card (overlay/styles.css at 404 px, scaled) ----------
export const LC = { x: 67, y: 740, S: 2.5, w: 356 }; // the overlay at a narrower window, scaled for a phone
export const LC_IN = { pad: 12, padX: 16, border: 1 };
export const lcLayout = () => {
  const content = LC.w - 2 * (LC_IN.padX + LC_IN.border);
  const action = wrap(LIVE.action, content, 16, 600);
  const reason = wrap(LIVE.reason, content, 13, 400);
  const rowTop = LC_IN.border + LC_IN.pad;
  const actionTop = rowTop + 15 + 4;
  const reasonTop = actionTop + action.length * 21.6 + 4;
  const h = reasonTop + reason.length * 18.2 + LC_IN.pad + LC_IN.border;
  const x0 = LC_IN.border + LC_IN.padX;
  return {
    action,
    reason,
    rowTop,
    actionTop,
    reasonTop,
    h,
    x0,
    dot: { x: x0 + 3, y: rowTop + 7.5, r: 3 },
    word: { x: x0, top: actionTop, base: actionTop + baselineOf(16, 600, 1.35) },
  };
};

/** The live card's camera: a slow push while it is read; it recedes before the review. */
export const lcPose = (f: number) => {
  const push = 1 + 0.08 * prog(f, CUE.dotLand + 20, CUE.away, E.dolly);
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
