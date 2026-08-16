import React from "react";

/**
 * Misafir — her bölümde değişen ikinci karakter.
 *
 * 16 türü tek tek çizmek yerine, tür adından **deterministik** olarak siluet
 * parametreleri türetiliyor: aynı tür her zaman aynı görünür, farklı türler
 * belirgin şekilde ayrışır. Bu, kod-tabanlı vektörün asıl kazancı — varyasyon
 * bedava geliyor ve tutarlılık kaybolmuyor.
 *
 * Fen'den kasıtlı olarak daha küçük ve daha basit: kahraman görsel olarak
 * baskın kalmalı.
 */

type Props = {
  /** `char/<tür>/<poz>` biçimindeki asset kimliği. */
  assetId: string;
  breath: number;
  accent: string;
  size?: number;
};

/** Tür adından kararlı bir sayı — aynı tür hep aynı silueti alır. */
function hashOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

type Family = "bird" | "longear" | "rounded" | "pointed" | "tall";

type Silhouette = {
  family: Family;
  bodyRx: number;
  bodyRy: number;
  earSize: number;
  neck: number;
  fur: string;
};

const FURS = [
  "#8d6f52",
  "#6b7a5e",
  "#9a8878",
  "#5f6b74",
  "#8a5f52",
  "#7d7b62",
  "#a08a6a",
  "#6d5f6e",
];

/**
 * Tür → aile eşlemesi. İlk sürümde siluet tamamen hash'ten türetiliyordu ve
 * balıkçıl uzun kulaklı bir tavşan olarak çiziliyordu. Aile anahtar kelimeden
 * belirlenir; hash yalnızca aile İÇİNDE varyasyon (renk, ölçü) üretir.
 *
 * Anahtarlar `core/storyboard.py::_slug` çıktısıyla eşleşir (Türkçe → ASCII).
 */
const FAMILY_KEYWORDS: ReadonlyArray<readonly [Family, readonly string[]]> = [
  ["bird", ["baykus", "balikcil", "kaz", "guvercin", "kus"]],
  ["longear", ["tavsan"]],
  ["tall", ["geyik"]],
  ["pointed", ["tilki", "sincap", "fare", "gelincik"]],
  ["rounded", ["porsuk", "kirpi", "kunduz", "kaplumbaga", "kurbaga"]],
];

function familyOf(species: string): Family {
  for (const [family, keys] of FAMILY_KEYWORDS) {
    if (keys.some((k) => species.includes(k))) return family;
  }
  return "rounded";
}

function silhouetteFor(species: string): Silhouette {
  const h = hashOf(species);
  const family = familyOf(species);

  // Aile temel oranları; hash bunların üstüne küçük bir sapma ekler.
  const base: Record<Family, { rx: number; ry: number; neck: number; ear: number }> = {
    bird: { rx: 30, ry: 40, neck: 34, ear: 0 },
    longear: { rx: 32, ry: 40, neck: 0, ear: 13 },
    tall: { rx: 30, ry: 44, neck: 22, ear: 8 },
    pointed: { rx: 34, ry: 36, neck: 0, ear: 10 },
    rounded: { rx: 40, ry: 38, neck: 0, ear: 8 },
  };
  const b = base[family];

  return {
    family,
    bodyRx: b.rx + (h % 7),
    bodyRy: b.ry + ((h >> 4) % 9),
    earSize: b.ear === 0 ? 0 : b.ear + ((h >> 12) % 4),
    neck: b.neck === 0 ? 0 : b.neck + ((h >> 8) % 14),
    fur: FURS[(h >> 20) % FURS.length] ?? FURS[0]!,
  };
}

