import type { Episode, Scene, Transition } from "./schema";

export const FPS = 30;

/**
 * Geçiş süreleri. Bedtime içeriğinde geçişler kasıtlı olarak yavaş — sert kesme
 * uyku öncesi tempoyu bozar, o yüzden `cut` bile sıfır değil, çok kısa bir yumuşama.
 */
export const TRANSITION_FRAMES: Record<Transition, number> = {
  cut: 3,
  fade: 45,
  dissolve: 36,
  wipe: 30,
};

export type TimedScene = {
  scene: Scene;
  /** Bölüm başından itibaren bu sahnenin başladığı kare. */
  from: number;
  durationInFrames: number;
  transitionInFrames: number;
};

/**
 * Sahneler üst üste binmez — geçiş, sahnenin KENDİ süresi içinde çalışır.
 *
 * Bindirmeli geçiş daha zarif olurdu ama iki sahneyi aynı anda render etmek
 * demek; bu CPU'da kare başına maliyeti ikiye katlar. 10 dakikalık bir bölüm
 * 18.000 kare, ve her karenin iki kez çizilmesi render'ı saatlerce uzatır.
 */
export function layout(episode: Episode): TimedScene[] {
  let cursor = 0;
  return episode.scenes.map((scene) => {
    const durationInFrames = Math.max(1, Math.round(scene.duration_seconds * FPS));
    const transitionInFrames = Math.min(
      TRANSITION_FRAMES[scene.transition],
      Math.floor(durationInFrames / 2),
    );
    const timed: TimedScene = { scene, from: cursor, durationInFrames, transitionInFrames };
    cursor += durationInFrames;
    return timed;
  });
}

export function totalFrames(episode: Episode): number {
  return layout(episode).reduce((sum, t) => sum + t.durationInFrames, 0);
}

export function totalSeconds(episode: Episode): number {
  return totalFrames(episode) / FPS;
}
