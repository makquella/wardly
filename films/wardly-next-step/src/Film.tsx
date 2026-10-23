import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from 'remotion';
import { C } from './brand/tokens';
import { Audit } from './lib/Audit';
import { FontGate } from './lib/FontGate';
import type { SafeSpec } from './lib/safe';
import { Noise, Question } from './scenes/Chaos';
import { LiveCard, LiveDot, MorphWord } from './scenes/Live';
import { ReviewScene } from './scenes/Review';
import { Finale } from './scenes/Finale';
import { CUE } from './timeline';

/** Written by the audio build. Renders are muted and scripts/render.sh muxes it with ffmpeg. */
export const SOUNDTRACK = 'audio/soundtrack.wav';

export type FilmProps = { audit?: boolean; safe?: SafeSpec; offset?: number };

/** The whole film is one continuous take: every layer is a pure function of the frame. */
export const Picture: React.FC<{ frame: number }> = ({ frame: f }) => (
  <AbsoluteFill style={{ background: C.ink }}>
    <Img src={staticFile('img/stage.png')} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
    <Noise frame={f} />
    {f < CUE.drill + 40 && <Question i={1} frame={f} pose={qOverride(1, f)} />}
    {f < CUE.clear && <Question i={2} frame={f} pose={qOverride(2, f)} />}
    <LiveCard frame={f} />
    {f < CUE.dotLand + 10 && <Question i={0} frame={f} hideKey={f >= CUE.shrink} rollFrame={f} />}
    <MorphWord frame={f} />
    <LiveDot frame={f} />
    <ReviewScene frame={f} />
    <Finale frame={f} />
  </AbsoluteFill>
);

import { qOverride } from './scenes/Review';

export const Film: React.FC<FilmProps> = ({ audit = false, safe, offset = 0 }) => {
  const frame = useCurrentFrame() + offset;
  return (
    <FontGate>
      <Picture frame={frame} />
      {audit && <Audit safe={safe} />}
    </FontGate>
  );
};
