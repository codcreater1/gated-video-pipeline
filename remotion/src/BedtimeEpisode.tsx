import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

import { SceneView } from "./SceneView";
import type { Episode } from "./schema";
import { FPS, type TimedScene, layout } from "./timing";

/**
 * Ses kaynağını çözer. `core/narration.py` dosya ADI yazar (mutlak yol değil);
 * render `--public-dir` ile o klasörü gösterir. URL verilmişse olduğu gibi
 * kullanılır — bu, ileride uzak asset'lere geçişi kolaylaştırır.
 */
function resolveAudio(src: string): string {
  return /^(https?:|file:|\/)/.test(src) ? src : staticFile(src);
}

/**
 * Bir bedtime bölümü.
 *
 * Uzun-form derlemeler BURADA render EDİLMEZ — 8-12 dakikalık bölümler ayrı ayrı
 * render edilip ffmpeg ile birleştirilir. 60 dakikalık tek render bu CPU'da
 * saatler sürer ve on binlerce ara kare üretir.
 */

const SceneSlot: React.FC<{ timed: TimedScene }> = ({ timed }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, transitionInFrames, scene } = timed;

  // Geçiş sahnenin başında (giriş) ve sonunda (çıkış) çalışır.
  const opacity = interpolate(
    frame,
    [
      0,
      transitionInFrames,
      durationInFrames - transitionInFrames,
      durationInFrames,
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  // Anlatım nefes payından sonra başlar; sahnenin başındaki sessizlik
  // bedtime temposunun parçası, boşluk değil.
  const audioDelay = Math.round(scene.audioDelaySeconds * FPS);

  return (
    <AbsoluteFill style={{ opacity }}>
      <SceneView scene={scene} localFrame={frame} durationInFrames={durationInFrames} />
      {scene.audioSrc ? (
        <Sequence from={audioDelay} name="Anlatım">
          <Audio src={resolveAudio(scene.audioSrc)} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

export const BedtimeEpisode: React.FC<Episode> = (episode) => {
  const timeline = layout(episode);

  return (
    <AbsoluteFill style={{ backgroundColor: "#0b1020" }}>
      {timeline.map((timed) => (
        <Sequence
          key={timed.scene.index}
          from={timed.from}
          durationInFrames={timed.durationInFrames}
          name={`Sahne ${timed.scene.index + 1} — ${timed.scene.mood}`}
        >
          <SceneSlot timed={timed} />
        </Sequence>
      ))}

      {episode.musicSrc ? (
        // Müzik anlatımın belirgin şekilde altında kalır; bedtime içeriğinde
        // müziğin öne çıkması uykuya geçişi bozuyor.
        <Audio src={resolveAudio(episode.musicSrc)} volume={0.18} loop />
      ) : null}
    </AbsoluteFill>
  );
};
