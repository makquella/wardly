// Act 2: «купити» becomes «Купіть», the first word of the real overlay card, and the card grows
// around it; the «?» dot lands as the card's status dot. The card is overlay/styles.css, scaled.
import React from 'react';
import { C, FONT, TYPE } from '../brand/tokens';
import { LIVE } from '../data';
import { E, mix, prog } from '../lib/anim';
import { baselineOf, measureTracked } from '../lib/measure';
import { arc, mixColor } from '../lib/track';
import { CUE } from '../timeline';
import { cardToScreen, LC, lcLayout, lcPose, qFont, qScreen, Q_KEY_TOP } from './layout';
import { HOOK, qDotScreen } from './Chaos';

const WORD = 'Купіть';
const centre = () => ({ x: LC.w / 2, y: lcLayout().h / 2 });

/** Where the card's first word sits on screen at frame f (its baseline-left point and its px size). */
const cardWord = (f: number) => {
  const L = lcLayout();
  const pose = lcPose(f);
  const p = cardToScreen(LC, centre(), pose.k, pose.dy, { x: L.word.x, y: L.word.base });
  return { ...p, size: 16 * LC.S * pose.k };
};

/** Where the hero word sits on screen (baseline-left, px size), from question 1's pose. */
const heroWord = (f: number) => {
  const p = qScreen(0, f);
  const base = Q_KEY_TOP + baselineOf(qFont.size, qFont.weight, TYPE.question.lead, qFont.family);
  return { x: p.x, y: p.y + base * p.s, size: qFont.size * p.s };
};

const SHRINK_END = CUE.dotLand - 6;

/** The word in flight: hero size and weight → the card's 16 px / 600, anchored on its baseline. */
export const MorphWord: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.shrink || f >= SHRINK_END) return null;
  const t = prog(f, CUE.shrink, SHRINK_END, E.inOut);
  const a = heroWord(CUE.shrink);
  const b = cardWord(f);
  const size = Math.exp(mix(Math.log(a.size), Math.log(b.size), t));
  const weight = mix(qFont.weight, 600, t);
  const track = mix(qFont.track, 0, t);
  const x = mix(a.x, b.x, t);
  const y = mix(a.y, b.y, t);
  const fs = 150; // drawn at a fixed size and scaled, so the glyphs never re-hint mid-move
  const base = baselineOf(fs, Math.round(weight), 1, FONT.text);
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        transform: `translate(${x}px, ${y}px) scale(${size / fs}) translate(0px, ${-base}px)`,
        transformOrigin: '0 0',
        fontFamily: FONT.text,
        fontSize: fs,
        fontWeight: weight,
        letterSpacing: `${track}em`,
        lineHeight: 1,
        whiteSpace: 'pre',
        color: mixColor(C.text, C.text, t),
      }}
    >
      {WORD}
    </div>
  );
};

/** Q1's dot: from the «?» (white) to the card's status dot (amber), on an arc. */
export const LiveDot: React.FC<{ frame: number }> = ({ frame: f }) => {
  const h1 = HOOK[0][1];
  if (f < h1 || f >= CUE.dotLand) return null;
  const L = lcLayout();
  const pose = lcPose(f);
  const a = qDotScreen(0, h1);
  // first it slides in to become the full stop of «Купіть.» (the question is now a statement) ...
  const hero = qScreen(0, CUE.shrink);
  const stop = { x: hero.x + (measureTracked(WORD, qFont.size, qFont.weight, qFont.track, qFont.family) + qFont.size * 0.02) * hero.s + a.r, y: a.y, r: a.r };
  const bp = cardToScreen(LC, centre(), pose.k, pose.dy, L.dot);
  const t1 = prog(f, h1 + 4, CUE.roll + 22, E.inOut);
  // ... then, as the word shrinks into the card, it drops into the card's status dot
  const t = prog(f, CUE.shrink + 4, CUE.dotLand, E.inOut);
  const from = { x: mix(a.x, stop.x, t1), y: a.y };
  const p = arc(from, bp, t, 0.22);
  const r = Math.exp(mix(Math.log(a.r), Math.log(L.dot.r * LC.S * pose.k), t));
  const col = mixColor(C.text, C.warn, prog(f, CUE.dotLand - 14, CUE.dotLand, E.smooth));
  return <div style={{ position: 'absolute', left: 0, top: 0, width: r * 2, height: r * 2, borderRadius: '50%', background: col, transform: `translate(${p.x - r}px, ${p.y - r}px)` }} />;
};

