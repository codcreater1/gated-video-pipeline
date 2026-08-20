import React from "react";
import { AbsoluteFill } from "remotion";

import { type Palette, mix } from "../palette";
import { GROUND_TOP_PCT, HORIZON_PCT } from "./layout";
import type { Backdrop as BackdropSpec, Terrain } from "./terrain";

/**
 * Mekâna özgü görsel katman — asset pack'in kendisi.
 *
 * 12 mekânın her biri ayrı bir siluet üretir. Dosya değil kod: `docs/
 * content-guidelines.md §4` gereği görsel dil kod-tabanlı vektör, çünkü
 * karakter ve mekân tutarlılığı **inşaen** garanti olmalı — aynı kimlik her
 * bölümde aynı görseli üretir, görüntü modeli gerekmez, maliyet $0.
 *
 * Katmanlar iki gruba ayrılır:
 *
 *   FarLayer  — zeminin ARKASINDA. Ağaç hattı, tepeler, uzak kıyı.
 *   NearLayer — zeminin ÖNÜNDE, karakterlerin arkasında. Ot, çiçek, kaya.
 *
 * Ortadaki zemin şeridini `SceneView` çiziyor; buradaki katmanlar ona göre
 * konumlanır (bkz. `layout.ts`).
 */

type LayerProps = {
  spec: BackdropSpec;
  palette: Palette;
  /** 0..1 nefes döngüsü — çok yavaş sürüklenme için. */
  breath: number;
};

/** Aynı mekân her bölümde aynı görünmeli: sabit tohumlu deterministik PRNG. */
function rngFor(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function seedOf(terrain: Terrain): number {
  let h = 2166136261;
  for (let i = 0; i < terrain.length; i++) {
    h ^= terrain.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/**
 * Hava perspektifi. Uzak katmanlar gökyüzü rengine doğru açılır, yakın olanlar
 * zemine yaklaşır.
 *
 * Bu olmadan her katman `palette.ground` kullanıyordu ve zemin de aynı renk
 * olduğu için arazi siluetleri görünmez oluyordu — karlı ormanda ekranda kalan
 * tek şey kar başlıklarıydı. Derinlik burada renkten geliyor, çizgiden değil.
 */
function depths(palette: Palette) {
  return {
    far: mix(palette.ground, palette.skyBottom, 0.38),
    mid: mix(palette.ground, palette.skyBottom, 0.2),
    near: mix(palette.ground, palette.skyBottom, 0.06),
  };
}

/** Uzak katmanların hepsi bu kutuya çizilir: ufuktan zeminin altına kadar. */
const FarBox: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ top: `${HORIZON_PCT}%` }}>
    {/* `slice`, `none` değil: yatay kadrajda ikisi aynı sonucu verir (oranlar
        zaten örtüşüyor), ama dikey Shorts kadrajında `none` çamları ve ağaç
        taçlarını eziyordu. `slice` şekilleri bozmadan ölçekleyip kenardan
        kırpıyor — dar kadrajda arazinin ortası görünüyor. */}
    <svg width="100%" height="100%" viewBox="0 0 1920 560" preserveAspectRatio="xMidYMid slice">
      {children}
    </svg>
  </AbsoluteFill>
);

/** Yakın katmanlar zeminin üstüne oturur. */
const NearBox: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ top: `${GROUND_TOP_PCT}%` }}>
    <svg width="100%" height="100%" viewBox="0 0 1920 300" preserveAspectRatio="xMidYMid slice">
      {children}
    </svg>
  </AbsoluteFill>
);

/**
 * Zeminin başladığı çizgi, FarBox'ın kendi koordinatlarında. Uzak katmanların
 * tabanı buranın biraz altında bitmeli — yukarıda bitirmek gökyüzü renginde
 * bir boşluk şeridi bırakıyor.
 */
const FAR_BASE = 224;

// --------------------------------------------------------------------------
// Şekil yardımcıları
// --------------------------------------------------------------------------

/** Üçgen çam. */
function pine(x: number, base: number, w: number, h: number): string {
  return `M ${x - w} ${base} L ${x} ${base - h} L ${x + w} ${base} Z`;
}

