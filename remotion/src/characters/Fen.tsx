import React from "react";

/**
 * Fen — su samuru, Kanal A'nın sabit kahramanı.
 *
 * Kod-tabanlı vektör: tutarlılık **inşaen** garanti. Aynı bileşen her bölümde
 * aynı karakteri üretir; "AI karakteri değiştirdi" diye bir sorun yok.
 *
 * Tasarım kuralları:
 * - Yuvarlak siluet, keskin köşe yok. Keskinlik uyanıklık sinyali.
 * - Gözler kapalıya yakın (yarım kapak) — sakin ifade, uyku öncesi tona uygun.
 * - Palet dışarıdan gelir, böylece karakter sahnenin ışığına uyar.
 */

export type Pose = "standing" | "walking" | "resting" | "looking" | "carrying";

export const POSES: readonly Pose[] = [
  "standing",
  "walking",
  "resting",
  "looking",
  "carrying",
] as const;

export function isPose(value: string): value is Pose {
  return (POSES as readonly string[]).includes(value);
}

type Props = {
  pose: Pose;
  /** 0..1 — yavaş nefes; gövde ve kuyruk buna göre kıpırdar. */
  breath: number;
  /** Sahne aksanı; karın ve burun bundan türer. */
  accent: string;
  /** Karakterin ana gövde rengi. */
  fur?: string;
  size?: number;
  flip?: boolean;
};

const FUR = "#7a5c43";
const FUR_DARK = "#5e4632";
const BELLY = "#c9a882";

export const Fen: React.FC<Props> = ({
  pose,
  breath,
  accent,
  fur = FUR,
  size = 320,
  flip = false,
}) => {
  // Nefes: gövde çok hafif uzayıp kısalır, kuyruk gecikmeli takip eder.
  const bodyScale = 1 + (breath - 0.5) * 0.03;
  const tailSway = (breath - 0.5) * 10;

  const resting = pose === "resting";
  const looking = pose === "looking";
  const carrying = pose === "carrying";
  const walking = pose === "walking";

  // Dinlenirken gövde alçalır ve yayvanlaşır.
  const bodyRy = resting ? 62 : 74;
  const bodyRx = resting ? 86 : 66;
  const bodyCy = resting ? 138 : 124;

  // Bakarken baş yukarı ve hafif yana döner.
  const headTilt = looking ? -12 : walking ? 4 : 0;
  const headCy = resting ? 92 : 70;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 240 220"
      style={{ transform: flip ? "scaleX(-1)" : undefined, overflow: "visible" }}
    >
      <g transform={`translate(120 40) scale(${bodyScale}) translate(-120 -40)`}>
        {/* Kuyruk — UZUN ve tabana doğru incelen. Su samurunun en ayırt edici
            özelliği bu; kısa kalın kuyruk karakteri kunduza benzetiyordu. */}
        <path
          d={
            resting
              ? `M 66 ${bodyCy + 10} Q ${8 + tailSway} ${bodyCy + 34}, ${-28 + tailSway} ${bodyCy + 10}`
              : `M 66 ${bodyCy + 8} Q ${6 + tailSway} ${bodyCy + 40}, ${-18 + tailSway} ${bodyCy - 26}`
          }
          stroke={FUR_DARK}
          strokeWidth={30}
          strokeLinecap="round"
          fill="none"
          opacity={0.95}
        />
        {/* Kuyruk ucu — inceltme etkisi */}
        <path
          d={
            resting
              ? `M 20 ${bodyCy + 22} Q ${-6 + tailSway} ${bodyCy + 24}, ${-28 + tailSway} ${bodyCy + 10}`
              : `M 14 ${bodyCy + 6} Q ${-4 + tailSway} ${bodyCy - 12}, ${-18 + tailSway} ${bodyCy - 26}`
          }
          stroke={FUR_DARK}
          strokeWidth={16}
          strokeLinecap="round"
          fill="none"
        />

        {/* Gövde */}
        <ellipse cx={120} cy={bodyCy} rx={bodyRx} ry={bodyRy} fill={fur} />
        {/* Karın */}
        <ellipse
          cx={124}
          cy={bodyCy + 14}
          rx={bodyRx * 0.58}
          ry={bodyRy * 0.6}
          fill={BELLY}
          opacity={0.9}
        />

        {/* Ön pençeler — taşırken öne uzanır */}
        <ellipse
          cx={carrying ? 150 : 132}
          cy={bodyCy + 44}
          rx={18}
          ry={14}
          fill={FUR_DARK}
        />
        <ellipse
          cx={carrying ? 96 : 104}
          cy={bodyCy + 46}
          rx={18}
          ry={14}
          fill={FUR_DARK}
        />

        {/* Taşınan nesne — sahne bağımsız, yumuşak bir yuvarlak */}
        {carrying ? (
          <circle cx={124} cy={bodyCy + 30} r={20} fill={accent} opacity={0.95} />
        ) : null}

        {/* Baş */}
        <g transform={`rotate(${headTilt} 120 ${headCy})`}>
          <ellipse cx={120} cy={headCy} rx={54} ry={48} fill={fur} />

          {/* Kulaklar — küçük, yuvarlak */}
          <circle cx={82} cy={headCy - 32} r={13} fill={FUR_DARK} />
          <circle cx={158} cy={headCy - 32} r={13} fill={FUR_DARK} />

          {/* Burun bölgesi */}
          <ellipse cx={120} cy={headCy + 16} rx={30} ry={22} fill={BELLY} />
          <ellipse cx={120} cy={headCy + 8} rx={9} ry={7} fill={accent} />

          {/* Gözler — yarım kapalı, sakin. Dinlenirken tamamen kapalı. */}
          {resting ? (
            <>
              <path
                d={`M 92 ${headCy - 6} q 10 8 20 0`}
                stroke={FUR_DARK}
                strokeWidth={4}
                fill="none"
                strokeLinecap="round"
              />
              <path
                d={`M 128 ${headCy - 6} q 10 8 20 0`}
                stroke={FUR_DARK}
                strokeWidth={4}
                fill="none"
                strokeLinecap="round"
              />
            </>
          ) : (
            <>
              <circle cx={102} cy={headCy - 6} r={8} fill="#2b2119" />
              <circle cx={138} cy={headCy - 6} r={8} fill="#2b2119" />
              {/* Üst kapak — bakışı yumuşatır */}
              <path
                d={`M 94 ${headCy - 12} q 8 -5 16 0`}
                stroke={fur}
                strokeWidth={7}
                fill="none"
                strokeLinecap="round"
              />
              <path
                d={`M 130 ${headCy - 12} q 8 -5 16 0`}
                stroke={fur}
                strokeWidth={7}
                fill="none"
                strokeLinecap="round"
              />
            </>
          )}

          {/* Bıyıklar */}
          <g stroke={FUR_DARK} strokeWidth={2} strokeLinecap="round" opacity={0.7}>
            <line x1={94} y1={headCy + 14} x2={68} y2={headCy + 10} />
            <line x1={94} y1={headCy + 19} x2={70} y2={headCy + 22} />
            <line x1={146} y1={headCy + 14} x2={172} y2={headCy + 10} />
            <line x1={146} y1={headCy + 19} x2={170} y2={headCy + 22} />
          </g>
        </g>
      </g>
    </svg>
  );
};