/** The real overlay card («Порада», medium priority), laid out at 404 px and scaled. */
export const LiveCard: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.shrink || f > CUE.away + 40) return null;
  const L = lcLayout();
  const pose = lcPose(f);
  const c = centre();
  // the container grows from around the word to the whole card
  const g = prog(f, CUE.shrink + 20, CUE.dotLand + 6, E.out); // only once the word is close to its slot
  const wordW = measureTracked(WORD, 16, 600, 0);
  const from = { t: L.word.top - 5, l: L.word.x - 8, r: LC.w - (L.word.x + wordW + 8), b: L.h - (L.word.top + 21.6 + 5) };
  const clip = `inset(${mix(from.t, 0, g)}px ${mix(from.r, 0, g)}px ${mix(from.b, 0, g)}px ${mix(from.l, 0, g)}px round ${mix(8, 12, g)}px)`;
  const wordsIn = (i: number) => prog(f, CUE.dotLand - 8 + i * 1.5, CUE.dotLand + 10 + i * 1.5, E.out);
  const handed = f >= SHRINK_END; // the card's own «Купіть» takes over from the flying word
  let n = 0;
  const tx = c.x * LC.S - c.x * LC.S * pose.k;
  const ty = c.y * LC.S - c.y * LC.S * pose.k + pose.dy;
  return (
    <div
      data-ui
      style={{
        position: 'absolute',
        left: LC.x,
        top: LC.y,
        width: LC.w,
        height: L.h,
        transformOrigin: '0 0',
        transform: `translate(${tx}px, ${ty}px) scale(${LC.S * pose.k})`,
        opacity: pose.o * prog(f, CUE.shrink + 14, CUE.shrink + 26, E.smooth),
        clipPath: clip,
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          background: C.overlayBg,
          boxShadow: `inset 3px 0 0 ${C.warn}, 0 20px 60px rgba(0, 0, 0, 0.35)`,
        }}
      />
      {/* top row: the status dot and «Порада» */}
      <div style={{ position: 'absolute', left: L.dot.x - 3, top: L.dot.y - 3, width: 6, height: 6, borderRadius: '50%', background: C.warn, opacity: f >= CUE.dotLand ? 1 : 0 }} />
      <div
        style={{
          position: 'absolute',
          left: L.x0 + 6 + 8,
          top: L.rowTop,
          height: 15,
          lineHeight: '15px',
          fontFamily: FONT.text,
          fontSize: 12,
          fontWeight: 500,
          color: C.text2,
          opacity: prog(f, CUE.dotLand - 4, CUE.dotLand + 12, E.out),
        }}
      >
        {LIVE.label}
      </div>
      {L.action.map((line, li) => (
        <div
          key={li}
          style={{ position: 'absolute', left: L.x0, top: L.actionTop + li * 21.6, height: 21.6, lineHeight: '21.6px', fontFamily: FONT.text, fontSize: 16, fontWeight: 600, color: C.text, whiteSpace: 'pre' }}
        >
          {line.split(' ').map((w, wi) => {
            const first = li === 0 && wi === 0;
            const k = first ? (handed ? 1 : 0) : wordsIn(n++);
            return (
              <span key={wi} style={{ opacity: k, display: 'inline-block', transform: `translateY(${(1 - k) * 4}px)` }}>
                {w}
                {wi < line.split(' ').length - 1 ? ' ' : ''}
              </span>
            );
          })}
        </div>
      ))}
      {L.reason.map((line, li) => {
        const k = prog(f, CUE.dotLand + 14 + li * 4, CUE.dotLand + 34 + li * 4, E.out);
        return (
          <div
            key={li}
            style={{ position: 'absolute', left: L.x0, top: L.reasonTop + li * 18.2, height: 18.2, lineHeight: '18.2px', fontFamily: FONT.text, fontSize: 13, fontWeight: 400, color: C.text2, whiteSpace: 'pre', opacity: k, transform: `translateY(${(1 - k) * 3}px)` }}
          >
            {line}
          </div>
        );
      })}
    </div>
  );
};