/** Yumuşak tepe kavisi — tabana kadar dolar. */
function hill(y: number, amp: number, phase: number): string {
  return (
    `M 0 ${y + amp} ` +
    `Q 320 ${y - amp * phase}, 640 ${y} ` +
    `T 1280 ${y + amp * 0.4} ` +
    `T 1920 ${y - amp * 0.2} ` +
    `L 1920 560 L 0 560 Z`
  );
}

// --------------------------------------------------------------------------
// Arazi katmanları
// --------------------------------------------------------------------------

const Conifer: React.FC<LayerProps & { snowy?: boolean }> = ({
  palette,
  spec,
  snowy = false,
}) => {
  const rnd = rngFor(seedOf(spec.terrain));
  const d = depths(palette);
  const rows = [
    { base: FAR_BASE - 26, scale: 0.85, color: d.far, step: 84 },
    { base: FAR_BASE, scale: 1.3, color: d.mid, step: 118 },
  ];
  return (
    <FarBox>
      {rows.map((row, ri) => (
        <g key={ri}>
          {Array.from({ length: Math.ceil(1920 / row.step) + 2 }, (_, i) => {
            const x = i * row.step + (rnd() - 0.5) * row.step * 0.5;
            const h = (86 + rnd() * 70) * row.scale;
            const w = (24 + rnd() * 12) * row.scale;
            return (
              <g key={i}>
                <path d={pine(x, row.base, w, h)} fill={row.color} />
                {/* Kar yalnızca üst üçte bire biner. Ağacın tamamını
                    kaplamak koyu gövdeyi yok ediyor ve çamlar beyaz
                    dikenlere dönüşüyordu. */}
                {snowy ? (
                  <path
                    d={pine(x, row.base - h * 0.62, w * 0.36, h * 0.3)}
                    fill={mix("#e8eef2", palette.skyBottom, ri === 0 ? 0.4 : 0.1)}
                  />
                ) : null}
              </g>
            );
          })}
        </g>
      ))}
    </FarBox>
  );
};

const Bamboo: React.FC<LayerProps> = ({ palette, spec }) => {
  const rnd = rngFor(seedOf(spec.terrain));
  const d = depths(palette);
  return (
    <FarBox>
      {Array.from({ length: 40 }, (_, i) => {
        const x = i * 50 + (rnd() - 0.5) * 28;
        const back = rnd() < 0.45;
        const top = -20 + rnd() * 60;
        const w = (11 + rnd() * 8) * (back ? 0.75 : 1);
        const lean = (rnd() - 0.5) * 16;
        const color = back ? d.far : d.mid;
        return (
          <g key={i}>
            <path
              d={`M ${x} ${FAR_BASE + 6} L ${x + lean} ${top} L ${x + lean + w} ${top} L ${x + w} ${FAR_BASE + 6} Z`}
              fill={color}
            />
            {/* Boğumlar — bambuyu ağaçtan ayıran asıl detay */}
            {[0.3, 0.52, 0.74].map((t, k) => (
              <rect
                key={k}
                x={x + lean * (1 - t) - 3}
                y={top + (FAR_BASE - top) * t}
                width={w + 6}
                height={4}
                fill={mix(color, palette.skyTop, 0.4)}
              />
            ))}
          </g>
        );
      })}
    </FarBox>
  );
};

const Orchard: React.FC<LayerProps> = ({ palette, spec }) => {
  const rnd = rngFor(seedOf(spec.terrain));
  const d = depths(palette);
  return (
    <FarBox>
      {[
        { base: FAR_BASE - 30, scale: 0.75, color: d.far, step: 150 },
        { base: FAR_BASE + 4, scale: 1.15, color: d.mid, step: 230 },
      ].map((row, ri) => (
        <g key={ri}>
          {Array.from({ length: Math.ceil(1920 / row.step) + 1 }, (_, i) => {
            const x = i * row.step + 60;
            const r = (46 + rnd() * 16) * row.scale;
            const trunk = 40 * row.scale;
            return (
              <g key={i}>
                <rect
                  x={x - 7 * row.scale}
                  y={row.base - trunk}
                  width={14 * row.scale}
                  height={trunk + 8}
                  fill={row.color}
                />
                <ellipse
                  cx={x}
                  cy={row.base - trunk - r * 0.66}
                  rx={r}
                  ry={r * 0.84}
                  fill={row.color}
                />
                {/* Meyveler — aksan rengiyle, çok küçük */}
                {ri === 1
                  ? Array.from({ length: 3 }, (_, k) => (
                      <circle
                        key={k}
                        cx={x + (rnd() - 0.5) * r * 1.1}
                        cy={row.base - trunk - r * 0.66 + (rnd() - 0.5) * r}
                        r={4}
                        fill={palette.accent}
                        opacity={0.55}
                      />
                    ))
                  : null}
              </g>
            );
          })}
        </g>
      ))}
    </FarBox>
  );
};

