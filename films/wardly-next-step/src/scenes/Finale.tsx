// Act 4: everything clears to the one red dot. The slogan builds toward it (the dot is its full
// stop), then the dot flies to the logo's orbit while the orbit draws itself; «Wardly», the
// slogan and the address settle into the end card.
import React from 'react';
import { Img, staticFile } from 'remotion';
import { C, FONT, TYPE } from '../brand/tokens';
import { CTA } from '../data';
import { E, mix, prog } from '../lib/anim';
import { glyphDot } from '../lib/glyph';
import { baselineOf, fitSize, measureTracked } from '../lib/measure';
import { arc, mixColor } from '../lib/track';
import { copy, CUE, TOTAL } from '../timeline';
import { HOOK, qDotScreen } from './Questions';
import { RC, rcLayout } from './layout';
import { qOverride, reviewToScreen } from './Review';

const FAM = FONT.display;
const W8 = TYPE.display.weight;
const TRK = TYPE.display.track;

// ---------- slogan layouts: the statement (big, left) and the end card (small, centred) ----------
type WordBox = { text: string; x: number; top: number; size: number; line: number };
const LINES_BIG = [['Менше', 'хаосу.'], ['Чіткіший'], ['наступний', 'крок']]; // the period is the dot

const layoutWords = (lines: string[][], size: number, lead: number, top: number, align: 'left' | 'center', x0 = 112, withPeriod = true) => {
  const out: WordBox[] = [];
  const space = measureTracked('а а', size, W8, TRK, FAM) - 2 * measureTracked('а', size, W8, TRK, FAM);
  lines.forEach((words, li) => {
    const full = words.join(' ') + (li === lines.length - 1 && withPeriod ? '.' : '');
    const lw = measureTracked(full, size, W8, TRK, FAM);
    let x = align === 'left' ? x0 : 540 - lw / 2;
    words.forEach((w) => {
      out.push({ text: w, x, top: top + li * size * lead, size, line: li });
      x += measureTracked(w, size, W8, TRK, FAM) + space;
    });
  });
  return out;
};

export const sloganBig = () => {
  const size = Math.min(TYPE.display.size, fitSize('наступний крок.', 830, TYPE.display.size, W8, TRK, FAM));
  const lead = TYPE.display.lead;
  const top = 960 - (3 * size * lead) / 2 - 40;
  return { size, lead, top, words: layoutWords(LINES_BIG, size, lead, top, 'left') };
};
/** The end card: the statement block, scaled down as one piece and moved under the lockup. */
export const END = { slogan: { x: 112, top: 846, k: 0.74 }, mark: { cx: 112 + 115, cy: 655, size: 230 }, wordmarkTop: 655 - 62, freeTop: 1112, urlTop: 1170 };
// The statement breathes while it is read (a 2% push about its own block), so it never freezes.
const breathe = (f: number, B: { top: number; size: number }, p: { x: number; y: number }) => {
  const k = 1 + 0.02 * prog(f, CUE.slogan1, CUE.logo, E.linear);
  const o = { x: 112, y: B.top + B.size * 1.6 };
  return { x: o.x + (p.x - o.x) * k, y: o.y + (p.y - o.y) * k, k };
};
const toEnd = (B: { top: number }, p: { x: number; y: number }, t: number) => {
  const ex = END.slogan.x + (p.x - 112) * END.slogan.k;
  const ey = END.slogan.top + (p.y - B.top) * END.slogan.k;
  return { x: mix(p.x, ex, t), y: mix(p.y, ey, t), k: mix(1, END.slogan.k, t) };
};

/** The full stop after «крок» in a layout: where the red dot sits. */
const periodOf = (L: { size: number; lead: number; words: WordBox[] }) => {
  const last = L.words[L.words.length - 1];
  const d = glyphDot('.', L.size, W8, FAM);
  const x = last.x + measureTracked(last.text, L.size, W8, TRK, FAM) + L.size * 0.05; // clear of the «к»
  const base = last.top + baselineOf(L.size, W8, L.lead, FAM);
  return { x: x + d.cx, y: base + d.cy, r: d.r, penX: x, top: last.top };
};

// ---------- the logo ----------
const LOGO = END.mark;
const LOGO_DOT = { x: 100.7, y: 385.2, r: 32 }; // measured in site/assets/logo.png (512 px)
const logoDot = () => {
  const k = LOGO.size / 512;
  return { x: LOGO.cx - LOGO.size / 2 + LOGO_DOT.x * k, y: LOGO.cy - LOGO.size / 2 + LOGO_DOT.y * k, r: LOGO_DOT.r * k };
};
const DOT_ANGLE = 230;
void measureTracked; // the red dot's direction from the logo centre, CSS conic degrees

