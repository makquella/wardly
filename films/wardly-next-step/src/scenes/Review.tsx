// Act 3: «Чому відстаю?» and «Що змінити?» come forward from the edges where they waited and are
// answered by the real review card («Головне на наступну гру»): Q2's dot becomes the finding's
// index, Q3's dot drops beside the drill and turns red — the next step.
import React from 'react';
import { C, FONT } from '../brand/tokens';
import { REVIEW } from '../data';
import { E, mix, prog } from '../lib/anim';
import { arc, mixColor, track } from '../lib/track';
import { CUE } from '../timeline';
import { HOOK, qDotScreen, type QOverride } from './Chaos';
import { cardToScreen, Q_HOME, qScreen, RC, rcCam, rcLayout } from './layout';

const LUCIDE = {
  target: (
    <>
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </>
  ),
  lightbulb: (
    <>
      <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
      <path d="M9 18h6" />
      <path d="M10 22h4" />
    </>
  ),
};
const Icon: React.FC<{ name: keyof typeof LUCIDE; x: number; y: number; color: string }> = ({ name, x, y, color }) => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" style={{ position: 'absolute', left: x, top: y }}>
    {LUCIDE[name]}
  </svg>
);

const centre = () => ({ x: RC.w / 2, y: rcLayout().hNoDrill / 2 });
export const reviewToScreen = (f: number, p: { x: number; y: number }) => {
  const cam = rcCam(f);
  return cardToScreen(RC, centre(), cam.k, cam.dy, p);
};

/** The drill box opening (0..1). */
const drillOpen = (f: number) => prog(f, CUE.drill + 4, CUE.drill + 40, E.out);

/** Act-3 poses for the waiting questions (null: their act-1/2 pose still holds). */
export const qOverride = (i: number, f: number): QOverride => {
  if (i === 1) {
    if (f < CUE.q2Come) return null;
    const p = track(f, [
      { f: CUE.q2Come, v: { ...Q_HOME.q2Wait } },
      { f: CUE.q2Come + 40, v: { x: 112, y: 440, s: 0.6, o: 1 }, e: E.cam },
      { f: CUE.title + 26, v: { x: 112, y: 440, s: 0.6, o: 0.42 }, e: E.smooth, dur: 24 },
      { f: CUE.drill + 30, v: { x: 112, y: 420, s: 0.6, o: 0 }, e: E.exit, dur: 24 },
    ]);
    return p;
  }
  if (i === 2) {
    if (f < CUE.q3Come - 30) return null;
    const L = rcLayout();
    const under = reviewToScreen(CUE.q3Come - 4, { x: 0, y: L.hNoDrill });
    const p = track(f, [
      { f: CUE.q3Come - 30, v: { ...Q_HOME.q3Wait } },
      { f: CUE.q3Come - 4, v: { x: 112, y: under.y + 44, s: 0.55, o: 1 }, e: E.cam },
      { f: CUE.drill + 26, v: { x: 112, y: under.y + 70, s: 0.55, o: 0 }, e: E.exit, dur: 20 },
    ]);
    return p;
  }
  return null;
};

/** Q2's dot: from the «?» to the index circle, where it grows into the «1». */
const IndexDot: React.FC<{ frame: number }> = ({ frame: f }) => {
  const h1 = HOOK[1][1];
  if (f < h1 || f >= CUE.index + 2) return null;
  const L = rcLayout();
  const a = qDotScreen(1, h1, qOverride(1, h1));
  const cam = rcCam(f);
  const b = reviewToScreen(f, L.index);
  const t = prog(f, h1 + 2, CUE.index, E.inOut);
  const p = arc(a, b, t, 0.2);
  const r = Math.exp(mix(Math.log(a.r), Math.log(L.index.r * RC.S * cam.k), t));
  const col = mixColor(C.text, C.surface2, prog(f, CUE.index - 10, CUE.index, E.smooth));
  return <div style={{ position: 'absolute', left: 0, top: 0, width: r * 2, height: r * 2, borderRadius: '50%', background: col, transform: `translate(${p.x - r}px, ${p.y - r}px)` }} />;
};

