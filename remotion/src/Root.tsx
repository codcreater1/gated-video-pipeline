import React from "react";
import { Composition } from "remotion";

import { BedtimeEpisode } from "./BedtimeEpisode";
import { BedtimeShort } from "./BedtimeShort";
import { type Episode, episodeSchema, sampleEpisode, sampleShort } from "./schema";
import { FPS, totalFrames } from "./timing";

const WIDTH = 1920;
const HEIGHT = 1080;

// Shorts dikey. Bu iki sayı `core/config.py`'daki SHORTS_WIDTH/SHORTS_HEIGHT
// ile eşleşmek ZORUNDA — uyumsuzluk render'ı bozmaz, sessizce yanlış oranda
// video üretir ve YouTube onu Shorts rafına koymaz.
const SHORT_WIDTH = 1080;
const SHORT_HEIGHT = 1920;

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

      <Composition
        id="BedtimeShort"
        component={BedtimeShort}
        schema={episodeSchema}
        defaultProps={sampleShort}
        fps={FPS}
        width={SHORT_WIDTH}
        height={SHORT_HEIGHT}
        calculateMetadata={({ props }: { props: Episode }) => ({
          durationInFrames: totalFrames(props),
        })}
      />
    </>
  );
};