/** The end card's slow creep, applied to everything that belongs to it (the dot included). */
const creep = (f: number) => 1 + 0.03 * prog(f, CUE.wordmark + 10, TOTAL, E.dolly);
const CREEP_O = { x: 540, y: 860 };
const creepPt = (f: number, p: { x: number; y: number }) => {
  const k = creep(f);
  return { x: CREEP_O.x + (p.x - CREEP_O.x) * k, y: CREEP_O.y + (p.y - CREEP_O.y) * k };
};

// ---------- the red dot: Q3's «?» dot from the drill to the logo ----------
const DRILL_LAND = CUE.drill + 22;
const TO_PERIOD = [CUE.clear + 2, CUE.clear + 46] as const;
const TO_LOGO = [CUE.logo, CUE.logo + 40] as const;

export const redDotAt = (f: number) => {
  const L = rcLayout();
  const h1 = HOOK[2][1];
  const gutter = (g: number) => {
    const p = reviewToScreen(g, L.redDot);
    return { ...p, r: L.redDot.r * RC.S };
  };
  const B = sloganBig();
  const per0 = periodOf(B);
  const per = { ...per0, ...breathe(Math.min(f, TO_LOGO[0]), B, per0) };
  const ld = logoDot();
  if (f < DRILL_LAND) {
    const a = qDotScreen(2, qOverride(2, h1)!);
    const b = gutter(f);
    const t = prog(f, h1, DRILL_LAND, E.inOut);
    const p = arc(a, b, t, -0.25);
    return { ...p, r: Math.exp(mix(Math.log(a.r), Math.log(b.r), t)), col: mixColor(C.text, C.accentFill, prog(f, DRILL_LAND - 12, DRILL_LAND, E.smooth)) };
  }
  if (f < TO_PERIOD[0]) return { ...gutter(f), col: C.accentFill };
  if (f < TO_LOGO[0]) {
    const a = gutter(TO_PERIOD[0]);
    const t = prog(f, TO_PERIOD[0], TO_PERIOD[1], E.inOut);
    const p = arc(a, per, t, 0.12);
    // it waits at the end of the empty line, big: the hero of the frame; on «крок» it shrinks into the full stop
    const big = Math.exp(mix(Math.log(a.r), Math.log(17), t));
    const r = Math.exp(mix(Math.log(big), Math.log(per.r * 1.15), prog(f, CUE.period - 16, CUE.period, E.inOut)));
    return { ...p, r, col: C.accentFill };
  }
  const t = prog(f, TO_LOGO[0], TO_LOGO[1], E.inOut);
  const p = arc({ x: per.x, y: per.y }, ld, t, 0.25); // over the top, never across the slogan
  const q = creepPt(f, p);
  return { ...q, r: Math.exp(mix(Math.log(per.r * 1.15), Math.log(ld.r), t)) * creep(f), col: mixColor(C.accentFill, C.logoDot, t) };
};

export const RedDot: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < HOOK[2][1]) return null;
  const d = redDotAt(f);
  return <div style={{ position: 'absolute', left: 0, top: 0, width: d.r * 2, height: d.r * 2, borderRadius: '50%', background: d.col, transform: `translate(${d.x - d.r}px, ${d.y - d.r}px)` }} />;
};

// ---------- the slogan ----------
const FLIP = [CUE.logo - 6, CUE.logo + 34] as const;

const Slogan: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.slogan1) return null;
  const B = sloganBig();
  const t = prog(f, FLIP[0], FLIP[1], E.inOut);
  const frag2 = copy('slogan.2');
  const k = creep(f);
  const pB = periodOf(B);
  return (
    <>
      {B.words.map((w, i) => {
        const start = i < 2 ? CUE.slogan1 + i * 6 : frag2.in + (i - 2) * 6;
        const p = prog(f, start, start + 26, E.out);
        const br = breathe(f, B, { x: w.x, y: w.top });
        const e = toEnd(B, br, t);
        e.k *= mix(br.k, 1, t);
        const c = creepPt(f, e);
        const rise = (1 - p) * 0.32 * w.size;
        return (
          <div
            key={i}
            data-text={i < 2 ? 'slogan.1' : 'slogan.2'}
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              transform: `translate(${c.x}px, ${c.y + rise * e.k}px) scale(${e.k * k})`,
              transformOrigin: '0 0',
              fontFamily: FAM,
              fontSize: w.size,
              fontWeight: W8,
              letterSpacing: `${TRK}em`,
              lineHeight: B.lead,
              whiteSpace: 'pre',
              color: i >= 2 && f < frag2.resolved + 40 ? mixColor(C.accent, C.text, prog(f, start + 12, start + 40, E.smooth)) : C.text,
              opacity: p,
            }}
          >
            {w.text}
          </div>
        );
      })}
      {/* the white full stop the red dot leaves behind on the end card */}
      {(() => {
        const o = prog(f, TO_LOGO[0] + 4, TO_LOGO[0] + 20, E.smooth);
        if (o <= 0) return null;
        const e = toEnd(B, { x: pB.penX, y: pB.top }, t);
        const c = creepPt(f, e);
        return (
          <div style={{ position: 'absolute', left: 0, top: 0, transform: `translate(${c.x}px, ${c.y}px) scale(${e.k * k})`, transformOrigin: '0 0', fontFamily: FAM, fontSize: B.size, fontWeight: W8, letterSpacing: `${TRK}em`, lineHeight: B.lead, color: C.text, opacity: o }}>
            .
          </div>
        );
      })()}
    </>
  );
};

