// Act 1 (and the break): the app's own numbers in depth, three questions colliding over them.
import React from 'react';
import { C, FONT, TYPE } from '../brand/tokens';
import { NOISE } from '../data';
import { clamp, E, mix, prog, rand } from '../lib/anim';
import { glyphDot } from '../lib/glyph';
import { measureTracked } from '../lib/measure';
import { CUE } from '../timeline';
import { STORM_T, chaosCam, qDotLocal, qFont, qScreen, Q_KEY_TOP, Q_LEAD, QUESTIONS } from './layout';

// ---------- noise: real strings at three depths, arriving faster as the storm builds ----------
type Frag = { text: string; x: number; y: number; z: number; at: number; vx: number; vy: number };
const FRAGS: Frag[] = NOISE.map((text, i) => {
  let n = 0;
  const r = () => rand(`frag${i}.${n++}`);
  const z = 0.35 + r() * 0.9; // depth: 0.35 far .. 1.25 near
  const lane = i % 6; // spread over the height, avoiding a uniform grid
  return {
    text,
    x: 40 + r() * 760,
    y: 230 + lane * 250 + r() * 160,
    z,
    // frame 0 already shows six; the rest arrive on 16ths, denser toward the storm
    at: i < 6 ? 0 : Math.round(((i - 5) / (NOISE.length - 5)) ** 0.8 * (CUE.brk - 40) / 7.5) * 7.5,
    vx: (r() - 0.5) * 0.9,
    vy: -0.25 - r() * 0.45,
  };
});

// Near the lens: four huge, soft numbers that cross the frame faster (parallax), so the chaos has depth.
const GIANTS = [
  { text: '−210', x: 560, y: 260, size: 300, vx: -1.6, vy: 0.4, at: 0 },
  { text: '38:00', x: -120, y: 1330, size: 260, vx: 1.4, vy: -0.6, at: 0 },
  { text: '1800', x: 620, y: 1480, size: 280, vx: -1.2, vy: -0.9, at: 96 },
  { text: '4:00', x: -60, y: 120, size: 240, vx: 1.8, vy: 0.5, at: 150 },
];
// The storm: real strings flash in at new places on every interruption and die in a few frames.
const FLASH = Array.from({ length: 10 }, (_, j) => {
  let n = 0;
  const r = () => rand(`flash${j}.${n++}`);
  return { text: NOISE[(j * 7 + 3) % NOISE.length], x: 60 + r() * 700, y: 300 + r() * 1200, size: 40 + r() * 46, j };
});

export const Noise: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f > CUE.settle + 20) return null;
  const cam = chaosCam(f);
  const fall = prog(f, CUE.brk + 6, CUE.settle + 6, E.out); // the break: everything falls into depth
  const ff = f >= CUE.brk && f < CUE.brk + 6 ? CUE.brk : f; // the freeze
  const storm = prog(ff, CUE.storm, CUE.brk, E.linear);
  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      {GIANTS.map((g, i) => {
        if (ff < g.at) return null;
        const p = g.at === 0 ? 1 : prog(ff, g.at, g.at + 10, E.out);
        const t = ff - g.at;
        const x = g.x + g.vx * t * (1 + storm * 1.5);
        const y = g.y + g.vy * t * (1 + storm * 1.5);
        return (
          <div key={`g${i}`} data-ui style={{ position: 'absolute', left: 0, top: 0, transform: `translate(${540 + (x - 540) * cam.k * mix(1, 1.6, fall)}px, ${960 + (y - 960) * cam.k * mix(1, 1.6, fall)}px)`, fontFamily: FONT.text, fontSize: g.size, fontWeight: 700, color: C.text3, opacity: 0.16 * p * (1 - fall), whiteSpace: 'pre', filter: 'blur(9px)', fontVariantNumeric: 'tabular-nums' }}>
            {g.text}
          </div>
        );
      })}
      {FLASH.map((g) => {
        const at = (STORM_T[g.j] ?? 999) + CUE.storm;
        const life = prog(ff, at, at + 2, E.out) * (1 - prog(ff, at + 6, at + 16, E.smooth));
        if (life <= 0 || ff >= CUE.brk) return null;
        return (
          <div key={`f${g.j}`} data-ui style={{ position: 'absolute', left: 0, top: 0, transform: `translate(${g.x}px, ${g.y}px)`, fontFamily: FONT.text, fontSize: g.size, fontWeight: 600, color: C.text2, opacity: 0.55 * life, whiteSpace: 'pre', fontVariantNumeric: 'tabular-nums' }}>
            {g.text}
          </div>
        );
      })}
      {FRAGS.map((g, i) => {
        if (ff < g.at) return null;
        const p = g.at === 0 ? 1 : prog(ff, g.at, g.at + 6, E.smooth); // frame 0 is already composed; later ones ease in, no pop
        const t = ff - g.at;
        const size = 28 + 40 * g.z;
        const depthK = mix(1, 0.72, fall);
        const x0 = g.x + g.vx * t * (1 + storm);
        const y0 = g.y + g.vy * t * (1 + storm);
        const x = 540 + (x0 - 540) * cam.k * depthK + cam.ox * g.z;
        const y = 960 + (y0 - 960) * cam.k * depthK + cam.oy * g.z;
        const o = (0.22 + 0.4 * clamp(g.z - 0.35)) * p * (1 - fall);
        return (
          <div
            key={i}
            data-ui
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              transform: `translate(${x}px, ${y}px) scale(${mix(1.12, 1, p) * depthK})`,
              transformOrigin: '0 0',
              fontFamily: FONT.text,
              fontSize: size,
              fontWeight: 500,
              color: g.z > 0.9 ? C.text2 : C.text3,
              opacity: o,
              whiteSpace: 'pre',
              fontVariantNumeric: 'tabular-nums',
              filter: g.z < 0.6 ? `blur(${((0.6 - g.z) * 6).toFixed(2)}px)` : undefined,
            }}
          >
            {g.text}
          </div>
        );
      })}
    </div>
  );
};

