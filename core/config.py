"""Merkezi yapılandırma: yollar, kanal profilleri, kadans ve bütçe tavanları.

Tüm ağır veri OTOMASYON_DATA_ROOT altında yaşar (harici disk). Kod C:'de kalır.
Disk değişirse .env'deki tek satır güncellenir, kod dokunulmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


# --------------------------------------------------------------------------
# Yollar
# --------------------------------------------------------------------------

def _data_root() -> Path:
    raw = os.getenv("OTOMASYON_DATA_ROOT")
    if not raw:
        raise RuntimeError(
            "OTOMASYON_DATA_ROOT tanımlı değil. .env.example dosyasını .env olarak "
            "kopyalayıp veri kökünü ayarla (ör. D:\\otomasyon-data)."
        )
    return Path(raw)


DATA_ROOT = _data_root()

ASSETS_DIR = DATA_ROOT / "assets"
MODELS_DIR = DATA_ROOT / "models"
OUTPUT_DIR = DATA_ROOT / "output"
CACHE_DIR = DATA_ROOT / "cache"
DB_DIR = DATA_ROOT / "db"

# Onay kuyruğu: render bitmiş ama henüz onaylanmamış videolar
PENDING_DIR = OUTPUT_DIR / "pending"
# Onaylanmış, yüklenmeye hazır
APPROVED_DIR = OUTPUT_DIR / "approved"
# Varyasyon veya QC kapısından dönmüş, yeniden üretim bekleyen
REJECTED_DIR = OUTPUT_DIR / "rejected"
# Yayınlanmış (arşiv)
PUBLISHED_DIR = OUTPUT_DIR / "published"

DB_PATH = DB_DIR / "pipeline.sqlite3"

ALL_DIRS = [
    ASSETS_DIR, MODELS_DIR, OUTPUT_DIR, CACHE_DIR, DB_DIR,
    PENDING_DIR, APPROVED_DIR, REJECTED_DIR, PUBLISHED_DIR,
]


def ensure_dirs() -> None:
    """Veri dizinlerini oluşturur. Idempotent."""
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Kanal profilleri
# --------------------------------------------------------------------------

class Channel(StrEnum):
    BEDTIME = "bedtime"      # Kanal A — Made for Kids
    STORYTIME = "storytime"  # Kanal B — MFK değil (şimdilik pasif)


@dataclass(frozen=True)
class VideoFormat:
    name: str
    min_seconds: int
    max_seconds: int
    target_seconds: int


@dataclass(frozen=True)
class ChannelProfile:
    channel: Channel
    display_name: str
    made_for_kids: bool
    age_range: str
    formats: dict[str, VideoFormat]
    # Anlatım hızı: bedtime belirgin şekilde yavaş
    speech_rate: float
    voice_id: str
    token_file_env: str
    # Pasif kanallar tanımlı kalır ama üretim yapmaz. İkinci kanal, ilk kanaldan
    # 30+ video ve retention verisi geldikten sonra açılır — tek kanalla öğrenmek
    # daha hızlı ve politika yüzeyi daha küçük.
    active: bool = True


# 8 dakika sert eşik: altında mid-roll reklam açılmıyor.
# Hiçbir uzun-form format 480 saniyenin altına inmez.
MIDROLL_THRESHOLD_SECONDS = 480

CHANNELS: dict[Channel, ChannelProfile] = {
    Channel.BEDTIME: ChannelProfile(
        channel=Channel.BEDTIME,
        display_name="Bedtime / Calm",
        made_for_kids=True,
        age_range="2-5",
        formats={
            # Temel üretim birimi. Derlemeler bunlardan ffmpeg ile birleştirilir.
            "episode": VideoFormat("episode", 480, 720, 600),      # 8-12 dk
            # Render EDİLMEZ — episode'lardan concat edilir.
            "compilation": VideoFormat("compilation", 2400, 3600, 3000),  # 40-60 dk
            "short": VideoFormat("short", 20, 59, 45),
        },
        speech_rate=0.82,
        voice_id="af_bella",
        token_file_env="YT_CHANNEL_A_TOKEN_FILE",
    ),
    Channel.STORYTIME: ChannelProfile(
        channel=Channel.STORYTIME,
        display_name="Story Time",
        # 13 yaş altına yönelik hikâye içeriği YouTube tanımına göre kesin olarak
        # "made for kids"tir. Yanlış işaretleme FTC/COPPA sorumluluğu doğurur.
        # Bkz. docs/content-guidelines.md §1. Bu değer optimizasyon için değiştirilmez.
        made_for_kids=True,
        age_range="5-10",
        formats={
            "episode": VideoFormat("episode", 600, 1200, 840),     # 10-20 dk
            "short": VideoFormat("short", 20, 59, 45),
        },
        speech_rate=1.0,
        voice_id="am_michael",
        token_file_env="YT_CHANNEL_B_TOKEN_FILE",
        # Faz 4'te açılır. Önce tek kanalla öğrenme döngüsü tamamlanır.
        active=False,
    ),
}


def active_channels() -> dict[Channel, ChannelProfile]:
    return {ch: p for ch, p in CHANNELS.items() if p.active}


# --------------------------------------------------------------------------
# Kadans — inauthentic content riskini yöneten üst sınırlar
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Cadence:
    """Faz bazlı yayın kadansı. Bunlar tavan, hedef değil."""
    phase: str
    episodes_per_week_per_channel: int
    shorts_per_day: int


CADENCE_PHASES: dict[str, Cadence] = {
    "cold_start": Cadence("cold_start", 3, 1),      # Ay 1-2
    "ramp": Cadence("ramp", 5, 2),                  # Ay 3-4
    "steady": Cadence("steady", 7, 2),              # Ay 5+, YPP onaylı
}

# Mutlak günlük tavan. Hiçbir faz bunu aşamaz.
# Bunun üstü varyasyon denetimini imkânsızlaştırır ve doğrudan politika riskidir.
HARD_DAILY_CAP_LONGFORM = 2
HARD_DAILY_CAP_SHORTS = 2

# Aktif faz. Kanal YPP'ye kabul edilene kadar elle değiştirilmez.
ACTIVE_PHASE = os.getenv("ACTIVE_CADENCE_PHASE", "cold_start")


def active_cadence() -> Cadence:
    if ACTIVE_PHASE not in CADENCE_PHASES:
        raise ValueError(
            f"Bilinmeyen kadans fazı: {ACTIVE_PHASE!r}. "
            f"Geçerli: {sorted(CADENCE_PHASES)}"
        )
    return CADENCE_PHASES[ACTIVE_PHASE]


# --------------------------------------------------------------------------
# Bütçe kapısı
# --------------------------------------------------------------------------

def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


SCRIPT_MODEL = os.getenv("SCRIPT_MODEL", "claude-opus-5")

BUDGET_MAX_USD_PER_VIDEO = _float_env("BUDGET_MAX_USD_PER_VIDEO", 4.00)
BUDGET_MAX_USD_PER_MONTH = _float_env("BUDGET_MAX_USD_PER_MONTH", 150.00)

# Kling 3.0: ~$0.84 / 10sn 1080p senkron sesli.
# 5. rejenerasyonda $1.50'lik klip $5 olur — en yaygın 2026 maliyet tuzağı.
# Bu yüzden klip başına yeniden deneme sert sınırlı.
KLING_USD_PER_10S = 0.84
MAX_REGENERATIONS_PER_CLIP = 2
MAX_AI_CLIPS_PER_VIDEO = 4


# --------------------------------------------------------------------------
# Onay kapısı
# --------------------------------------------------------------------------

REQUIRE_HUMAN_APPROVAL = os.getenv("REQUIRE_HUMAN_APPROVAL", "true").lower() != "false"


# --------------------------------------------------------------------------
# Varyasyon kapısı eşikleri
# --------------------------------------------------------------------------

# Son N videoya karşı karşılaştırma yapılır.
VARIATION_LOOKBACK = 50
# Senaryo embedding kosinüs benzerliği bu eşiği aşarsa reddedilir.
VARIATION_MAX_SCRIPT_SIMILARITY = 0.82
# Aynı başlık şablonu arka arkaya en fazla bu kadar kullanılabilir.
VARIATION_MAX_TITLE_PATTERN_STREAK = 3
# Asset kombinasyonu örtüşme oranı bu eşiği aşarsa reddedilir.
VARIATION_MAX_ASSET_OVERLAP = 0.60
# Aynı ses arka arkaya en fazla bu kadar kullanılabilir.
VARIATION_MAX_VOICE_STREAK = 4


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------

RENDER_FPS = 30
RENDER_WIDTH = 1920
RENDER_HEIGHT = 1080
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920

# i5-9300H 4c/8t. Remotion headless Chrome ile kare kare render eder.
# Tüm çekirdekleri vermek makineyi kullanılamaz hale getirir.
RENDER_CONCURRENCY = 3


# --------------------------------------------------------------------------
# TTS
# --------------------------------------------------------------------------

# Kokoro-ONNX: 82M parametre, ~300 MB runtime, CPU'da rahat çalışır.
# PyTorch+CUDA ~4 GB yer isterdi; GTX 1650'nin 4 GB VRAM'i Chatterbox'a yetmiyor.
KOKORO_MODEL_PATH = MODELS_DIR / "kokoro" / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = MODELS_DIR / "kokoro" / "voices-v1.0.bin"
TTS_SAMPLE_RATE = 24000


# --------------------------------------------------------------------------
# Doğrulama
# --------------------------------------------------------------------------

def validate() -> list[str]:
    """Yapılandırma tutarlılığını denetler. Sorun listesi döner (boş = sağlam).

    Saf fonksiyon: yalnızca yapılandırma değerlerine bakar, dosya sistemine değil.
    Diskin takılı olup olmadığı ortam durumudur ve `core.doctor` orada denetler —
    burada karıştırmak, harici disk çıkarıldığında yapılandırmayı bozuk gösterirdi.
    """
    problems: list[str] = []

    if not REQUIRE_HUMAN_APPROVAL:
        problems.append(
            "REQUIRE_HUMAN_APPROVAL=false — onay kapısı kapalı. "
            "Bu, inauthentic content politikası karşısında kanalı doğrudan riske atar."
        )

    if BUDGET_MAX_USD_PER_VIDEO <= 0:
        problems.append("BUDGET_MAX_USD_PER_VIDEO pozitif olmalı.")

    cadence = active_cadence()
    if cadence.episodes_per_week_per_channel > HARD_DAILY_CAP_LONGFORM * 7:
        problems.append(
            f"Kadans fazı {cadence.phase!r} mutlak günlük tavanı aşıyor."
        )

    for ch, profile in CHANNELS.items():
        # COPPA kapısı: 13 yaş altına yönelik içerik MFK işaretlenmek ZORUNDA.
        # Bu, RPM için gevşetilebilir bir ayar değil; yanlış işaretleme yasal
        # sorumluluk doğurur. Bkz. docs/content-guidelines.md §1.
        upper_age = int(profile.age_range.split("-")[-1])
        if upper_age < 13 and not profile.made_for_kids:
            problems.append(
                f"{ch.value}: hedef yaş {profile.age_range} (13 altı) ama "
                f"made_for_kids=False. Bu yanlış sınıflandırmadır ve FTC/COPPA "
                f"sorumluluğu doğurur."
            )

        for fmt_name, fmt in profile.formats.items():
            if fmt_name == "short":
                continue
            if fmt.min_seconds < MIDROLL_THRESHOLD_SECONDS:
                problems.append(
                    f"{ch.value}/{fmt_name}: min {fmt.min_seconds}sn, "
                    f"mid-roll eşiği {MIDROLL_THRESHOLD_SECONDS}sn altında."
                )
            if not (fmt.min_seconds <= fmt.target_seconds <= fmt.max_seconds):
                problems.append(
                    f"{ch.value}/{fmt_name}: target {fmt.target_seconds} "
                    f"[{fmt.min_seconds}, {fmt.max_seconds}] aralığında değil."
                )

    return problems
