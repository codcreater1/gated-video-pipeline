import React from "react";
import { Composition } from "remotion";

import { BedtimeEpisode } from "./BedtimeEpisode";
import { type Episode, episodeSchema, sampleEpisode } from "./schema";
import { FPS, totalFrames } from "./timing";

const WIDTH = 1920;
const HEIGHT = 1080;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="BedtimeEpisode"
        component={BedtimeEpisode}
        schema={episodeSchema}
        defaultProps={sampleEpisode}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        // Süre sahne listesinden hesaplanır — sabit bir değer, storyboard
        // değiştiğinde sessizce yanlış olurdu.
        calculateMetadata={({ props }: { props: Episode }) => ({
          durationInFrames: totalFrames(props),
        })}
      />
    </>
  );
};
