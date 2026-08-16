/**
 * `bg/<mekân>/<varyant>` kimliğini araziye ve atmosfere çevirir.
 *
 * Bu dosya olmadan önce `SceneView` arka plan kimliğini hiç okumuyordu: sahne
 * ister karlı çam ormanında ister kumsalda geçsin aynı ağaç hattı ve aynı dere
 * çiziliyordu. Varyasyon kapısının görsel ekseni tam da bu kimlikleri
 * karşılaştırdığı için kapı, ekranda var olmayan bir çeşitliliği ölçüyordu.
 *
 * Anahtarlar `core/storyboard.py::_slug` çıktısıyla eşleşir (Türkçe → ASCII).
 * Bir mekân havuza eklenip buraya eklenmezse `tests/test_backgrounds.py`
 * bunu yakalar — sessizce varsayılana düşmek, tam olarak düzeltmeye
 * çalıştığımız hatanın kendisi olurdu.
 */

export type Terrain =
  | "conifer"
  | "snow"
  | "lake"
  | "stream"
  | "orchard"
  | "valley"
  | "hill"
  | "shore"
  | "clearing"
  | "hollow"
  | "bamboo"
  | "meadow";

/** Kimlikteki varyant — ruh halinden türüyor, atmosferi modüle eder. */
export type Variant = "soft" | "bright" | "golden" | "hazy" | "dusk";

export const VARIANTS: readonly Variant[] = [
  "soft",
  "bright",
  "golden",
  "hazy",
  "dusk",
];

/**
 * SIRA ÖNEMLİ. `kar_altinda_cam_ormani` hem "kar" hem "orman" içeriyor;
 * karlı orman, sıradan ormandan önce eşleşmeli. Aynı şekilde
 * `yosunlu_dere_yatagi` "dere" ile eşleşmeli, `ay_isiginda_gol_kiyisi` "gol"
 * ile — ikisi de su ama görsel olarak ayrı.
 */
export const TERRAIN_KEYWORDS: ReadonlyArray<readonly [Terrain, readonly string[]]> = [
  ["snow", ["kar_altinda", "kar"]],
  ["bamboo", ["bambu"]],
  ["hollow", ["kovug", "kovuk", "agacin"]],
  ["orchard", ["bahce", "meyve"]],
  ["shore", ["sahil", "kumsal"]],
  ["lake", ["gol"]],
  ["stream", ["dere"]],
  ["hill", ["tepe"]],
  ["valley", ["vadi"]],
  ["clearing", ["aciklik", "yildizlarin"]],
  ["meadow", ["cayir"]],
  ["conifer", ["orman"]],
];

/** Suyu olan araziler. Dere Fen'in evi, ama her mekânda su yok. */
const WATERY: ReadonlySet<Terrain> = new Set<Terrain>(["stream", "lake", "shore"]);

/** Ağaç hattı taşımayan araziler — açık gökyüzü onların karakteri. */
const OPEN_SKY: ReadonlySet<Terrain> = new Set<Terrain>([
  "clearing",
  "meadow",
  "shore",
  "hill",
]);

export type Backdrop = {
  terrain: Terrain;
  variant: Variant;
  hasWater: boolean;
  openSky: boolean;
  /** Sis yoğunluğu 0..1 — `hazy` varyantı ve tepe arazisi arttırır. */
  fog: number;
  /** Yıldız görünürlüğü 0..1 — açık gökyüzünde ve `dusk`ta yüksek. */
  starVisibility: number;
};

export function terrainOf(assetId: string): Terrain {
  const slug = assetId.split("/")[1] ?? "";
  for (const [terrain, keys] of TERRAIN_KEYWORDS) {
    if (keys.some((k) => slug.includes(k))) return terrain;
  }
  // Fen'in evi varsayılan: bilinmeyen bir mekân markanın dışına düşmemeli.
  return "stream";
}

export function variantOf(assetId: string): Variant {
  const raw = assetId.split("/")[2] ?? "";
  return (VARIANTS as readonly string[]).includes(raw) ? (raw as Variant) : "soft";
}

export function backdropOf(assetId: string): Backdrop {
  const terrain = terrainOf(assetId);
  const variant = variantOf(assetId);

  const fog =
    (variant === "hazy" ? 0.55 : variant === "soft" ? 0.18 : 0.08) +
    (terrain === "hill" ? 0.3 : 0) +
    (terrain === "snow" ? 0.15 : 0);

  const starVisibility =
    (variant === "dusk" ? 1 : variant === "bright" ? 0.35 : 0.7) *
    (OPEN_SKY.has(terrain) ? 1 : 0.65) *
    (1 - Math.min(0.7, fog));

  return {
    terrain,
    variant,
    hasWater: WATERY.has(terrain),
    openSky: OPEN_SKY.has(terrain),
    fog: Math.min(1, fog),
    starVisibility: Math.max(0, Math.min(1, starVisibility)),
  };
}
