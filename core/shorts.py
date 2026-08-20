"""SHORTS — yayınlanmış bir bölümden türetilen dikey klip.

Neden bu format ayrıca önemli: `docs/content-guidelines.md §1`, Made for Kids
işaretli bir kanalda Super Thanks'in, üyeliklerin, end screen'in ve yorumların
kapandığını yazıyor. Açık kalan tek native para kazanma yolu **Shorts gelir
paylaşımı**. Yani kanalın gerçekten para kazandığı format bu.

Short SIFIRDAN ÜRETİLMEZ. Yayınlanmış bir bölüm seçilir, o bölümün bir
sahnesinin anlatımı Shorts uzunluğuna kısaltılır ve dikey kadrajda yeniden
render edilir. Sonuç:

- LLM maliyeti **$0** — yeni senaryo yazılmıyor.
- TTS maliyeti **$0** — Kokoro yerel çalışıyor (bkz. docs/benchmarks.md).
- Render maliyeti ~1 dakika — 20-59 saniyelik tek sahne.

Yeni bir fikir üretmek yerine türetmek, varyasyon açısından da doğru: Short'un
çeşitliliği kaynak bölümlerin çeşitliliğinden geliyor ve o zaten kapıdan
geçmiş durumda.

**Varyasyon kapısı format şeridinde çalışır** (bkz. `variation_guard.evaluate`).
Bir Short'u kaynak bölümüyle karşılaştırmak tanım gereği "çok benzer" verirdi —
metni ondan türüyor. Short'lar Short'larla yarışır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core import config, db, narration, render, storyboard, voice

# Kısaltılmış anlatımın hedef uzunluğu. Format sınırları [20, 59] saniye;
# hedef ortada tutuluyor çünkü nefes payları (LEAD_IN + LEAD_OUT ≈ 3.2 sn)
# ve tahmin hatası üstüne biniyor.
TARGET_NARRATION_SECONDS = 32.0

# Kaynak bölümün hangi sahnesi alınır. 0 kasıtlı: senaryonun açılış beat'i
# zaten kancadır, ortadan bir sahne almak bağlamsız kalır.
DEFAULT_SCENE_INDEX = 0


class ShortError(Exception):
    """Short üretilemedi."""


@dataclass
class ShortPlan:
    parent_job_id: int
    scene_index: int
    title: str
    narration_text: str
    estimated_seconds: float
    storyboard: dict[str, Any]


def _trim_to_fit(text: str, speech_rate: float, target: float) -> str:
    """Anlatımı cümle sınırında keser.

    Karakter sayısıyla kesmek cümle ortasında bırakıyor ve seslendirme yarım
    bir cümleyle bitiyordu. En az bir cümle her zaman döner — hedefi aşsa bile,
    çünkü cümlesiz bir Short üretmek daha kötü.
    """
    sentences = voice._split_sentences(text)
    if not sentences:
        raise ShortError("Kaynak sahnenin anlatımı boş.")

    kept: list[str] = []
    for sentence in sentences:
        candidate = kept + [sentence]
        if kept and voice.estimate_duration(" ".join(candidate), speech_rate) > target:
            break
        kept.append(sentence)
    return " ".join(kept)


def plan(
    parent_job_id: int,
    scene_index: int = DEFAULT_SCENE_INDEX,
    target_seconds: float = TARGET_NARRATION_SECONDS,
) -> ShortPlan:
    """Kaynak bölümden Short planı çıkarır. Hiçbir şey üretmez, hiçbir şey yazmaz."""
    parent = db.get_job(parent_job_id)
    if parent is None:
        raise ShortError(f"Kaynak bölüm bulunamadı: {parent_job_id}")
    if parent["format"] != "episode":
        raise ShortError(
            f"Short yalnızca bölümden türetilir; iş #{parent_job_id} formatı "
            f"{parent['format']!r}."
        )
    if parent["status"] != db.JobStatus.PUBLISHED.value:
        raise ShortError(
            f"İş #{parent_job_id} yayınlanmamış (durum: {parent['status']}). "
            f"Yayınlanmamış bir bölümden Short türetmek, onay kapısından "
            f"geçmemiş içeriği kanala sokmak olurdu."
        )

    board = json.loads(parent["storyboard_json"] or "{}")
    scenes = board.get("scenes", [])
    if not 0 <= scene_index < len(scenes):
        raise ShortError(
            f"Sahne {scene_index} yok — bölümde {len(scenes)} sahne var."
        )

    channel = config.Channel(parent["channel"])
    profile = config.CHANNELS[channel]
    scene = dict(scenes[scene_index])

    text = _trim_to_fit(scene.get("narration") or "", profile.speech_rate, target_seconds)
    estimated = voice.estimate_duration(text, profile.speech_rate)

    # Sahne yeni bölümün TEK sahnesi olduğu için index sıfırlanır; aksi halde
    # narration ses dosyalarını `scene_<index>.wav` olarak yanlış adlandırır.
    scene["index"] = 0
    scene["narration"] = text
    scene["transition"] = "fade"

    short_board = {
        "premise": board.get("premise", {}),
        "title": parent["title"] or "",
        "description": board.get("description", ""),
        "scenes": [scene],
        "short_of": parent_job_id,
    }

    return ShortPlan(
        parent_job_id=parent_job_id,
        scene_index=scene_index,
        title=parent["title"] or "",
        narration_text=text,
        estimated_seconds=estimated,
        storyboard=short_board,
    )


def duration_within_format(seconds: float, channel: config.Channel) -> bool:
    fmt = config.CHANNELS[channel].formats["short"]
    return fmt.min_seconds <= seconds <= fmt.max_seconds


def create(
    parent_job_id: int,
    scene_index: int = DEFAULT_SCENE_INDEX,
    narrator=None,
    renderer=None,
) -> tuple[int, ShortPlan]:
    """Short işini kurar, seslendirir ve render eder.

    Onay kuyruğuna BIRAKMAZ — bunu `pipeline` tarafındaki çağıran yapar, tıpkı
    bölümlerde olduğu gibi. Burada üretim var, karar yok.
    """
    p = plan(parent_job_id, scene_index=scene_index)
    parent = db.get_job(parent_job_id)
    assert parent is not None  # plan() zaten doğruladı
    channel = config.Channel(parent["channel"])

    job_id = db.create_job(
        parent["channel"], "short", topic=f"short of #{parent_job_id}"
    )
    db.update_job(
        job_id,
        status=db.JobStatus.GENERATING.value,
        title=p.title,
        script=p.narration_text,
        storyboard_json=storyboard.to_json(p.storyboard),
    )

    # Kaynak bölümün sesi kullanılır: Short ile bölüm aynı anlatıcıyla
    # eşleşmezse izleyici için iki ayrı kanal gibi duruyor.
    synth = narrator or narration.narrate
    result = synth(job_id, p.storyboard, channel, parent["voice_id"] or None)

    if not duration_within_format(result.total_seconds, channel):
        fmt = config.CHANNELS[channel].formats["short"]
        db.reject_job(
            job_id,
            f"SHORTS SÜRESİ: {result.total_seconds:.0f}sn, izinli aralık "
            f"{fmt.min_seconds}-{fmt.max_seconds}sn.",
        )
        raise ShortError(
            f"Short süresi aralık dışında: {result.total_seconds:.0f}sn "
            f"(izinli {fmt.min_seconds}-{fmt.max_seconds}sn). "
            f"Farklı bir sahne dene: --scene <n>"
        )

    db.update_job(
        job_id,
        storyboard_json=storyboard.to_json(result.storyboard),
        duration_seconds=int(result.total_seconds),
        voice_id=result.voice_id,
        status=db.JobStatus.RENDERING.value,
    )

    draw = renderer or _default_renderer
    output = draw(job_id, result.storyboard, narration.audio_dir_for(job_id))
    db.update_job(job_id, output_path=str(output))

    return job_id, p


def _default_renderer(job_id: int, board: dict[str, Any], audio_dir):
    return render.render_short(
        job_id=job_id, storyboard=board, audio_dir=audio_dir
    ).output_path
