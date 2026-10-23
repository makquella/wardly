// Act 2: the chosen icon becomes the item icon of the real overlay card and the card opens around it.
// The card is the death screen (overlay/styles.css: .overlay-shell.plan.death-screen, its red stripe,
// the title as its label, the item row under the first line), laid out at 356 px and scaled.
import React from 'react';
import { Img, staticFile } from 'remotion';
import { C, FONT } from '../brand/tokens';
import { LIVE } from '../data';
import { E, lmix, mix, prog } from '../lib/anim';
import { CUE } from '../timeline';
import { cardIconAt, PICK_W } from './Dota';
import { LC, lcLayout, lcPose } from './layout';

/** The pull-back: 1 when the card is at rest; at the reveal its icon is exactly the candidate on screen. */
const zoomOf = (f: number) => lmix(PICK_W / (lcLayout().icon.w * LC.S), 1, prog(f, CUE.reveal, CUE.reveal + 64, E.cam));

export const LiveCard: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f < CUE.reveal || f > CUE.away + 40) return null;
  const L = lcLayout();
  const pose = lcPose(f);
  const z = zoomOf(f);
  const a = cardIconAt(); // the pull-back is anchored on the icon's top-left corner, which never moves
  const c = { x: LC.w / 2, y: L.h / 2 };
  // the resting transform (the push about the card's centre, then the recede), then the pull-back about the icon
  const k = LC.S * pose.k;
  const tx0 = LC.x + c.x * LC.S - c.x * k;
  const ty0 = LC.y + c.y * LC.S - c.y * k + pose.dy;
  const tx = a.x + (tx0 - a.x) * z;
  const ty = a.y + (ty0 - a.y) * z;
  // the card's surface spreads out of the icon's own box
  const g = prog(f, CUE.reveal + 2, CUE.reveal + 40, E.out);
  const m = 2;
  const from = { t: L.icon.y - m, l: L.icon.x - m, r: LC.w - (L.icon.x + L.icon.w + m), b: L.h - (L.icon.y + L.icon.h + m) };
  const clip = `inset(${mix(from.t, 0, g)}px ${mix(from.r, 0, g)}px ${mix(from.b, 0, g)}px ${mix(from.l, 0, g)}px round ${mix(3, 12, g)}px)`;
  const titleIn = prog(f, CUE.reveal + 18, CUE.reveal + 34, E.out);
  const wordsIn = (i: number) => prog(f, CUE.reveal + 24 + i * 2, CUE.reveal + 40 + i * 2, E.out);
  let n = 0;
  return (
    <div
      data-ui
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: LC.w,
        height: L.h,
        transformOrigin: '0 0',
        transform: `translate(${tx}px, ${ty}px) scale(${k * z})`,
        opacity: pose.o,
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
          boxShadow: `inset 3px 0 0 ${C.error}, 0 20px 60px rgba(0, 0, 0, 0.35)`,
        }}
      />
      {/* top row: the idle dot and the title («Відродження через 23 с») */}
      <div style={{ position: 'absolute', left: L.dot.x - 3, top: L.dot.y - 3, width: 6, height: 6, borderRadius: '50%', background: C.idle, opacity: titleIn }} />
      <div
        style={{ position: 'absolute', left: L.x0 + 6 + 8, top: L.rowTop, height: 15, lineHeight: '15px', fontFamily: FONT.text, fontSize: 12, fontWeight: 500, color: C.text2, opacity: titleIn, transform: `translateX(${(1 - titleIn) * -6}px)` }}
      >
        {LIVE.label}
      </div>
      {L.action.map((line, li) => (
        <div
          key={li}
          style={{ position: 'absolute', left: L.x0, top: L.actionTop + li * 18.9, height: 18.9, lineHeight: '18.9px', fontFamily: FONT.text, fontSize: 14, fontWeight: 600, color: C.text, whiteSpace: 'pre' }}
        >
          {line.split(' ').map((w, wi, all) => {
            const kk = wordsIn(n++);
            return (
              <span key={wi} style={{ opacity: kk, display: 'inline-block', transform: `translateY(${(1 - kk) * 4}px)` }}>
                {w}
                {wi < all.length - 1 ? ' ' : ''}
              </span>
            );
          })}
        </div>
      ))}
      {/* the item row: the icon the viewer followed from the inventory */}
      <Img src={staticFile(`img/dota/items/${LIVE.item.key}.png`)} style={{ position: 'absolute', left: L.icon.x, top: L.icon.y, width: L.icon.w, height: L.icon.h, borderRadius: 3 }} />
      {L.reason.map((line, li) => {
        const kk = prog(f, CUE.why + li * 6, CUE.why + 24 + li * 6, E.out);
        return (
          <div
            key={li}
            style={{ position: 'absolute', left: L.x0, top: L.reasonTop + li * 18.2, height: 18.2, lineHeight: '18.2px', fontFamily: FONT.text, fontSize: 13, fontWeight: 400, color: C.text2, whiteSpace: 'pre', opacity: kk, transform: `translateY(${(1 - kk) * 3}px)` }}
          >
            {line}
          </div>
        );
      })}
    </div>
  );
};