export const Companion: React.FC<Props> = ({ assetId, breath, accent, size = 200 }) => {
  const parts = assetId.split("/");
  const species = parts[1] ?? "guest";
  const pose = parts[2] ?? "standing";
  const s = silhouetteFor(species);

  const resting = pose === "resting";
  const bob = (breath - 0.5) * 6;
  const bodyCy = 130 - (resting ? 10 : 0);
  const headCy = bodyCy - s.bodyRy - s.neck - 18;

  return (
    <svg width={size} height={size} viewBox="0 0 200 200" style={{ overflow: "visible" }}>
      <g transform={`translate(0 ${bob})`}>
        {/* Boyun — yalnızca uzun boyunlu türlerde */}
        {s.neck > 0 ? (
          <rect
            x={96}
            y={headCy}
            width={12}
            height={s.neck + 20}
            rx={6}
            fill={s.fur}
          />
        ) : null}

        {/* Gövde */}
        <ellipse cx={100} cy={bodyCy} rx={s.bodyRx} ry={resting ? s.bodyRy * 0.78 : s.bodyRy} fill={s.fur} />
        <ellipse
          cx={102}
          cy={bodyCy + 8}
          rx={s.bodyRx * 0.55}
          ry={s.bodyRy * 0.5}
          fill="#00000018"
        />

        {/* Baş */}
        <circle cx={102} cy={headCy} r={26} fill={s.fur} />

        {/* Kulaklar — aileye göre. Kuşlarda kulak yok, gaga var. */}
        {s.family === "longear" ? (
          <>
            <ellipse
              cx={90}
              cy={headCy - 30}
              rx={s.earSize * 0.5}
              ry={s.earSize * 2}
              fill={s.fur}
            />
            <ellipse
              cx={114}
              cy={headCy - 30}
              rx={s.earSize * 0.5}
              ry={s.earSize * 2}
              fill={s.fur}
            />
          </>
        ) : null}
        {s.family === "pointed" ? (
          <>
            <path
              d={`M 84 ${headCy - 14} L 78 ${headCy - 34} L 98 ${headCy - 24} Z`}
              fill={s.fur}
            />
            <path
              d={`M 120 ${headCy - 14} L 126 ${headCy - 34} L 106 ${headCy - 24} Z`}
              fill={s.fur}
            />
          </>
        ) : null}
        {s.family === "rounded" || s.family === "tall" ? (
          <>
            <circle cx={84} cy={headCy - 20} r={s.earSize} fill={s.fur} />
            <circle cx={120} cy={headCy - 20} r={s.earSize} fill={s.fur} />
          </>
        ) : null}

        {/* Gözler — Fen gibi sakin, dinlenirken kapalı */}
        {resting ? (
          <path
            d={`M 92 ${headCy - 2} q 6 6 12 0`}
            stroke="#2b2119"
            strokeWidth={3}
            fill="none"
            strokeLinecap="round"
          />
        ) : (
          <>
            <circle cx={94} cy={headCy - 3} r={4.5} fill="#2b2119" />
            <circle cx={112} cy={headCy - 3} r={4.5} fill="#2b2119" />
          </>
        )}

        {/* Gaga (kuşlar) veya burun — aksan rengiyle, sahneye bağlanır */}
        {s.family === "bird" ? (
          <path
            d={`M 118 ${headCy + 2} L 152 ${headCy + 8} L 118 ${headCy + 12} Z`}
            fill={accent}
          />
        ) : (
          <ellipse cx={103} cy={headCy + 9} rx={6} ry={4.5} fill={accent} />
        )}

        {/* Uzun bacaklar — balıkçıl, geyik. Suda duruş markanın parçası. */}
        {s.neck > 0 ? (
          <g stroke={s.fur} strokeWidth={6} strokeLinecap="round">
            <line x1={94} y1={bodyCy + s.bodyRy - 4} x2={90} y2={bodyCy + s.bodyRy + 30} />
            <line x1={110} y1={bodyCy + s.bodyRy - 4} x2={114} y2={bodyCy + s.bodyRy + 30} />
          </g>
        ) : null}
      </g>
    </svg>
  );
};
