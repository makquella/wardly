// The review's two questions, «Чому відстаю?» and «Що змінити?»: they come forward from the edges and
// are answered by the review card; each «?» loses its hook and its dot travels on (scenes/Review.tsx).
import React from 'react';
import { C, FONT, TYPE } from '../brand/tokens';
import { E, mix, prog } from '../lib/anim';
import { CUE } from '../timeline';
import { qDotLocal, qFont, Q_KEY_TOP, Q_LEAD, QUESTIONS } from './layout';

/** Frames over which question i's «?» loses its hook (null: it keeps it). */
export const HOOK: Record<number, [number, number]> = {
  1: [CUE.index - 36, CUE.index - 22],
  2: [CUE.drill - 14, CUE.drill - 2],
};

export type QOverride = { x: number; y: number; s: number; o: number; leadO?: number; keyO?: number } | null;

export const Question: React.FC<{ i: number; frame: number; pose: QOverride }> = ({ i, frame: f, pose }) => {
  const q = QUESTIONS[i];
  const p = pose;
  if (!p || p.o <= 0.001) return null;
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
    fontKerning: 'none',
  };
  return (
    <div
      data-text={`q${i + 1}`}
      // fontSize: the block's smallest text (the lead word), so the layout audit measures real type, not the 16 px default
      style={{ position: 'absolute', left: 0, top: 0, fontSize: Q_LEAD, transform: `translate(${p.x}px, ${p.y}px) scale(${p.s})`, transformOrigin: '0 0', opacity: p.o }}
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
          opacity: p.leadO ?? 1,
        }}
      >
        {q.lead}
      </div>
      <div style={{ ...keyStyle, position: 'absolute', left: 0, top: Q_KEY_TOP, opacity: p.keyO ?? 1 }}>
        <span>{q.key}</span>
        <span style={{ clipPath: `inset(${clipTop}px 0 0 0)`, opacity: dotGone ? 0 : 1 }}>?</span>
      </div>
    </div>
  );
};

/** The «?» dot of question i at scale 1, as a circle (the traveller starts exactly here). */
export const qDotScreen = (i: number, pose: NonNullable<QOverride>) => {
  const p = pose;
  const d = qDotLocal(i);
  return { x: p.x + d.x * p.s, y: p.y + d.y * p.s, r: d.r * p.s };
};