const Hills: React.FC<LayerProps> = ({ palette, spec }) => {
  const d = depths(palette);
  return (
    <FarBox>
      <path d={hill(96, 44, 1.1)} fill={d.far} />
      <path d={hill(158, 34, 0.6)} fill={mix(d.far, d.mid, 0.5)} />
      <path d={hill(FAR_BASE - 6, 24, 1.4)} fill={d.mid} />
      {spec.terrain === "hill"
        ? [0, 1, 2].map((i) => (
            <rect
              key={i}
              y={120 + i * 44}
              width={1920}
              height={20}
              fill={palette.ink}
              opacity={0.1}
              rx={10}
            />
          ))
        : null}
    </FarBox>
  );
};

const Lake: React.FC<LayerProps> = ({ palette }) => {
  const d = depths(palette);
  // Su gökyüzünden AÇIK olmalı, koyu değil. Koyulaştırmak denendi ve işe
  // yaramadı: gökyüzü ufka doğru zaten koyu, iki koyu ton birbirine karışıyor.
  // Ay ışığındaki su gerçekte gümüşi bir şerit olarak okunur.
  const water = mix(palette.skyBottom, palette.accent, 0.32);
  return (
    <FarBox>
      {/* Karşı kıyı — düz ve uzak, gölün genişliğini o veriyor. Yüksekte
          tutuluyor: alçak bir kıyı, suyu ufukta 80px'lik bir şeride
          sıkıştırıyor ve göl karakterlerin arkasında kayboluyordu. */}
      <path d={hill(62, 12, 0.4)} fill={d.far} />
      <rect y={74} width={1920} height={FAR_BASE - 68} fill={water} />
      {/* Ufuk çizgisi — suyu gökyüzünden ayıran şey bu ince şerit */}
      <rect y={72} width={1920} height={4} fill={palette.accent} opacity={0.4} />
      {/* Ay yansıması — sağ üstteki ay ile aynı x'te */}
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect
          key={i}
          x={1512 + (i % 2) * 22}
          y={92 + i * 22}
          width={110 - i * 12}
          height={6}
          rx={3}
          fill={palette.accent}
          opacity={0.32 - i * 0.045}
        />
      ))}
      <path d={hill(FAR_BASE + 2, 10, 0.9)} fill={d.mid} />
    </FarBox>
  );
};

const Shore: React.FC<LayerProps> = ({ palette }) => {
  const d = depths(palette);
  // Bkz. Lake: su gökyüzünden açık olmalı.
  const sea = mix(palette.skyBottom, palette.accent, 0.34);
  return (
    <FarBox>
      {/* Deniz ufku — dümdüz, kumsalın imzası. Bkz. Lake: bant yüksek
          tutulmazsa deniz ufukta bir çizgiye iniyor. */}
      <rect y={52} width={1920} height={158} fill={sea} />
      <rect y={50} width={1920} height={4} fill={palette.accent} opacity={0.45} />
      {[0, 1, 2, 3].map((i) => (
        <path
          key={i}
          d={`M 0 ${92 + i * 30} Q 480 ${84 + i * 30}, 960 ${92 + i * 30} T 1920 ${92 + i * 30}`}
          stroke={palette.accent}
          strokeWidth={3}
          fill="none"
          opacity={0.3 - i * 0.08}
        />
      ))}
      {/* Kumul */}
      <path d={hill(FAR_BASE - 4, 26, 0.8)} fill={mix(d.mid, palette.accent, 0.22)} />
    </FarBox>
  );
};

