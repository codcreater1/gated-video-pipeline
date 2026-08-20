import { z } from "zod";

/**
 * Bu şema `core/storyboard.py` çıktısının aynadaki karşılığıdır.
 * Python tarafı değişirse burası da değişmeli — uyumsuzluk render anında
 * değil, Remotion Studio'da hemen görünür.
 */

export const moodSchema = z.enum(["calm", "curious", "warm", "gentle", "resolved"]);
export type Mood = z.infer<typeof moodSchema>;

export const transitionSchema = z.enum(["fade", "cut", "dissolve", "wipe"]);
export type Transition = z.infer<typeof transitionSchema>;

export const sceneSchema = z.object({
  index: z.number().int(),
  narration: z.string(),
  setting: z.string(),
  action: z.string(),
  mood: moodSchema,
  duration_seconds: z.number().positive(),
  transition: transitionSchema,
  assets: z.object({
    background: z.string(),
    /** Kahraman (Fen) — her bölümde aynı. */
    character: z.string(),
    /** Bu bölümün misafiri — her bölümde değişir. */
    companion: z.string().nullable().default(null),
  }),
  /**
   * Bu sahnenin seslendirme dosyası — `--public-dir` içindeki DOSYA ADI,
   * mutlak yol değil. `core/narration.py` bu klasörü yazar.
   * Yoksa sahne sessiz render edilir.
   */
  audioSrc: z.string().nullable().default(null),
  /** Anlatım sahnenin başında değil, bu kadar saniye sonra başlar (nefes payı). */
  audioDelaySeconds: z.number().min(0).default(0),
});
export type Scene = z.infer<typeof sceneSchema>;

export const premiseSchema = z.object({
  channel: z.string(),
  protagonist: z.string().default("Fen"),
  topic: z.string(),
  setting: z.string(),
  character: z.string(),
  shape: z.string(),
  beats: z.array(z.string()),
  combo_key: z.string(),
});

export const episodeSchema = z.object({
  premise: premiseSchema,
  title: z.string(),
  description: z.string(),
  scenes: z.array(sceneSchema).min(1),
  /** Arka plan müziği — bölüm boyunca döner, anlatımın altında kalır. */
  musicSrc: z.string().nullable().default(null),
});
export type Episode = z.infer<typeof episodeSchema>;

/** Remotion Studio'da şablonu boş açmamak için kullanılan örnek veri. */
export const sampleEpisode: Episode = {
  premise: {
    channel: "bedtime",
    protagonist: "Fen",
    topic: "kaybolan bir şeyi geri götürmek",
    setting: "yosunlu dere yatağı",
    character: "uzun bacaklı balıkçıl",
    shape: "arayış",
    beats: ["kayıp fark edilir", "iz sürülür", "bulunur", "geri dönülür"],
    combo_key: "sample0000000000",
  },
  title: "Fen and the Lost Feather",
  description: "A gentle bedtime story about returning what was lost.",
  musicSrc: null,
  scenes: [
    {
      index: 0,
      narration: "Fen found a long grey feather resting on a wet stone.",
      setting: "mossy stream",
      action: "looks at the feather",
      mood: "curious",
      duration_seconds: 52,
      transition: "fade",
      assets: {
        background: "bg/mossy_stream/bright",
        character: "char/su_samuru/looking",
        companion: null,
      },
      audioSrc: null,
      audioDelaySeconds: 0,
    },
    {
      index: 1,
      narration: "It was not Fen's feather. Somewhere, a bird was missing it.",
      setting: "mossy stream",
      action: "carries the feather",
      mood: "calm",
      duration_seconds: 68,
      transition: "dissolve",
      assets: {
        background: "bg/mossy_stream/soft",
        character: "char/su_samuru/carrying",
        companion: null,
      },
      audioSrc: null,
      audioDelaySeconds: 0,
    },
    {
      index: 2,
      narration: "Fen followed the water until a tall bird stood in the shallows.",
      setting: "reed bank",
      action: "walks along the water",
      mood: "gentle",
      duration_seconds: 74,
      transition: "cut",
      assets: {
        background: "bg/reed_bank/hazy",
        character: "char/su_samuru/walking",
        companion: "char/uzun_bacakli_balikcil/standing",
      },
      audioSrc: null,
      audioDelaySeconds: 0,
    },
    {
      index: 3,
      narration: "The heron tucked the feather back into her wing. The stream went quiet again.",
      setting: "reed bank",
      action: "rests on a stone",
      mood: "resolved",
      duration_seconds: 61,
      transition: "fade",
      assets: {
        background: "bg/reed_bank/dusk",
        character: "char/su_samuru/resting",
        companion: "char/uzun_bacakli_balikcil/resting",
      },
      audioSrc: null,
      audioDelaySeconds: 0,
    },
  ],
};

/**
 * Remotion Studio'da Short şablonunu boş açmamak için örnek veri.
 *
 * Yapısı bilerek `sampleEpisode` ile aynı: bir Short, ayrı bir içerik türü
 * değil, bir bölümden kesilmiş tek sahnedir (bkz. `core/shorts.py`).
 */
export const sampleShort: Episode = {
  ...sampleEpisode,
  title: "Fen and the Lost Feather",
  scenes: [
    {
      ...sampleEpisode.scenes[0]!,
      narration: "Fen found a long grey feather resting on a wet stone.",
      duration_seconds: 34,
    },
  ],
};
