// Act 1: Dota, a choice, the answer. Juggernaut (Valve's own render) arrives and stops dead on the
// hit; the camera runs along his blade, and the blade's shape opens onto his inventory, where the
// real item icons click into the real slot layout one by one. «ЩО КУПИТИ?»: Butterfly or Black King
// Bar rise out of the empty slot and take the focus in turn; Black King Bar stays, everything else
// leaves, and after a pause the real overlay card opens around that icon (scenes/Live.tsx).
import React from 'react';
import { Img, staticFile } from 'remotion';
import { C, FONT } from '../brand/tokens';
import { DOTA } from '../data';
import { clamp, E, hitPulse, lmix, mix, prog } from '../lib/anim';
import { measureTracked } from '../lib/measure';
import { track } from '../lib/track';
import { CUE } from '../timeline';
import { LC, lcLayout } from './layout';

// ---------- Juggernaut ----------
// Source points in public/img/dota/juggernaut.webp (1160x1380, tools/fetch_dota.py CROP).
const HERO = { w: 1160, h: 1380, mask: { x: 712, y: 170 }, pommel: { x: 40, y: 445 }, tip: { x: 915, y: 100 } };
const AX = (() => {
  const dx = HERO.tip.x - HERO.pommel.x;
  const dy = HERO.tip.y - HERO.pommel.y;
  const n = Math.hypot(dx, dy);
  return { x: dx / n, y: dy / n }; // along the blade, toward its tip (up and to the right)
})();
const deg = (r: number) => (r * 180) / Math.PI;

/** The hero's camera: mask position on screen, scale and roll. A straight, fast move that stops dead on the hit. */
export const heroCam = (f: number) => {
  const t = clamp(f / CUE.hit); // linear: already at speed on frame 0, no ease into the stop
  const shake = hitPulse(f - CUE.hit, 1, 4);
  const drift = 1 + 0.03 * prog(f, CUE.hit, CUE.slash, E.linear);
  const run = prog(f, CUE.slash, CUE.wipe + 8, E.exit); // along the blade, accelerating into the wipe
  const k = lmix(2.3, 1.6, t) * drift * (1 + 0.025 * shake) * lmix(1, 1.3, run);
  const d = 640 * run;
  return {
    x: mix(860, 600, t) + 22 * shake - AX.x * d,
    y: mix(770, 650, t) - 14 * shake - AX.y * d,
    k,
    r: mix(-0.14, 0, t), // radians
  };
};
/** A source point of the render on screen at frame f. */
const heroPt = (f: number, p: { x: number; y: number }) => {
  const c = heroCam(f);
  const dx = (p.x - HERO.mask.x) * c.k;
  const dy = (p.y - HERO.mask.y) * c.k;
  return { x: c.x + dx * Math.cos(c.r) - dy * Math.sin(c.r), y: c.y + dx * Math.sin(c.r) + dy * Math.cos(c.r) };
};

const heroSrc = staticFile('img/dota/juggernaut.webp');
const HeroLayer: React.FC<{ f: number; style?: React.CSSProperties }> = ({ f, style }) => {
  const c = heroCam(f);
  return (
    <Img
      src={heroSrc}
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: HERO.w,
        height: HERO.h,
        transformOrigin: '0 0',
        transform: `translate(${c.x}px, ${c.y}px) rotate(${deg(c.r)}deg) scale(${c.k}) translate(${-HERO.mask.x}px, ${-HERO.mask.y}px)`,
        ...style,
      }}
    />
  );
};