// ---------- a question block ----------
const OLD = 'купити';
const NEW = 'Купіть';

/** «купити» → «Купіть»: the changed letters roll up through a one-line window, staggered. */
const Roll: React.FC<{ frame: number }> = ({ frame: f }) => {
  const size = qFont.size;
  return (
    <>
      {/* lint-ok: hero word */}
      {OLD.split('').map((a, i) => {
        const b = NEW[i];
        if (a === b) return <span key={i}>{a}</span>;
        const order = [0, 3, 5].indexOf(i);
        const p = prog(f, CUE.roll + order * 3, CUE.roll + order * 3 + 10, E.inOut);
        const wa = measureTracked(a, size, qFont.weight, qFont.track, qFont.family);
        const wb = measureTracked(b, size, qFont.weight, qFont.track, qFont.family);
        // the old letter rises and fades out, the new one rises in from below: never two half-letters at full strength
        return (
          <span key={i} style={{ display: 'inline-block', position: 'relative', width: mix(wa, wb, p), height: '1em', overflow: 'hidden', verticalAlign: 'top' }}>
            <span style={{ position: 'absolute', left: 0, top: 0, lineHeight: 1, transform: `translateY(${-p * 0.5}em)`, opacity: clamp(1.15 - 1.3 * p) }}>{a}</span>
            <span style={{ position: 'absolute', left: 0, top: 0, lineHeight: 1, transform: `translateY(${(1 - p) * 0.5}em)`, opacity: clamp(1.3 * p - 0.15) }}>{b}</span>
          </span>
        );
      })}
    </>
  );
};

/** Frames over which question i's «?» loses its hook (null: it keeps it). */
export const HOOK: Record<number, [number, number]> = {
  0: [CUE.hook, CUE.hook + 16],
  1: [CUE.index - 36, CUE.index - 22],
  2: [CUE.drill - 14, CUE.drill - 2],
};

export type QOverride = { x: number; y: number; s: number; o: number; leadO?: number; keyO?: number } | null;

export const Question: React.FC<{ i: number; frame: number; pose?: QOverride; hideKey?: boolean; rollFrame?: number }> = ({ i, frame: f, pose, hideKey, rollFrame }) => {
  const q = QUESTIONS[i];
  const p = pose ?? qScreen(i, f);
  if (p.o <= 0.001) return null;
  const [h0, h1] = HOOK[i];
  const d = qDotLocal(i);
  const hookP = prog(f, h0, h1, E.in);
  const clipTop = mix(0, d.dotTop - d.hookTop - 2, hookP);
  const dotGone = f >= h1; // from here the traveller dot carries it
  const keyStyle: React.CSSProperties = {
    fontFamily: qFont.family,
    fontSize: qFont.size,
    fontWeight: qFont.weight,
    letterSpacing: `${qFont.track}em`,
    lineHeight: TYPE.question.lead,
    whiteSpace: 'pre',
    color: C.text,
  };
  // Q1: «Що» slides out to the left as the hook goes
  const leadOut = i === 0 ? prog(f, CUE.hook - 4, CUE.hook + 18, E.exit) : 0;
  return (
    <div
      data-text={`q${i + 1}`}
      style={{ position: 'absolute', left: 0, top: 0, transform: `translate(${p.x}px, ${p.y}px) scale(${p.s})`, transformOrigin: '0 0', opacity: p.o, filter: p.o < 0.97 && f < CUE.brk + 6 ? `blur(${((1 - p.o) * 5).toFixed(2)}px)` : undefined }}
    >
      <div
        style={{
          fontFamily: FONT.text,
          fontSize: Q_LEAD,
          fontWeight: TYPE.lead.weight,
          letterSpacing: `${TYPE.lead.track}em`,
          lineHeight: TYPE.lead.lead,
          color: C.text2,
          whiteSpace: 'pre',
          opacity: (pose?.leadO ?? 1) * (1 - leadOut),
          transform: `translateX(${-140 * leadOut}px)`,
        }}
      >
        {q.lead}
      </div>
      <div style={{ ...keyStyle, position: 'absolute', left: 0, top: Q_KEY_TOP, opacity: pose?.keyO ?? 1 }}>
        {!hideKey && (i === 0 && rollFrame !== undefined ? <Roll frame={rollFrame} /> : <span>{q.key}</span>)}
        {!hideKey && <span style={{ clipPath: `inset(${clipTop}px 0 0 0)`, opacity: dotGone ? 0 : 1 }}>?</span>}
      </div>
    </div>
  );
};

/** The «?» dot of question i at scale 1, as a circle (the traveller starts exactly here). */
export const qDotScreen = (i: number, f: number, pose?: QOverride) => {
  const p = pose ?? qScreen(i, f);
  const d = qDotLocal(i);
  return { x: p.x + d.x * p.s, y: p.y + d.y * p.s, r: d.r * p.s };
};

export const keyWidth = (text: string, weight = qFont.weight) => measureTracked(text, qFont.size, weight, qFont.track, qFont.family);
export { glyphDot };
