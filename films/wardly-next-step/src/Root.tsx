import React from 'react';
import { Composition, Folder } from 'remotion';
import { Film, FilmProps } from './Film';
import { FilmSub, subMetadata } from './FilmSub';
import { ACT, FPS, H, TOTAL, W } from './timeline';

/** The opening, rendered alone for review: up to a beat after the card is complete. */
export const INTRO = 450;

export const RemotionRoot: React.FC = () => (
  <>
    {/* The film. Render with scripts/render.sh (muted picture + ffmpeg mux + sync check). */}
    <Composition id="Film" component={Film} durationInFrames={TOTAL} fps={FPS} width={W} height={H} defaultProps={{ audit: false } as FilmProps} />
    {/* The film as sub-frames for the motion-blurred master (render.sh --blur passes out/samples.json). */}
    <Composition id="FilmSub" component={FilmSub} durationInFrames={TOTAL} fps={FPS} width={W} height={H} defaultProps={{ groups: [] as number[] }} calculateMetadata={subMetadata} />
    <Folder name="Acts">
      {/* Each act is a range of the one continuous take (offset = its first frame). */}
      <Composition id="Act1" component={Film} durationInFrames={ACT.dota.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.dota.from } as FilmProps} />
      <Composition id="Act2" component={Film} durationInFrames={ACT.live.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.live.from } as FilmProps} />
      <Composition id="Act3" component={Film} durationInFrames={ACT.review.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.review.from } as FilmProps} />
      <Composition id="Act4" component={Film} durationInFrames={ACT.resolve.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.resolve.from } as FilmProps} />
      {/* The opening and its hand-off into the card, with sound (0 .. 7.5 s). */}
      <Composition id="Intro" component={Film} durationInFrames={INTRO} fps={FPS} width={W} height={H} defaultProps={{ audit: false } as FilmProps} />
    </Folder>
  </>
);