/** Act 1a: the hero, lit from the upper right; a flash on the hit, a sweep over the mask, a glint running up the blade. */
const HeroShot: React.FC<{ f: number }> = ({ f }) => {
  if (f > CUE.wipe + 10) return null;
  const behind = prog(f, CUE.wipe - 2, CUE.wipe + 6, E.smooth); // the hero sinks into the dark as the cut opens
  const flash = hitPulse(f - CUE.hit, 1, 6);
  const sweep = prog(f, CUE.hit + 2, CUE.hit + 24, E.smooth); // a band of light across the mask
  const glint = prog(f, CUE.hit + 10, CUE.slash + 8, E.inOut); // runs from the guard to the tip: where the camera goes next
  const g = heroPt(f, { x: mix(330, HERO.tip.x, glint), y: mix(255, HERO.tip.y, glint) });
  const m = heroPt(f, HERO.mask);
  const c = heroCam(f);
  const bandAt = mix(-30, 130, sweep);
  return (
    <div style={{ position: 'absolute', inset: 0, opacity: 1 - 0.85 * behind }}>
      {/* the key light's spill behind the mask */}
      <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(circle 760px at ${m.x + 160}px ${m.y - 120}px, ${C.key}, transparent 70%)` }} />
      <HeroLayer f={f} style={{ filter: `brightness(${(0.62 + 0.45 * flash).toFixed(3)}) contrast(1.12) saturate(0.9)` }} />
      {/* key light: the same render, brighter, through a mask that falls off away from the upper right */}
      <HeroLayer
        f={f}
        style={{
          filter: 'brightness(1.55) contrast(1.12)',
          opacity: 0.95,
          WebkitMaskImage: `radial-gradient(circle ${(560 * c.k) / 1.6}px at ${HERO.mask.x + 120}px ${HERO.mask.y - 40}px, black 15%, transparent 75%)`,
          maskImage: `radial-gradient(circle ${(560 * c.k) / 1.6}px at ${HERO.mask.x + 120}px ${HERO.mask.y - 40}px, black 15%, transparent 75%)`,
        }}
      />
      {/* the sweep across the mask */}
      {sweep > 0 && sweep < 1 && (
        <HeroLayer
          f={f}
          style={{
            filter: 'brightness(2.4) saturate(0.6)',
            opacity: Math.sin(sweep * Math.PI) * 0.9,
            WebkitMaskImage: `linear-gradient(115deg, transparent ${bandAt - 12}%, black ${bandAt}%, transparent ${bandAt + 12}%)`,
            maskImage: `linear-gradient(115deg, transparent ${bandAt - 12}%, black ${bandAt}%, transparent ${bandAt + 12}%)`,
          }}
        />
      )}
      {/* the glint on the blade */}
      {glint > 0 && glint < 1 && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: 220,
            height: 14,
            borderRadius: 7,
            transform: `translate(${g.x - 110}px, ${g.y - 7}px) rotate(${deg(Math.atan2(AX.y, AX.x) + c.r)}deg)`,
            background: `radial-gradient(ellipse 50% 50% at 50% 50%, ${C.rim}, transparent)`,
            opacity: Math.sin(glint * Math.PI),
            mixBlendMode: 'screen',
          }}
        />
      )}
      {/* the light falls away toward the hips and the edges: the eye stays on the mask and the blade */}
      <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(180deg, transparent 50%, ${C.ink} 90%)` }} />
      <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(ellipse 85% 60% at ${m.x}px ${m.y + 120}px, transparent 45%, rgba(0, 0, 0, 0.55) 100%)` }} />
    </div>
  );
};

// ---------- the inventory (Dota 2's HUD: 3x2 slots, the TP slot, the backpack), in 1x units ----------
const SLOT = { w: 88, h: 64, gap: 6 };
const slotXY = (i: number) => ({ x: (i % 3) * (SLOT.w + SLOT.gap), y: Math.floor(i / 3) * (SLOT.h + SLOT.gap) });
const TP = { x: 3 * (SLOT.w + SLOT.gap), y: SLOT.h + SLOT.gap + 20, w: 44, h: 44 };
const PACK = { y: 2 * (SLOT.h + SLOT.gap) + 6, w: 55, h: 40 };
const PANEL = { x: -10, y: -10, w: TP.x + TP.w + 20, h: PACK.y + PACK.h + 20 };
export const ITEM_STEP = 7.5; // a 16th
const landAt = (i: number) => CUE.item0 + i * ITEM_STEP; // the 5 items, then the TP scroll (i = 5)
const FLIGHT = 20;

/** Where the inventory sits: big and central while it assembles, then low and left for the choice. */
const invCam = (f: number) => {
  const p = track(f, [
    { f: CUE.wipe, v: { x: 172, y: 700, s: 2.2 } },
    { f: CUE.ask + 6, v: { x: 112, y: 1232, s: 1.55 }, e: E.smooth, dur: 24 }, // settled before the candidates rise
  ]);
  // it comes in on the wipe still travelling, and settles
  const settle = 1 - prog(f, CUE.wipe - 6, CUE.item0 + 10, E.out);
  return { x: p.x - AX.x * 140 * settle, y: p.y - AX.y * 140 * settle, s: p.s };
};
const inv = (f: number, p: { x: number; y: number }) => {
  const c = invCam(f);
  return { x: c.x + p.x * c.s, y: c.y + p.y * c.s, s: c.s };
};

const itemSrc = (key: string) => staticFile(`img/dota/items/${key}.png`);
const Icon: React.FC<{ k: string; x: number; y: number; w: number; h: number; style?: React.CSSProperties }> = ({ k, x, y, w, h, style }) => (
  <Img src={itemSrc(k)} style={{ position: 'absolute', left: 0, top: 0, width: w, height: h, borderRadius: 3, transform: `translate(${x}px, ${y}px)`, ...style }} />
);

const Well: React.FC<{ x: number; y: number; w: number; h: number; s: number; lit: number; round?: boolean; dim?: number }> = ({ x, y, w, h, s, lit, round, dim = 1 }) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: 0,
      width: w * s,
      height: h * s,
      transform: `translate(${x}px, ${y}px)`,
      borderRadius: round ? '50%' : 3 * s,
      background: C.slot,
      opacity: dim,
      boxShadow: `inset 0 ${2 * s}px ${6 * s}px ${C.slotShade}, 0 0 0 ${s}px ${C.slotEdge}, 0 0 ${18 * s * lit}px ${C.key}`,
      outline: lit > 0.01 ? `${1.5 * s}px solid rgba(255, 255, 255, ${(0.55 * lit).toFixed(3)})` : undefined,
      outlineOffset: -1.5 * s,
    }}
  />
);

const Inventory: React.FC<{ f: number }> = ({ f }) => {
  const c = invCam(f);
  const leave = prog(f, CUE.pick, CUE.pick + 13, E.exit); // gone before the pause
  const o = 1 - leave;
  if (o <= 0) return null;
  const P = inv(f, PANEL);
  const ask = prog(f, CUE.ask, CUE.ask + 12, E.out) * (1 - prog(f, CUE.pick - 6, CUE.pick + 6, E.smooth));
  return (
    <div style={{ position: 'absolute', inset: 0, opacity: o, transform: `translateY(${70 * leave}px)` }}>
      <div style={{ position: 'absolute', left: 0, top: 0, width: PANEL.w * c.s, height: PANEL.h * c.s, transform: `translate(${P.x}px, ${P.y}px)`, borderRadius: 6 * c.s, background: C.hud, boxShadow: `0 ${20 * c.s}px ${50 * c.s}px rgba(0, 0, 0, 0.5), inset 0 0 0 ${c.s}px ${C.border}` }} />
      {DOTA.slots.map((key, i) => {
        const p = inv(f, slotXY(i));
        const land = key ? landAt(i) : 0;
        const lit = key ? hitPulse(f - land, 1, 5) : 0.35 + 0.65 * ask * (0.75 + 0.25 * Math.sin((f - CUE.ask) / 6));
        return <Well key={`w${i}`} x={p.x} y={p.y} w={SLOT.w} h={SLOT.h} s={c.s} lit={key ? lit : ask * lit} />;
      })}
      <Well x={inv(f, TP).x} y={inv(f, TP).y} w={TP.w} h={TP.h} s={c.s} lit={hitPulse(f - landAt(5), 1, 5)} />
      {[0, 1, 2].map((j) => {
        const p = inv(f, { x: j * (PACK.w + SLOT.gap), y: PACK.y });
        return <Well key={`b${j}`} x={p.x} y={p.y} w={PACK.w} h={PACK.h} s={c.s} lit={0} dim={0.55} />;
      })}
      {[...DOTA.slots.map((key, i) => ({ key, i, to: slotXY(i), w: SLOT.w, h: SLOT.h })), { key: DOTA.tp, i: 5, to: { x: TP.x, y: TP.y }, w: TP.w * 1.375, h: TP.h }].map(({ key, i, to, w, h }) => {
        if (!key) return null;
        const at = landAt(i);
        const t = prog(f, at - FLIGHT, at, E.glide); // picks up speed, then brakes under control into the slot
        if (t <= 0) return null;
        const p = inv(f, to);
        const fly = (1 - t) * 320;
        const settle = hitPulse(f - at, 1, 4);
        const k = mix(1.3, 1, t) * (1 + 0.035 * settle);
        // the TP slot is square: its scroll fills it at the slot's height, centred
        const iw = (i === 5 ? h : w) * c.s * k;
        const ih = h * c.s * k;
        const cx = p.x + ((i === 5 ? TP.w : w) * c.s) / 2 - AX.x * fly;
        const cy = p.y + (h * c.s) / 2 - AX.y * fly;
        return (
          <Icon
            key={`i${i}`}
            k={key}
            x={cx - iw / 2}
            y={cy - ih / 2}
            w={iw}
            h={ih}
            style={{ opacity: clamp(t * 3) * prog(f, CUE.wipe + 2, CUE.wipe + 10, E.smooth), objectFit: 'cover', filter: `brightness(${(1 + 0.5 * settle).toFixed(3)})` }}
          />
        );
      })}
    </div>
  );
};

/** Act 1b: inside the blade. The band opens from the blade's own width along its line until it is the frame. */
const BladeWipe: React.FC<{ f: number; children: React.ReactNode }> = ({ f, children }) => {
  if (f < CUE.wipe - 12) return null;
  // first the blade itself widens into a slit (slow), then the slit opens to the frame (fast, a frame-filling edge)
  const slit = prog(f, CUE.wipe - 12, CUE.wipe - 2, E.smooth);
  const open = prog(f, CUE.wipe - 2, CUE.wipe + 10, E.out); // parts like a cut: fast, then slowing as it leaves the frame
  const full = open >= 1;
  const a = heroPt(Math.min(f, CUE.wipe + 10), HERO.pommel);
  const b = heroPt(Math.min(f, CUE.wipe + 10), HERO.tip);
  const ux = b.x - a.x;
  const uy = b.y - a.y;
  const n = Math.hypot(ux, uy);
  const u = { x: ux / n, y: uy / n };
  const nv = { x: -u.y, y: u.x };
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const w = mix(8, 46, slit) + 1650 * open;
  const L = 3000;
  const pt = (s: number, t: number) => `${(mid.x + u.x * s + nv.x * t).toFixed(1)}px ${(mid.y + u.y * s + nv.y * t).toFixed(1)}px`;
  const clip = full ? undefined : `polygon(${pt(-L, -w)}, ${pt(L, -w)}, ${pt(L, w)}, ${pt(-L, w)})`;
  const edge = 1 - prog(f, CUE.wipe - 5, CUE.wipe - 1, E.smooth); // the edges are gone before the cut parts fast
  return (
    <>
      <div style={{ position: 'absolute', inset: 0, clipPath: clip, background: C.ink }}>
        {/* a cold streak of light along the blade's direction */}
        <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(${deg(Math.atan2(u.y, u.x)) + 90}deg, transparent 30%, ${C.key} 50%, transparent 70%)`, opacity: 0.35 }} />
        {children}
      </div>
      {/* the cut's two edges */}
      {!full &&
        [-1, 1].map((sgn) => (
          <div
            key={sgn}
            style={{
              position: 'absolute',
              left: 0,
              top: 0,
              width: 2 * L,
              height: 3,
              transformOrigin: '0 50%',
              transform: `translate(${mid.x - u.x * L + nv.x * w * sgn}px, ${mid.y - u.y * L + nv.y * w * sgn - 1.5}px) rotate(${deg(Math.atan2(u.y, u.x))}deg)`,
              background: C.rim,
              opacity: edge * 0.85,
            }}
          />
        ))}
    </>
  );
};

