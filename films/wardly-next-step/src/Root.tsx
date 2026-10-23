import React from 'react';
import { Composition, Folder } from 'remotion';
import { Film, FilmProps } from './Film';
import { FilmSub, subMetadata } from './FilmSub';
import { ACT, CUE, FPS, H, TOTAL, W } from './timeline';

export const RemotionRoot: React.FC = () => (
  <>
    {/* The film. Render with scripts/render.sh (muted picture + ffmpeg mux + sync check). */}
    <Composition id="Film" component={Film} durationInFrames={TOTAL} fps={FPS} width={W} height={H} defaultProps={{ audit: false } as FilmProps} />
    {/* The film as sub-frames for the motion-blurred master (render.sh --blur passes out/samples.json). */}
    <Composition id="FilmSub" component={FilmSub} durationInFrames={TOTAL} fps={FPS} width={W} height={H} defaultProps={{ groups: [] as number[] }} calculateMetadata={subMetadata} />
    <Folder name="Acts">
      {/* Each act is a range of the one continuous take (offset = its first frame). */}
      <Composition id="Act1" component={Film} durationInFrames={ACT.chaos.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.chaos.from } as FilmProps} />
      <Composition id="Act2" component={Film} durationInFrames={ACT.live.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.live.from } as FilmProps} />
      <Composition id="Act3" component={Film} durationInFrames={ACT.review.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.review.from } as FilmProps} />
      <Composition id="Act4" component={Film} durationInFrames={ACT.resolve.dur} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: ACT.resolve.from } as FilmProps} />
      {/* The hardest transition, with sound: the storm, the break, the morph into the card (3.0 s .. 10.0 s). */}
      <Composition id="Transition" component={Film} durationInFrames={CUE.away - 180} fps={FPS} width={W} height={H} defaultProps={{ audit: false, offset: 180 } as FilmProps} />
    </Folder>
  </>
);
