import React from "react";
import { AbsoluteFill, interpolate } from "remotion";

import { Companion } from "./characters/Companion";
import { Fen, type Pose, isPose } from "./characters/Fen";
import { paletteFor } from "./palette";
import type { Scene } from "./schema";

/**
 * Bir sahnenin görsel katmanı.
 *
 * Hareket kasıtlı olarak çok yavaş: bedtime içeriğinde hızlı hareket uyanıklık
 * sinyali. Ayrıca düşük hareket = düşük kare-farkı, h264 bunu çok iyi sıkıştırıyor
 * ve bu CPU'da render süresini kısaltıyor (ölçüldü: 8.2 kare/sn).
 *
 * Katman sırası: gökyüzü → uzak siluet → ışık havuzu → zemin → su → karakterler.
 */

type Props = {
  scene: Scene;
  localFrame: number;
  durationInFrames: number;
};

/** Sahne boyunca tek bir yavaş nefes — 0..1..0. */
function breathe(localFrame: number, durationInFrames: number): number {
  const t = localFrame / Math.max(1, durationInFrames);
  return (Math.sin(t * Math.PI * 2 - Math.PI / 2) + 1) / 2;
}

function poseFrom(assetId: string): Pose {
  const last = assetId.split("/").pop() ?? "standing";
  return isPose(last) ? last : "standing";
}

const Sky: React.FC<{ top: string; bottom: string; drift: number }> = ({
  top,
  bottom,
  drift,
}) => (
  <AbsoluteFill
    style={{ background: `linear-gradient(${175 + drift * 6}deg, ${top} 0%, ${bottom} 100%)` }}
  />
);