// ---------- the choice ----------
/** The card's icon on screen at its resting pose: the chosen candidate sits exactly there (same top-left corner). */
export const cardIconAt = () => {
  const L = lcLayout();
  return { x: LC.x + L.icon.x * LC.S, y: LC.y + L.icon.y * LC.S, w: L.icon.w * LC.S, h: L.icon.h * LC.S };
};
export const PICK_W = 300; // the candidates' width on screen (3.4x the game's 88 px, from the 4x Lanczos copy)
const PICK_H = (PICK_W * 64) / 88;
const candidates = () => {
  const a = cardIconAt();
  return [
    { key: DOTA.answer, x: a.x, y: a.y }, // Black King Bar: where the card's icon will be
    { key: DOTA.damage, x: a.x + PICK_W + 64, y: a.y }, // Butterfly: beside it
  ];
};

/** One candidate's pose: risen out of the empty slot, then the focus (scale, light) moves A → B. */
const candPose = (f: number, j: number) => {
  const empty = inv(f, slotXY(5));
  const s0 = invCam(f).s;
  const c = candidates()[j];
  const rise = prog(f, CUE.ask + 6 + j * 4, CUE.ask + 30 + j * 4, E.glide); // out of the slot, braking into place
  const x = mix(empty.x, c.x, rise);
  const y = mix(empty.y, c.y, rise);
  const w = lmix(SLOT.w * s0, PICK_W, rise);
  // focus: j = 1 (the damage item) first, then j = 0 (Black King Bar); the other steps back
  const onA = prog(f, CUE.optA - 4, CUE.optA + 10, E.out) * (1 - prog(f, CUE.optB - 4, CUE.optB + 10, E.out));
  const onB = prog(f, CUE.optB - 4, CUE.optB + 10, E.out) * (1 - prog(f, CUE.pick, CUE.brk, E.smooth)); // settles back to its exact size for the hand-off
  const mine = j === 1 ? onA : onB;
  const other = j === 1 ? onB : onA;
  const focus = 1 + 0.16 * mine - 0.14 * other;
  const light = 1 + 0.2 * mine - 0.55 * other;
  // the pick: Butterfly falls back the way the items came; Black King Bar stays
  const out = j === 1 ? prog(f, CUE.pick, CUE.pick + 13, E.exit) : 0;
  return { x: x - AX.x * 240 * out, y: y - AX.y * 240 * out + 90 * out, w: w * focus * mix(1, 0.7, out), o: clamp(rise * 4) * (1 - out), light, rise, lit: mine };
};