export const ReviewCard: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.review - 12 || f > CUE.clear + 32) return null;
  const L = rcLayout();
  const cam = rcCam(f);
  const c = centre();
  const open = drillOpen(f);
  const grow = prog(f, CUE.index - 6, CUE.title + 20, E.out);
  const h = mix(mix(49 + 20, L.hNoDrill, grow), L.h, open);
  const tx = c.x * RC.S - c.x * RC.S * cam.k;
  const ty = c.y * RC.S - c.y * RC.S * cam.k + cam.dy;
  const fade = (a: number, d = 16) => prog(f, a, a + d, E.out);
  const head = fade(CUE.review - 6);
  const title = fade(CUE.title);
  const tag = fade(CUE.title + 6);
  const txt = (li: number) => fade(CUE.title + 10 + li * 4);
  const indexIn = f >= CUE.index ? 1 : 0;
  const text: React.CSSProperties = { position: 'absolute', fontFamily: FONT.text, whiteSpace: 'pre', fontVariantNumeric: 'tabular-nums' };
  return (
    <div data-ui style={{ position: 'absolute', left: RC.x, top: RC.y, width: RC.w, height: h, transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${RC.S * cam.k})`, opacity: cam.o }}>
      <div style={{ position: 'absolute', inset: 0, borderRadius: 12, border: `1px solid ${C.border}`, background: C.surface1, boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.035), 0 20px 60px rgba(0, 0, 0, 0.3)' }} />
      {/* card head: target icon + «Головне на наступну гру» */}
      <div style={{ opacity: head }}>
        <Icon name="target" x={21} y={31 - 8} color={C.text3} />
        <div style={{ ...text, left: 45, top: 31 - 10.15, height: 20.3, lineHeight: '20.3px', fontSize: 14, fontWeight: 600, letterSpacing: '-0.005em', color: C.text }}>{REVIEW.head}</div>
      </div>
      {/* the finding: index «1» */}
      <div style={{ position: 'absolute', left: L.index.x - 11, top: L.index.y - 11, width: 22, height: 22, borderRadius: '50%', background: C.surface2, opacity: indexIn, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: FONT.text, fontSize: 12, fontWeight: 600, color: C.text2 }}>
        <span style={{ opacity: prog(f, CUE.index, CUE.index + 10, E.out) }}>{REVIEW.index}</span>
      </div>
      {/* title + section tag */}
      <div style={{ ...text, left: L.bodyX, top: L.titleTop, height: 20.3, lineHeight: '20.3px', fontSize: 14, fontWeight: 600, color: C.text, opacity: title, transform: `translateY(${(1 - title) * 4}px)` }}>{REVIEW.title}</div>
      <div
        style={{
          ...text,
          left: L.tagWraps ? L.bodyX : L.bodyX + 8 + 0,
          top: L.tagWraps ? L.titleTop + 20.3 + 8 : L.titleTop - 0.5,
          padding: '1px 6px',
          border: `1px solid ${C.borderStrong}`,
          borderRadius: 6,
          fontSize: 12,
          lineHeight: '17.4px',
          fontWeight: 400,
          color: C.text3,
          opacity: tag,
          marginLeft: L.tagWraps ? 0 : tagOffset(),
        }}
      >
        {REVIEW.tag}
      </div>
      {L.text.map((line, li) => (
        <div key={li} style={{ ...text, left: L.bodyX, top: L.textTop + li * 18.85, height: 18.85, lineHeight: '18.85px', fontSize: 13, fontWeight: 400, color: C.text2, opacity: txt(li), transform: `translateY(${(1 - txt(li)) * 3}px)` }}>
          {line}
        </div>
      ))}
      {/* the drill: lightbulb, «Вправа:», the drill text; opens from its top */}
      <div style={{ position: 'absolute', left: L.bodyX, top: L.drillTop, width: L.bodyW, height: L.drillH, borderRadius: 8, background: C.surface2, clipPath: `inset(0 0 ${(1 - open) * 100}% 0 round 8px)`, opacity: open > 0 ? 1 : 0 }}>
        <Icon name="lightbulb" x={12} y={8 + 1} color={C.text3} />
        {L.drill.map((line, li) => {
          const k = prog(f, CUE.drill + 10 + li * 3, CUE.drill + 26 + li * 3, E.out);
          const label = `${REVIEW.drillLabel}:`;
          const isFirst = li === 0 && line.startsWith(label);
          return (
            <div key={li} style={{ ...text, left: 12 + 16 + 8, top: 8 + li * 18.85, height: 18.85, lineHeight: '18.85px', fontSize: 13, fontWeight: 400, color: C.text2, opacity: k }}>
              {isFirst ? (
                <>
                  <span style={{ color: C.text, fontWeight: 500 }}>{label}</span>
                  {line.slice(label.length)}
                </>
              ) : (
                line
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// the tag sits after the title on the same row (flex gap 8)
import { measureTracked } from '../lib/measure';
const tagOffset = () => measureTracked(REVIEW.title, 14, 600, 0);

export const ReviewScene: React.FC<{ frame: number }> = ({ frame }) => (
  <>
    <ReviewCard frame={frame} />
    <IndexDot frame={frame} />
  </>
);

export { qScreen };
