import type { Mood } from "./schema";

/**
 * Renk paleti — ruh haline göre.
 *
 * 2026'da hızlı büyüyen bedtime nişinin ortak görsel dili: yumuşak tempo, sıcak
 * renk paleti, düşük kontrast. Yüksek doygunluk ve sert kontrast uyanıklık
 * sinyali verdiği için bilinçli olarak kaçınılıyor.
 *
 * Bölüm sonuna doğru palet `resolved`a kayar ve belirgin şekilde koyulaşır —
 * izleyiciyi uykuya bırakan asıl mekanizma bu, anlatı değil.
 */

export type Palette = {
  skyTop: string;
  skyBottom: string;
  ground: string;
  accent: string;
  /** Anlatım altyazısı ve başlık için — arka planla kontrastı düşük tutulur. */
  ink: string;
};

export const PALETTES: Record<Mood, Palette> = {
  curious: {
    skyTop: "#2b3a67",
    skyBottom: "#5c7a9e",
    ground: "#3d5a52",
    accent: "#e8c07d",
    ink: "#f2e9dc",
  },
  calm: {
    skyTop: "#1f2b4d",
    skyBottom: "#42597d",
    ground: "#2f4a45",
    accent: "#d8b78a",
    ink: "#ece3d6",
  },
  warm: {
    skyTop: "#3a2f4d",
    skyBottom: "#7a5f72",
    ground: "#4a3d44",
    accent: "#f0b98d",
    ink: "#f5ebe0",
  },
  gentle: {
    skyTop: "#1a2740",
    skyBottom: "#36506b",
    ground: "#28403c",
    accent: "#c9b7a0",
    ink: "#e6ddd2",
  },
  resolved: {
    skyTop: "#0f1626",
    skyBottom: "#233247",
    ground: "#1b2b2a",
    accent: "#9fb0a8",
    ink: "#cfc9c0",
  },
};

export function paletteFor(mood: Mood): Palette {
  return PALETTES[mood] ?? PALETTES.calm;
}

/**
 * İki rengi karıştırır. `t=0` → a, `t=1` → b.
 *
 * Hava perspektifi için: uzak katmanlar gökyüzü rengine doğru açılır. Bu
 * olmadan arazi siluetleri zeminle aynı rengi paylaşıyor ve görünmez oluyordu
 * — karlı ormanda ekranda kalan tek şey kar başlıklarıydı.
 */
export function mix(a: string, b: string, t: number): string {
  const parse = (hex: string): [number, number, number] => {
    const h = hex.replace("#", "");
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  };
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  const k = Math.max(0, Math.min(1, t));
  const to = (x: number, y: number) =>
    Math.round(x + (y - x) * k)
      .toString(16)
      .padStart(2, "0");
  return `#${to(r1, r2)}${to(g1, g2)}${to(b1, b2)}`;
}
