"""Seslendirme — Kokoro ONNX.

Neden Kokoro ve neden ONNX:
- 82M parametre. GTX 1650'nin 4 GB VRAM'i Chatterbox gibi ~0.5B modellere yetmiyor.
- ONNX runtime ~300 MB; PyTorch+CUDA ~4 GB isterdi ve C:'de o yer yok.
- Anlatım/narration Kokoro'nun en güçlü olduğu alan — saatlerce artefaktsız okuyor.
- XTTS kullanılmıyor: Coqui 2024'te kapandı, model desteksiz.

Bedtime içeriği için tempo kasıtlı olarak yavaş (`speech_rate` 0.82).
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from core import config

MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)

# Varyasyon kapısının ses ekseni bu havuzdan seçim yapar.
# Aynı ses arka arkaya VARIATION_MAX_VOICE_STREAK'ten fazla kullanılamaz.
BEDTIME_VOICES = ["af_bella", "af_nicole", "af_sarah", "bf_emma"]
# Kanal B pasif; açıldığında bu havuz kullanılır.
STORYTIME_VOICES = ["am_michael", "af_heart", "bm_george", "af_sky"]


class ModelMissing(Exception):
    """Kokoro model dosyaları indirilmemiş."""


@dataclass
class Narration:
    audio_path: Path
    duration_seconds: float
    voice_id: str
    sample_rate: int


def model_ready() -> bool:
    return config.KOKORO_MODEL_PATH.exists() and config.KOKORO_VOICES_PATH.exists()


def download_model(force: bool = False) -> None:
    """Model dosyalarını veri diskine indirir (~350 MB toplam)."""
    config.KOKORO_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    downloads = (
        (MODEL_URL, config.KOKORO_MODEL_PATH),
        (VOICES_URL, config.KOKORO_VOICES_PATH),
    )
    for url, target in downloads:
        if target.exists() and not force:
            print(f"  atlandı (mevcut): {target.name}")
            continue

        print(f"  indiriliyor: {target.name}")
        tmp = target.with_suffix(target.suffix + ".partial")

        def _progress(block: int, block_size: int, total: int) -> None:
            if total <= 0:
                return
            pct = min(100, block * block_size * 100 // total)
            print(f"\r    {pct}%", end="", flush=True)

        try:
            urllib.request.urlretrieve(url, tmp, reporthook=_progress)
            tmp.replace(target)
            print(f"\r    tamam ({target.stat().st_size // (1024 * 1024)} MB)")
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def _split_sentences(text: str) -> list[str]:
    """Uzun metni cümlelere böler.

    Kokoro tek seferde çok uzun metinde tempo kaybediyor; cümle cümle sentezleyip
    aralarına nefes payı koymak hem daha doğal hem bellek açısından güvenli.
    """
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _load_model():
    if not model_ready():
        raise ModelMissing(
            f"Kokoro model dosyaları yok. Şunu çalıştır:\n"
            f"  py -3.12 -m core.voice --download-model\n"
            f"Beklenen konum: {config.KOKORO_MODEL_PATH.parent}"
        )
    from kokoro_onnx import Kokoro

    return Kokoro(str(config.KOKORO_MODEL_PATH), str(config.KOKORO_VOICES_PATH))


def synthesize(
    text: str,
    voice_id: str,
    speech_rate: float,
    out_path: Path,
    sentence_gap_seconds: float = 0.35,
) -> Narration:
    """Metni seslendirip WAV olarak yazar.

    `sentence_gap_seconds`: cümleler arası sessizlik. Bedtime içeriğinde bu boşluk
    tempoyu yavaşlatan asıl araç — sadece `speech_rate` düşürmek robotik duyuluyor.
    """
    kokoro = _load_model()
    sentences = _split_sentences(text)
    if not sentences:
        raise ValueError("Seslendirilecek metin boş.")

    sample_rate = config.TTS_SAMPLE_RATE
    gap = np.zeros(int(sample_rate * sentence_gap_seconds), dtype=np.float32)

    chunks: list[np.ndarray] = []
    for i, sentence in enumerate(sentences):
        samples, sr = kokoro.create(sentence, voice=voice_id, speed=speech_rate, lang="en-us")
        if sr != sample_rate:
            raise RuntimeError(f"Beklenmeyen örnekleme hızı: {sr} (beklenen {sample_rate})")
        chunks.append(np.asarray(samples, dtype=np.float32))
        if i < len(sentences) - 1:
            chunks.append(gap)

    audio = np.concatenate(chunks)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, sample_rate)

    return Narration(
        audio_path=out_path,
        duration_seconds=len(audio) / sample_rate,
        voice_id=voice_id,
        sample_rate=sample_rate,
    )


def estimate_duration(text: str, speech_rate: float, sentence_gap_seconds: float = 0.35) -> float:
    """Sentez yapmadan süre tahmini.

    Senaryo uzunluğunu format hedefine oturtmak için kullanılır — 10 dakikalık
    hedefe 3 dakikalık metin yazmak boşa render demek.
    """
    words = len(text.split())
    sentences = len(_split_sentences(text))
    # Kokoro ~165 kelime/dk temel hız; speech_rate çarpan.
    base_seconds = words / (165 * speech_rate) * 60
    return base_seconds + max(0, sentences - 1) * sentence_gap_seconds


def voices_for(channel: config.Channel) -> list[str]:
    return BEDTIME_VOICES if channel is config.Channel.BEDTIME else STORYTIME_VOICES


def pick_voice(channel: config.Channel, recent_voice_ids: list[str]) -> str:
    """Ses havuzundan seçim yapar, arka arkaya tekrarı önler.

    Varyasyon kapısının ses ekseni aynı sesin üst üste
    `VARIATION_MAX_VOICE_STREAK` kereden fazla kullanılmasını reddediyor.
    Kanal profilindeki sabit sesi her bölümde göndermek, kapının hattı
    kilitlemesi demekti — seçim kaynağında yapılmalı.

    `recent_voice_ids` en yeniden en eskiye sıralı gelir.
    """
    pool = voices_for(channel)

    # Baştaki kesintisiz seri: kaç bölümdür aynı ses kullanılıyor?
    streak = 0
    for v in recent_voice_ids:
        if recent_voice_ids and v == recent_voice_ids[0]:
            streak += 1
        else:
            break

    current = recent_voice_ids[0] if recent_voice_ids else None
    limit = config.VARIATION_MAX_VOICE_STREAK

    # Seri sınıra dayandıysa sesi zorunlu olarak değiştir.
    if current is not None and streak >= limit - 1:
        alternatives = [v for v in pool if v != current]
        if alternatives:
            # Son kullanılanlardan en uzak olanı seç — döngüsel tekrarı da kırar.
            def staleness(v: str) -> int:
                return recent_voice_ids.index(v) if v in recent_voice_ids else len(pool) * 10

            return max(alternatives, key=staleness)

    return current or pool[0]


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Kokoro TTS yardımcıları")
    parser.add_argument("--download-model", action="store_true", help="Model dosyalarını indir")
    parser.add_argument("--force", action="store_true", help="Mevcut dosyaları yeniden indir")
    parser.add_argument("--test", metavar="METIN", help="Kısa bir test seslendirmesi üret")
    parser.add_argument("--voice", default="af_bella")
    args = parser.parse_args()

    if args.download_model:
        print("Kokoro model dosyaları indiriliyor…")
        download_model(force=args.force)
        print("Tamam.")
        return 0

    if args.test:
        out = config.CACHE_DIR / "tts" / "test.wav"
        n = synthesize(args.test, args.voice, 0.82, out)
        print(f"Yazıldı: {n.audio_path} ({n.duration_seconds:.1f} sn, ses: {n.voice_id})")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
