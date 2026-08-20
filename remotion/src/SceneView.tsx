import React from "react";
import { AbsoluteFill, interpolate } from "remotion";

import { BackdropFar, BackdropFrame, BackdropNear } from "./backgrounds/Backdrop";
import { BASELINE_PCT, GROUND_TOP_PCT } from "./backgrounds/layout";
import { backdropOf } from "./backgrounds/terrain";
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
 * Katman sırası:
 *   gökyüzü → yıldız → ay → MEKÂN (uzak) → ışık → zemin → su →
 *   MEKÂN (yakın) → karakterler → MEKÂN (çerçeve)
 *
 * Mekân katmanları `scene.assets.background` kimliğinden gelir. Bu bağlantı
 * bir süre eksikti: sahne kimliği ne olursa olsun aynı ağaç hattı ve aynı
 * dere çiziliyordu, yani varyasyon kapısının görsel ekseni ekranda karşılığı
 * olmayan bir çeşitliliği ölçüyordu.
 */

type Props = {
  scene: Scene;
  localFrame: number;
  durationInFrames: number;
  /**
   * Dikey kadraj (Shorts, 1080×1920). Katmanlar yüzdeyle konumlandığı için
   * kendiliğinden uyum sağlıyor; ayarlanması gereken tek şey karakterlerin
   * yatay yerleşimi — 1920 genişliğe göre seçilmiş yüzdeler 1080'de figürleri
   * üst üste bindiriyor.
   */
  portrait?: boolean;
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

/** Yıldız alanı — deterministik konum, sahne boyunca çok yavaş sönümlenme.
 *
 * `visibility` mekândan gelir: sisli bir tepede yıldız görünmez, açıklıkta
 * gökyüzü kanalın en açık hâlidir. Yıldızları her mekânda aynı yoğunlukta
 * çizmek, mekânları birbirine benzeten şeylerden biriydi.
 */
const Stars: React.FC<{
  ink: string;
  phase: number;
  visibility: number;
  portrait: boolean;
}> = ({ ink, phase, visibility, portrait }) => {
  // Kadraj oranı değişince viewBox da değişmeli. Sabit 1920×1080 viewBox'ı
  // dikey kadrajda `preserveAspectRatio="none"` ile germek yıldızları ve ayı
  // elipse çeviriyordu.
  const vw = portrait ? 1080 : 1920;
  const vh = portrait ? 1920 : 1080;
  // Sabit tohum: yıldızlar sahneden sahneye zıplamaz, gökyüzü kararlı kalır.
  const stars = React.useMemo(() => {
    let seed = 20260813;
    const next = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    return Array.from({ length: 60 }, () => ({
      x: next() * vw,
      y: next() * vh * 0.57,
      r: 1 + next() * 2.2,
      off: next(),
    }));
  }, [vw, vh]);

  return (
    <AbsoluteFill>
      <svg width="100%" height="100%" viewBox={`0 0 ${vw} ${vh}`} preserveAspectRatio="none">
        {stars.map((s, i) => (
          <circle
            key={i}
            cx={s.x}
            cy={s.y}
            r={s.r}
            fill={ink}
            opacity={
              visibility *
              (0.12 + 0.28 * (0.5 + 0.5 * Math.sin((phase + s.off) * Math.PI * 2)))
            }
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};

/** Ay — bedtime kanalının sabit göksel işareti, sağ üstte. */
const Moon: React.FC<{ accent: string; glow: number; portrait: boolean }> = ({
  accent,
  glow,
  portrait,
}) => {
  const vw = portrait ? 1080 : 1920;
  const vh = portrait ? 1920 : 1080;
  // Konum orantısal: her iki kadrajda da sağ üstte, aynı yerde.
  const cx = vw * 0.81;
  const cy = vh * 0.195;
  return (
    <AbsoluteFill>
      <svg width="100%" height="100%" viewBox={`0 0 ${vw} ${vh}`} preserveAspectRatio="none">
        <circle cx={cx} cy={cy} r={110} fill={accent} opacity={0.1 + glow * 0.06} />
        <circle cx={cx} cy={cy} r={74} fill={accent} opacity={0.16 + glow * 0.08} />
        <circle cx={cx} cy={cy} r={52} fill={accent} opacity={0.92} />
        {/* Kraterler — çok düşük kontrast, dikkat çekmemeli */}
        <circle cx={cx - 16} cy={cy - 14} r={11} fill="#00000012" />
        <circle cx={cx + 16} cy={cy + 14} r={8} fill="#00000010" />
        <circle cx={cx + 8} cy={cy - 22} r={6} fill="#0000000e" />
      </svg>
    </AbsoluteFill>
  );
};

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
 * Zemin kasıtlı olarak neredeyse düz: belirgin elips eğrisi, farklı x'lerde
 * duran karakterlerin farklı yüksekliklere denk gelmesine ve havada durur
 * görünmesine sebep oluyordu. Hafif kavis derinlik için yeterli.
 *
 * Taban çizgisi artık `backgrounds/layout.ts`'te: mekân katmanları da aynı
 * çizgilere oturmak zorunda ve iki yerde tutmak kaçınılmaz olarak kayardı.
 */
const Ground: React.FC<{ color: string; rise: number }> = ({ color, rise }) => (
  <AbsoluteFill
    style={{
      top: `${GROUND_TOP_PCT + rise}%`,
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

export const SceneView: React.FC<Props> = ({
  scene,
  localFrame,
  durationInFrames,
  portrait = false,
}) => {
  const palette = paletteFor(scene.mood);
  const b = breathe(localFrame, durationInFrames);
  const heroPose = poseFrom(scene.assets.character);
  const hasCompanion = Boolean(scene.assets.companion);
  const spec = backdropOf(scene.assets.background);
  const layer = { spec, palette, breath: b };

  // Sabit kadraj ölü görünüyor, hızlı hareket uyandırıyor. %1.5 doğru aralık.
  const zoom = interpolate(localFrame, [0, durationInFrames], [1, 1.015], {
    extrapolateRight: "clamp",
  });

  // Misafir varsa Fen sola kayar; yalnızsa ortada durur.
  const heroLeft = hasCompanion ? (portrait ? "31%" : "38%") : "50%";
  const guestLeft = portrait ? "75%" : "68%";
  // Dikey kadrajda figürler telefonda küçük kalmasın diye biraz büyütülür,
  // ama kutular dar genişlikte çakışmayacak kadar da küçültülür.
  const heroBox = portrait ? 360 : 420;
  const guestBox = portrait ? 260 : 320;

  return (
    <AbsoluteFill style={{ transform: `scale(${zoom})`, transformOrigin: "50% 58%" }}>
      <Sky top={palette.skyTop} bottom={palette.skyBottom} drift={b} />
      <Stars
        ink={palette.ink}
        phase={localFrame / Math.max(1, durationInFrames)}
        visibility={spec.starVisibility}
        portrait={portrait}
      />
      <Moon accent={palette.accent} glow={b} portrait={portrait} />
      <BackdropFar {...layer} />
      <Glow color={palette.accent} intensity={b} />
      <Ground color={palette.ground} rise={b * 0.5} />
      {/* Su her mekânda yok: dere Fen'in evi ama kumsalda deniz, çayırda
          hiç su olmaz. Su şeridini her sahneye çizmek mekânları birbirine
          benzeten en büyük etkendi. */}
      {spec.hasWater ? <Water accent={palette.accent} drift={b} /> : null}
      <BackdropNear {...layer} />

      {/* Karakterler tabana OTURUR — kutunun alt kenarı BASELINE'a hizalanır,
          böylece bir katman değişince figürler havada kalmaz. */}
      <div style={{ ...standOn(heroLeft), width: heroBox, height: heroBox }}>
        <Fen pose={heroPose} breath={b} accent={palette.accent} size={heroBox - 20} />
      </div>

      {scene.assets.companion ? (
        <div style={{ ...standOn(guestLeft), width: guestBox, height: guestBox }}>
          <Companion
            assetId={scene.assets.companion}
            breath={1 - b}
            accent={palette.accent}
            size={guestBox - 20}
          />
        </div>
      ) : null}

      {/* Kadrajı çerçeveleyen katman — karakterlerin ÖNÜNDE. Yalnızca ağaç
          kovuğu kullanıyor; "içeride olma" hissini veren şey bu. */}
      <BackdropFrame {...layer} />
    </AbsoluteFill>
  );
};