/** Yıldız alanı — deterministik konum, sahne boyunca çok yavaş sönümlenme. */
const Stars: React.FC<{ ink: string; phase: number }> = ({ ink, phase }) => {
  // Sabit tohum: yıldızlar sahneden sahneye zıplamaz, gökyüzü kararlı kalır.
  const stars = React.useMemo(() => {
    let seed = 20260813;
    const next = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    return Array.from({ length: 60 }, () => ({
      x: next() * 1920,
      y: next() * 620,
      r: 1 + next() * 2.2,
      off: next(),
    }));
  }, []);

  return (
    <AbsoluteFill>
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="none">
        {stars.map((s, i) => (
          <circle
            key={i}
            cx={s.x}
            cy={s.y}
            r={s.r}
            fill={ink}
            opacity={0.12 + 0.28 * (0.5 + 0.5 * Math.sin((phase + s.off) * Math.PI * 2))}
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};

/** Ay — bedtime kanalının sabit göksel işareti, sağ üstte. */
const Moon: React.FC<{ accent: string; glow: number }> = ({ accent, glow }) => (
  <AbsoluteFill>
    <svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="none">
      <circle cx={1560} cy={210} r={110} fill={accent} opacity={0.1 + glow * 0.06} />
      <circle cx={1560} cy={210} r={74} fill={accent} opacity={0.16 + glow * 0.08} />
      <circle cx={1560} cy={210} r={52} fill={accent} opacity={0.92} />
      {/* Kraterler — çok düşük kontrast, dikkat çekmemeli */}
      <circle cx={1544} cy={196} r={11} fill="#00000012" />
      <circle cx={1576} cy={224} r={8} fill="#00000010" />
      <circle cx={1568} cy={188} r={6} fill="#0000000e" />
    </svg>
  </AbsoluteFill>
);

/** Uzak ağaç hattı — derinlik verir, dikkat çekmez. */
const Treeline: React.FC<{ color: string }> = ({ color }) => (
  <AbsoluteFill style={{ top: "48%" }}>
    <svg width="100%" height="100%" viewBox="0 0 1920 560" preserveAspectRatio="none">
      <path
        d="M0 160 L90 70 L170 150 L250 60 L330 140 L420 80 L500 150 L590 70
           L680 145 L770 90 L860 155 L950 65 L1040 140 L1130 85 L1220 150
           L1310 70 L1400 145 L1490 90 L1580 150 L1670 75 L1760 140 L1850 95
           L1920 150 L1920 560 L0 560 Z"
        fill={color}
        opacity={0.5}
      />
    </svg>
  </AbsoluteFill>
);

const Glow: React.FC<{ color: string; intensity: number }> = ({ color, intensity }) => {
  const alpha = Math.round(20 + intensity * 24)
    .toString(16)
    .padStart(2, "0");
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 54%, ${color}${alpha} 0%, transparent 58%)`,
      }}
    />
  );
};

/**
 * Karakterlerin ayak bastığı çizgi. Zemin, karakterler ve su hep buna göre
 * konumlanır — ayrı ayrı yüzde değerleri vermek, bir katman değiştiğinde
 * figürlerin havada kalmasına yol açıyordu.
 */
const BASELINE_PCT = 72;

/**
 * Zemin kasıtlı olarak neredeyse düz: belirgin elips eğrisi, farklı x'lerde
 * duran karakterlerin farklı yüksekliklere denk gelmesine ve havada durur
 * görünmesine sebep oluyordu. Hafif kavis derinlik için yeterli.
 */
const Ground: React.FC<{ color: string; rise: number }> = ({ color, rise }) => (
  <AbsoluteFill
    style={{
      top: `${BASELINE_PCT - 4 + rise}%`,
      background: color,
      borderTopLeftRadius: "50% 6%",
      borderTopRightRadius: "50% 6%",
    }}
  />
);

/** Fen'in dünyası dere — su şeridi markanın görsel imzası. */
const Water: React.FC<{ accent: string; drift: number }> = ({ accent, drift }) => (
  <AbsoluteFill style={{ top: `${BASELINE_PCT + 8}%` }}>
    <svg width="100%" height="100%" viewBox="0 0 1920 300" preserveAspectRatio="none">
      <rect width="1920" height="300" fill={accent} opacity={0.12} />
      {[0, 1, 2, 3].map((i) => (
        <path
          key={i}
          d={`M0 ${40 + i * 62} Q 480 ${24 + i * 62 + drift * 10}, 960 ${40 + i * 62}
              T 1920 ${40 + i * 62}`}
          stroke={accent}
          strokeWidth={3}
          fill="none"
          opacity={0.24 - i * 0.045}
        />
      ))}
    </svg>
  </AbsoluteFill>
);

/**
 * Bir figürü taban çizgisine oturtur: kutunun ALT kenarı BASELINE'da, içerik
 * alta hizalı. Karakterleri `top` ile konumlandırmak, SVG boyutu her
 * değiştiğinde figürleri havaya kaldırıyordu.
 */
function standOn(left: string): React.CSSProperties {
  return {
    position: "absolute",
    left,
    bottom: `${100 - BASELINE_PCT}%`,
    transform: "translateX(-50%)",
    display: "flex",
    justifyContent: "center",
    alignItems: "flex-end",
  };
}

export const SceneView: React.FC<Props> = ({ scene, localFrame, durationInFrames }) => {
  const palette = paletteFor(scene.mood);
  const b = breathe(localFrame, durationInFrames);
  const heroPose = poseFrom(scene.assets.character);
  const hasCompanion = Boolean(scene.assets.companion);

  // Sabit kadraj ölü görünüyor, hızlı hareket uyandırıyor. %1.5 doğru aralık.
  const zoom = interpolate(localFrame, [0, durationInFrames], [1, 1.015], {
    extrapolateRight: "clamp",
  });

  // Misafir varsa Fen sola kayar; yalnızsa ortada durur.
  const heroLeft = hasCompanion ? "38%" : "50%";

  return (
    <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 58%" }}>
      <Sky top={palette.skyTop} bottom={palette.skyBottom} drift={b} />
      <Stars ink={palette.ink} phase={localFrame / Math.max(1, durationInFrames)} />
      <Moon accent={palette.accent} glow={b} />
      <Treeline color={palette.ground} />
      <Glow color={palette.accent} intensity={b} />
      <Ground color={palette.ground} rise={b * 0.5} />
      <Water accent={palette.accent} drift={b} />

      {/* Karakterler tabana OTURUR — kutunun alt kenarı BASELINE'a hizalanır,
          böylece bir katman değişince figürler havada kalmaz. */}
      <div style={{ ...standOn(heroLeft), width: 420, height: 420 }}>
        <Fen pose={heroPose} breath={b} accent={palette.accent} size={400} />
      </div>

      {scene.assets.companion ? (
        <div style={{ ...standOn("68%"), width: 320, height: 320 }}>
          <Companion
            assetId={scene.assets.companion}
            breath={1 - b}
            accent={palette.accent}
            size={300}
          />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