// ---------- logo, wordmark, address ----------
const Logo: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.logo) return null;
  const sweep = prog(f, CUE.logo + 6, CUE.logo + 46, E.inOut) * 360;
  const eye = prog(f, CUE.logo + 14, CUE.logo + 44, E.out);
  const k = creep(f);
  const c = creepPt(f, { x: LOGO.cx, y: LOGO.cy });
  const s = LOGO.size;
  // a fixed-size image moved and scaled by one transform: resizing the element itself would
  // re-pick the image's resampling every few frames (a one-frame shimmer on the ring)
  const box: React.CSSProperties = { position: 'absolute', left: 0, top: 0, width: s, height: s, transformOrigin: '50% 50%', translate: `${c.x - s / 2}px ${c.y - s / 2}px`, scale: `${k}` };
  const ring = `conic-gradient(from ${DOT_ANGLE}deg, #000 ${sweep}deg, transparent ${sweep}deg), radial-gradient(circle closest-side, transparent 60%, #000 60.5%)`;
  return (
    <>
      {/* the orbit draws itself clockwise from the dot */}
      <Img src={staticFile('img/logo.png')} style={{ ...box, WebkitMaskImage: ring, WebkitMaskComposite: 'source-in', maskComposite: 'intersect' }} />
      {/* the eye opens in the centre */}
      <Img
        src={staticFile('img/logo.png')}
        style={{ ...box, WebkitMaskImage: 'radial-gradient(circle closest-side, #000 60%, transparent 60.5%)', opacity: eye, scale: `${k * mix(0.7, 1, eye)}` }}
      />
    </>
  );
};

const Wordmark: React.FC<{ frame: number }> = ({ frame: f }) => {
  const c = copy('wordmark');
  if (f < c.in) return null;
  const p = prog(f, c.in, c.resolved, E.out);
  const size = TYPE.wordmark.size;
  const pt = creepPt(f, { x: END.mark.cx + END.mark.size / 2 + 34, y: END.wordmarkTop });
  return (
    <div
      data-text="wordmark"
      style={{ position: 'absolute', left: 0, top: 0, transform: `translate(${pt.x}px, ${pt.y + (1 - p) * 26}px) scale(${creep(f)})`, transformOrigin: '0 0', fontFamily: FAM, fontSize: size, fontWeight: TYPE.wordmark.weight, letterSpacing: `${TYPE.wordmark.track}em`, lineHeight: 1, color: C.text, opacity: p }}
    >
      Wardly
    </div>
  );
};

const Address: React.FC<{ frame: number }> = ({ frame: f }) => {
  const a = copy('free');
  const b = copy('url');
  if (f < a.in) return null;
  const pa = prog(f, a.in, a.resolved, E.out);
  const pb = prog(f, b.in, b.resolved, E.out);
  const A = creepPt(f, { x: END.slogan.x, y: END.freeTop });
  const Bp = creepPt(f, { x: END.slogan.x, y: END.urlTop });
  const k = creep(f);
  const st = (role: 'secondary' | 'url'): React.CSSProperties => ({ position: 'absolute', left: 0, top: 0, transformOrigin: '0 0', fontFamily: FONT.text, fontSize: TYPE[role].size, fontWeight: TYPE[role].weight, letterSpacing: `${TYPE[role].track}em`, lineHeight: TYPE[role].lead, whiteSpace: 'pre' });
  return (
    <>
      <div data-text="free" style={{ ...st('secondary'), color: C.text2, opacity: pa, transform: `translate(${A.x}px, ${A.y + (1 - pa) * 14}px) scale(${k})` }}>
        {CTA.free}
      </div>
      <div data-text="url" data-ui style={{ ...st('url'), color: C.text, opacity: pb, transform: `translate(${Bp.x}px, ${Bp.y + (1 - pb) * 14}px) scale(${k})` }}>
        {CTA.url}
      </div>
    </>
  );
};

export const Finale: React.FC<{ frame: number }> = ({ frame }) => (
  <>
    <Logo frame={frame} />
    <Wordmark frame={frame} />
    <Slogan frame={frame} />
    <Address frame={frame} />
    <RedDot frame={frame} />
  </>
);

export { rcLayout };