const Candidates: React.FC<{ f: number }> = ({ f }) => {
  if (f < CUE.ask || f >= CUE.reveal) return null;
  return (
    <>
      {[1, 0].map((j) => {
        const p = candPose(f, j);
        if (p.o <= 0) return null;
        const breath = j === 0 ? 1 + 0.03 * hitPulse(f - CUE.brk, 1, 8) : 1;
        const pw = p.w * breath;
        const h = (pw * 64) / 88;
        // focus scales about the candidate's centre; Black King Bar is back at scale 1 by the pick
        const c = candidates()[j];
        const s0 = invCam(f).s;
        const cx = mix(p.x + (SLOT.w * s0) / 2, c.x + PICK_W / 2, p.rise);
        const cy = mix(p.y + (SLOT.h * s0) / 2, c.y + PICK_H / 2, p.rise);
        const glow = j === 0 ? prog(f, CUE.pick, CUE.brk, E.out) + 0.8 * hitPulse(f - CUE.brk, 1, 8) : 0; // one breath as the music stops
        return (
          <Icon
            key={j}
            k={c.key}
            x={cx - pw / 2}
            y={cy - h / 2}
            w={pw}
            h={h}
            style={{
              opacity: p.o,
              borderRadius: 6,
              filter: `brightness(${p.light.toFixed(3)})${p.light < 0.9 ? ` blur(${(4 * (1 - p.light)).toFixed(2)}px)` : ''}`,
              boxShadow: `0 0 0 ${(2 + 2 * p.lit).toFixed(2)}px rgba(255, 255, 255, ${(0.14 + 0.5 * p.lit).toFixed(3)}), 0 18px 50px rgba(0, 0, 0, 0.6), 0 0 ${(30 * p.lit + 40 * glow).toFixed(1)}px ${C.key}`,
            }}
          />
        );
      })}
    </>
  );
};

