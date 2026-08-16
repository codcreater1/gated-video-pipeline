"""Seslendirme aşaması — storyboard'a gerçek ses ve gerçek süre yazar.

Senaryo aşamasındaki `duration_seconds` bir TAHMİN. Ses üretilene kadar bir
sahnenin gerçekte kaç saniye süreceği bilinmiyor. Bu süreleri güncellemezsek
görüntü ve ses birbirinden kayar — 10 dakikalık bir bölümde birikerek
dakikalarca fark eder.

Bu yüzden burada storyboard **yeniden yazılır**: her sahnenin süresi sentezlenen
sesin gerçek uzunluğu + nefes payı olur.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import config, db, voice

# Sahne başı nefes payı. Anlatım bitince sahne hemen kesilmemeli — bedtime
# temposunda sessizlik, anlatımın kendisi kadar önemli.
LEAD_IN_SECONDS = 1.2
LEAD_OUT_SECONDS = 2.0

# Anlatımı olmayan sahne (varsa) bu kadar sürer.
SILENT_SCENE_SECONDS = 8.0


@dataclass
class NarrationResult:
    storyboard: dict[str, Any]
    audio_dir: Path
    voice_id: str
    total_seconds: float
    scene_count: int


def audio_dir_for(job_id: int) -> Path:
    return config.CACHE_DIR / "tts" / f"job_{job_id}"


def recent_voice_ids(channel: str, limit: int = 12) -> list[str]:
    """En yeniden en eskiye ses geçmişi — `voice.pick_voice` bunu kullanır."""
    return [
        fp["voice_id"]
        for fp in db.recent_fingerprints(channel, limit=limit)
        if fp.get("voice_id")
    ]


def narrate(
    job_id: int,
    storyboard: dict[str, Any],
    channel: config.Channel,
    voice_id: str | None = None,
) -> NarrationResult:
    """Her sahneyi seslendirir, süreleri gerçek değerle günceller.

    Ses dosyaları `<veri kökü>/cache/tts/job_<id>/scene_<i>.wav` altına yazılır;
    Remotion bu klasörü `--public-dir` olarak alır ve `staticFile()` ile okur.
    Bu yüzden `audioSrc` mutlak yol değil, dosya adıdır.
    """
    profile = config.CHANNELS[channel]
    chosen = voice_id or voice.pick_voice(channel, recent_voice_ids(channel.value))

    out_dir = audio_dir_for(job_id)
    # Yeniden üretimde eski dosyalar kalmamalı — sahne sayısı azalırsa
    # artakalan wav'lar sessizce yanlış bölüme karışırdı.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes: list[dict[str, Any]] = []
    total = 0.0

    for scene in storyboard.get("scenes", []):
        text = (scene.get("narration") or "").strip()
        updated = dict(scene)

        if not text:
            updated["audioSrc"] = None
            updated["duration_seconds"] = int(SILENT_SCENE_SECONDS)
            total += SILENT_SCENE_SECONDS
            scenes.append(updated)
            continue

        filename = f"scene_{scene['index']}.wav"
        result = voice.synthesize(
            text=text,
            voice_id=chosen,
            speech_rate=profile.speech_rate,
            out_path=out_dir / filename,
        )

        duration = LEAD_IN_SECONDS + result.duration_seconds + LEAD_OUT_SECONDS
        updated["audioSrc"] = filename
        updated["duration_seconds"] = max(1, round(duration))
        # Remotion sesi sahnenin başında değil, nefes payından sonra başlatır.
        updated["audioDelaySeconds"] = LEAD_IN_SECONDS
        total += duration
        scenes.append(updated)

    board = dict(storyboard)
    board["scenes"] = scenes

    return NarrationResult(
        storyboard=board,
        audio_dir=out_dir,
        voice_id=chosen,
        total_seconds=total,
        scene_count=len(scenes),
    )


def cleanup(job_id: int) -> None:
    """Yayınlanan veya kalıcı reddedilen işin ses ara dosyalarını siler."""
    d = audio_dir_for(job_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
