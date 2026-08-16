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