/** «ЩО КУПИТИ?»: two words that land on the spoken «Що», read while the focus moves, and leave on the pick. */
const ASK = ['ЩО', 'КУПИТИ?'];
const ASK_SIZE = 124;
const AskLine: React.FC<{ f: number }> = ({ f }) => {
  if (f < CUE.ask - 2 || f > CUE.pick + 20) return null;
  const top = cardIconAt().y - 300;
  let x = 112;
  return (
    <div data-text="ask" style={{ position: 'absolute', left: 112, top, fontSize: ASK_SIZE, width: 800, height: ASK_SIZE }}>
      {ASK.map((w, i) => {
        const at = CUE.ask + i * 6;
        const p = prog(f, at - 2, at + 10, E.out);
        const q = prog(f, CUE.pick + i * 2, CUE.pick + 11 + i * 2, E.exit);
        const el = (
          <span
            key={i}
            style={{
              position: 'absolute',
              left: x - 112,
              top: 0,
              fontFamily: FONT.text,
              fontSize: ASK_SIZE,
              fontWeight: 800,
              letterSpacing: '-0.02em',
              lineHeight: 1,
              whiteSpace: 'pre',
              color: C.text,
              opacity: clamp(p * 2) * (1 - q),
              transform: `translateY(${(-60 * q).toFixed(2)}px) scale(${mix(1.22, 1, p)})`,
              transformOrigin: '0% 80%',
              filter: p < 1 ? `blur(${(8 * (1 - p)).toFixed(2)}px)` : undefined,
            }}
          >
            {w}
          </span>
        );
        x += measureTracked(`${w} `, ASK_SIZE, 800, -0.02);
        return el;
      })}
    </div>
  );
};

/** The whole opening, up to the moment the card takes the icon over. */
export const DotaIntro: React.FC<{ frame: number }> = ({ frame: f }) => {
  if (f >= CUE.reveal) return null;
  return (
    <>
      <HeroShot f={f} />
      <BladeWipe f={f}>
        <Inventory f={f} />
      </BladeWipe>
      <AskLine f={f} />
      <Candidates f={f} />
    </>
  );
};