const Stream: React.FC<LayerProps> = ({ palette, spec }) => {
  const rnd = rngFor(seedOf(spec.terrain));
  const d = depths(palette);
  return (
    <FarBox>
      {/* Yosunlu yamaçlar — Fen'in evi, markanın varsayılan mekânı */}
      <path d={hill(120, 32, 0.9)} fill={d.far} />
      <path d={hill(FAR_BASE - 8, 20, 1.3)} fill={d.mid} />
      {/* Sazlar */}
      {Array.from({ length: 30 }, (_, i) => {
        const x = i * 66 + rnd() * 36;
        const h = 44 + rnd() * 52;
        return (
          <line
            key={i}
            x1={x}
            y1={FAR_BASE + 8}
            x2={x + (rnd() - 0.5) * 18}
            y2={FAR_BASE + 8 - h}
            stroke={d.near}
            strokeWidth={5}
            strokeLinecap="round"
          />
        );
      })}
    </FarBox>
  );
};

const Clearing: React.FC<LayerProps> = ({ palette, spec }) => {
  const rnd = rngFor(seedOf(spec.terrain));
  const d = depths(palette);
  return (
    <FarBox>
      {/* Açıklığın tanımı: ağaç hattı UZAKTA ve alçak — gökyüzü açık kalır */}
      {Array.from({ length: 30 }, (_, i) => {
        const x = i * 66 + rnd() * 30;
        return (
          <ellipse
            key={i}
            cx={x}
            cy={FAR_BASE - 4}
            rx={34 + rnd() * 28}
            ry={20 + rnd() * 16}
            fill={i % 3 === 0 ? d.far : d.mid}
          />
        );
      })}
    </FarBox>
  );
};

const Meadow: React.FC<LayerProps> = ({ palette }) => {
  const d = depths(palette);
  return (
    <FarBox>
      <path d={hill(150, 20, 0.7)} fill={d.far} />
      <path d={hill(FAR_BASE - 2, 16, 1.2)} fill={d.mid} />
    </FarBox>
  );
};

/**
 * Kovuk diğerlerinden farklı: uzak siluet değil, sahneyi ÇERÇEVELEYEN bir
 * gövde. Karakterlerin önünde durmaz ama kadrajı iki yandan daraltır —
 * "içeride olma" hissini veren şey bu.
 */
