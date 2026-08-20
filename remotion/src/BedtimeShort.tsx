import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";

import { SceneView } from "./SceneView";
import { paletteFor } from "./palette";
import type { Episode } from "./schema";
import { FPS, type TimedScene, layout } from "./timing";

/**
 * Dikey Short (1080×1920).
 *
 * Bir Short sıfırdan üretilmez — yayınlanmış bir bölümden türetilir
 * (`core/shorts.py`). Yeni senaryo yok, yeni fikir yok; yalnızca kısaltılmış
 * anlatım yeniden seslendirilir. LLM maliyeti $0, TTS maliyeti $0.
 *
 * Bunun neden önemli olduğu `docs/content-guidelines.md §1`'de: Made for Kids
 * bir kanalda Super Thanks, üyelik, end screen ve yorum kapanıyor. Geriye
 * kalan tek native gelir yolu Shorts. Kanalın para kazandığı format bu.
 *
 * Kadraj farkı yalnızca yerleşimde: `SceneView` yüzdeyle konumlandığı için
 * `portrait` bayrağı karakter yerleşimini ve viewBox oranlarını düzeltmeye
 * yetiyor. Ayrı bir sahne bileşeni yazmak iki görsel dilin zamanla
 * ayrışmasına yol açardı.
 */

function resolveAudio(src: string): string {
  return /^(https?:|file:|\/)/.test(src) ? src : staticFile(src);
}

/** Alt şerit: bölüm başlığı. Short'u kaynak bölüme bağlayan tek ipucu. */
const TitleBand: React.FC<{ title: string; ink: string; ground: string }> = ({
  title,
  ink,
  ground,
}) => (
  <AbsoluteFill
    style={{
      justifyContent: "flex-end",
      alignItems: "center",
      paddingBottom: 150,
    }}
  >
    <div
      style={{
        maxWidth: "84%",
        padding: "22px 34px",
        borderRadius: 26,
        background: `${ground}cc`,
        color: ink,
        fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
        fontSize: 46,
        lineHeight: 1.25,
        textAlign: "center",
        // Düşük kontrast bedtime kuralı metin için de geçerli: parlak beyaz
        // bir başlık, karartılmış bir sahnenin üzerinde uyandırıcı olur.
        opacity: 0.88,
      }}
    >
      {title}
    </div>
  </AbsoluteFill>
);

const SceneSlot: React.FC<{ timed: TimedScene }> = ({ timed }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, transitionInFrames, scene } = timed;

  const opacity = interpolate(
    frame,
    [0, transitionInFrames, durationInFrames - transitionInFrames, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const audioDelay = Math.round(scene.audioDelaySeconds * FPS);

  return (
    <AbsoluteFill style={{ opacity }}>
      <SceneView
        scene={scene}
        localFrame={frame}
        durationInFrames={durationInFrames}
        portrait
      />
      {scene.audioSrc ? (
        <Sequence from={audioDelay} name="Anlatım">
          <Audio src={resolveAudio(scene.audioSrc)} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

export const BedtimeShort: React.FC<Episode> = (episode) => {
  const timeline = layout(episode);
  const palette = paletteFor(episode.scenes[0]?.mood ?? "calm");

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

      <TitleBand title={episode.title} ink={palette.ink} ground={palette.ground} />

      {episode.musicSrc ? (
        <Audio src={resolveAudio(episode.musicSrc)} volume={0.18} loop />
      ) : null}
    </AbsoluteFill>
  );
};