const HollowFrame: React.FC<LayerProps> = ({ palette }) => {
  const wood = mix(palette.ground, "#000000", 0.35);
  return (
    <AbsoluteFill>
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" preserveAspectRatio="none">
        <path
          d="M 0 0 L 1920 0 L 1920 1080 L 1660 1080
             C 1690 700, 1570 400, 1250 282
             C 1085 222, 835 222, 670 282
             C 350 400, 230 700, 260 1080
             L 0 1080 Z"
          fill={wood}
        />
        {/* Odun dokusu — birkaç düşük kontrastlı damar */}
        {[0, 1, 2, 3].map((i) => (
          <path
            key={i}
            d={`M ${120 + i * 40} 1080 C ${150 + i * 40} 760, ${205 + i * 36} 560, ${310 + i * 32} 392`}
            stroke="#00000030"
            strokeWidth={7}
            fill="none"
          />
        ))}
        {[0, 1, 2, 3].map((i) => (
          <path
            key={`r${i}`}
            d={`M ${1800 - i * 40} 1080 C ${1770 - i * 40} 760, ${1715 - i * 36} 560, ${1610 - i * 32} 392`}
            stroke="#00000030"
            strokeWidth={7}
            fill="none"
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};

// --------------------------------------------------------------------------
// Yakın katman ve atmosfer
// --------------------------------------------------------------------------

const NearDetail: React.FC<LayerProps> = ({ palette, spec }) => {
  const rnd = rngFor(seedOf(spec.terrain) ^ 0x5bf03635);
  const d = depths(palette);
  const { terrain } = spec;

  if (terrain === "valley" || terrain === "meadow") {
    return (
      <NearBox>
        {Array.from({ length: 70 }, (_, i) => {
          const x = rnd() * 1920;
          const y = 20 + rnd() * 220;
          const tip = y - 18 - rnd() * 16;
          return (
            <g key={i}>
              <line
                x1={x}
                y1={y}
                x2={x + (rnd() - 0.5) * 12}
                y2={tip}
                stroke={mix(d.near, palette.ink, 0.18)}
                strokeWidth={3}
                strokeLinecap="round"
                opacity={0.55}
              />
              {terrain === "valley" ? (
                <circle cx={x} cy={tip - 3} r={4} fill={palette.accent} opacity={0.6} />
              ) : null}
            </g>
          );
        })}
      </NearBox>
    );
  }

  if (terrain === "snow") {
    return (
      <NearBox>
        <path
          d="M 0 40 Q 480 12, 960 34 T 1920 26 L 1920 300 L 0 300 Z"
          fill="#dfe8ee"
          opacity={0.3}
        />
      </NearBox>
    );
  }

  if (terrain === "shore") {
    return (
      <NearBox>
        {Array.from({ length: 30 }, (_, i) => (
          <ellipse
            key={i}
            cx={rnd() * 1920}
            cy={30 + rnd() * 220}
            rx={6 + rnd() * 10}
            ry={4 + rnd() * 6}
            fill={palette.ink}
            opacity={0.14}
          />
        ))}
      </NearBox>
    );
  }

  if (terrain === "stream" || terrain === "lake") {
    return (
      <NearBox>
        {Array.from({ length: 10 }, (_, i) => (
          <ellipse
            key={i}
            cx={rnd() * 1920}
            cy={16 + rnd() * 54}
            rx={18 + rnd() * 28}
            ry={10 + rnd() * 12}
            fill={mix(d.near, palette.ink, 0.12)}
            opacity={0.6}
          />
        ))}
      </NearBox>
    );
  }

  return null;
};

/**
 * Sis. CSS gradyanı kullanılıyor, SVG dikdörtgeni değil: keskin kenarlı
 * bantlar sisten çok jaluzi gibi duruyordu. Gaussian blur filtresi daha iyi
 * olurdu ama kare başına maliyeti bu CPU'da render süresini ölçülebilir
 * şekilde uzatıyor.
 */
const Fog: React.FC<{ color: string; density: number }> = ({ color, density }) => {
  if (density <= 0.02) return null;
  const a = (x: number) =>
    Math.round(Math.min(255, x * density * 255))
      .toString(16)
      .padStart(2, "0");
  return (
    <AbsoluteFill
      style={{
        top: `${HORIZON_PCT - 8}%`,
        height: `${GROUND_TOP_PCT - HORIZON_PCT + 12}%`,
        background:
          `linear-gradient(to bottom, transparent 0%, ${color}${a(0.16)} 28%, ` +
          `${color}${a(0.3)} 56%, ${color}${a(0.12)} 82%, transparent 100%)`,
      }}
    />
  );
};

// --------------------------------------------------------------------------
// Giriş noktası
// --------------------------------------------------------------------------

const FAR_LAYERS: Record<Terrain, React.FC<LayerProps>> = {
  conifer: (p) => <Conifer {...p} />,
  snow: (p) => <Conifer {...p} snowy />,
  bamboo: Bamboo,
  orchard: Orchard,
  valley: Hills,
  hill: Hills,
  lake: Lake,
  shore: Shore,
  stream: Stream,
  clearing: Clearing,
  meadow: Meadow,
  // Kovuk uzak siluet olarak dereyi kullanır; ayırt edici olan çerçevesi.
  hollow: Stream,
};

/** Zeminin ARKASINDA duran mekân katmanı. */
export const BackdropFar: React.FC<LayerProps> = (props) => {
  const Layer = FAR_LAYERS[props.spec.terrain];
  return (
    <>
      <Layer {...props} />
      <Fog color={props.palette.ink} density={props.spec.fog} />
    </>
  );
};

/** Zeminin ÖNÜNDE, karakterlerin arkasında duran katman. */
export const BackdropNear: React.FC<LayerProps> = (props) => <NearDetail {...props} />;

/** Kadrajı çerçeveleyen katman — yalnızca kovuk kullanıyor. */
export const BackdropFrame: React.FC<LayerProps> = (props) =>
  props.spec.terrain === "hollow" ? <HollowFrame {...props} /> : null;
