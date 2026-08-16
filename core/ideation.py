"""Fikir üretimi — tekrar önleme burada başlar.

Varyasyon kapısı bir savunma hattıdır, üretim stratejisi değil. Eğer ideation her
seferinde "sevimli hayvan uykuya dalıyor" üretirse kapı sürekli reddeder ve hat
boşa döner. Bu yüzden fikir üretimi **kombinatoriktir**: her bölüm dört eksenin
farklı bir bileşiminden doğar ve kullanılmış bileşimler tekrar seçilmez.

    premise = konu × mekân × misafir × anlatı şekli

Kahraman (Fen, su samuru) sabittir ve havuzda yer almaz — marka sürekliliği
tekrar eden bir karakterden gelir. Değişen, her bölümde karşılaşılan misafirdir.

Bu, kapının beş ekseninden üçünü (senaryo, yapı, görsel) kaynağında besler.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core import config, db

# --------------------------------------------------------------------------
# Eksen havuzları — Kanal A (Bedtime, 2-5 yaş)
# --------------------------------------------------------------------------
# Kasıtlı olarak "uyku" temalı değil: her bölüm uykuya götüren bir sona sahip
# ama hikâyenin kendisi merak ve keşif taşır. Sadece "X uyudu" varyantları
# üretmek tam olarak inauthentic content politikasının hedeflediği şey.

BEDTIME_TOPICS = [
    "kaybolan bir şeyi geri götürmek", "beklenmedik bir misafir ağırlamak",
    "bir sesin nereden geldiğini bulmak", "birine küçük bir hediye hazırlamak",
    "gökyüzünde bir değişikliği fark etmek", "yeni bir arkadaşa yol göstermek",
    "bir şeyi paylaşmayı öğrenmek", "korktuğu bir şeyin aslında zararsız olduğunu görmek",
    "bir koleksiyon tamamlamak", "havanın değişmesini izlemek",
    "birinin işini kolaylaştırmak", "geceleri uyanık olan canlıları tanımak",
    "bir izi takip etmek", "kırılan bir şeyi onarmak",
    "sabırla beklemeyi öğrenmek", "bir şeyi ilk kez denemek",
]

BEDTIME_SETTINGS = [
    "sessiz orman", "ay ışığında göl kıyısı", "yosunlu dere yatağı",
    "eski bir meyve bahçesi", "çiçek açmış bir vadi", "kar altında çam ormanı",
    "sisli bir tepe", "sahil kumsalı", "yıldızların göründüğü açıklık",
    "büyük bir ağacın kovuğu", "bambu korusu", "ılık bir çayır",
]

# --------------------------------------------------------------------------
# Kahraman — SABİT
# --------------------------------------------------------------------------
# 2026'da en hızlı büyüyen çocuk kanalları konsept değil KARAKTER etrafında
# kuruluyor. Her bölümde başka bir hayvan kullanmak marka sürekliliğini yok
# ederdi; tekrar eden bir kahraman izleyicinin geri gelme sebebidir.
PROTAGONIST = {
    "name": "Fen",
    "species": "su samuru",
    "traits": "sakin, yardımsever, acele etmez",
    # Dere/su teması bedtime için doğal bir ambiyans kaynağı: su sesi.
    "home": "yosunlu dere yatağı",
}

# Kahraman sabit olunca varyasyon kapısının "karakter" ekseni boşa düşerdi.
# Onun yerine her bölümde karşılaşılan MİSAFİR değişir — hem varyasyon korunur
# hem her bölüm Fen'in dünyasına yeni biri katar.
BEDTIME_COMPANIONS = [
    "utangaç porsuk", "meraklı tavşan", "yaşlı kirpi", "sessiz tilki",
    "yavru geyik", "kararlı sincap", "hayalperest fare", "küçük baykuş",
    "sakin kaplumbağa", "uzun bacaklı balıkçıl", "yalnız kunduz", "gri kaz",
    "yavru porsuk", "ürkek gelincik", "yaşlı kurbağa", "beyaz güvercin",
]

# Anlatı şekli, varyasyon kapısının "yapı" eksenini doğrudan etkiler.
# Aynı şekil arka arkaya seçilmez.
NARRATIVE_SHAPES = [
    {"name": "yolculuk", "beats": ["ayrılış", "üç karşılaşma", "varış", "dinlenme"]},
    {"name": "arayış", "beats": ["kayıp fark edilir", "iz sürülür", "bulunur", "geri dönülür"]},
    {"name": "misafir", "beats": ["beklenmedik gelen", "ağırlama", "birlikte iş", "uğurlama"]},
    {"name": "hazırlık", "beats": ["bir plan", "toplama", "kurma", "tamamlanma"]},
    {"name": "gözlem", "beats": ["bir fark ediş", "yakından bakma", "anlama", "paylaşma"]},
    {"name": "yardım", "beats": ["bir zorluk", "denemeler", "birlikte çözüm", "teşekkür"]},
    {"name": "keşif", "beats": ["merak", "adım adım ilerleme", "bulgu", "eve dönüş"]},
]


@dataclass(frozen=True)
class Premise:
    """Bir bölümün çekirdek fikri. Senaryo bundan yazılır.

    `character` alanı bu bölümün MİSAFİRİ — kahraman her zaman Fen.
    Alan adı `companion` değil `character`, çünkü varyasyon kapısı ve storyboard
    bu adı kullanıyor ve bu, kapının denetlediği değişken eksen.
    """

    channel: str
    topic: str
    setting: str
    character: str
    shape: dict[str, Any]

    @property
    def protagonist(self) -> str:
        return PROTAGONIST["name"]

    @property
    def combo_key(self) -> str:
        """Bu bileşimin kimliği. Aynı bileşim ikinci kez seçilmez."""
        raw = f"{self.channel}|{self.topic}|{self.setting}|{self.character}|{self.shape['name']}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "protagonist": PROTAGONIST["name"],
            "topic": self.topic,
            "setting": self.setting,
            "character": self.character,
            "shape": self.shape["name"],
            "beats": self.shape["beats"],
            "combo_key": self.combo_key,
        }

    def summary(self) -> str:
        return (
            f"{PROTAGONIST['name']} ve {self.character} — {self.topic} "
            f"({self.setting}, {self.shape['name']} yapısı)"
        )


def _pools(channel: config.Channel) -> tuple[list[str], list[str], list[str]]:
    """(konu, mekân, misafir) havuzları. Kahraman sabit olduğu için havuzda değil."""
    if channel is config.Channel.BEDTIME:
        return BEDTIME_TOPICS, BEDTIME_SETTINGS, BEDTIME_COMPANIONS
    # Kanal B pasif; açıldığında kendi havuzları buraya eklenir.
    return BEDTIME_TOPICS, BEDTIME_SETTINGS, BEDTIME_COMPANIONS


def _used_combos(channel: str) -> set[str]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT topic FROM topics WHERE channel = ? AND used_count > 0", (channel,)
        ).fetchall()
    return {r["topic"] for r in rows}


def _recent_axis_values(channel: str, limit: int = 8) -> dict[str, list[str]]:
    """Son bölümlerin eksen değerleri — arka arkaya tekrarı önlemek için."""
    recent = db.recent_jobs(channel, limit=limit)
    out: dict[str, list[str]] = {"setting": [], "character": [], "shape": []}
    for job in recent:
        raw = job.get("storyboard_json")
        if not raw:
            continue
        try:
            premise = json.loads(raw).get("premise", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        for axis in out:
            val = premise.get(axis)
            if val:
                out[axis].append(val)
    return out


def _weighted_choice(
    rng: random.Random,
    pool: list[Any],
    weights: dict[str, float] | None,
    key=lambda item: item,
) -> Any:
    """Havuzdan ağırlıklı seçim. Ağırlık yoksa düzgün rastgele.

    Ağırlıklar `core.analytics`'ten gelir ve kırpılmıştır — hiçbir değer
    sıfırlanmaz, yani ağırlıklandırma havuzu daraltmaz, yalnızca eğer.
    Bu kasıtlı: varyasyon kapısı zaten benzer bölümleri reddediyor ve geri
    beslemenin havuzu tek bir "kazanan" değere çökertmesi hattı kilitlerdi.
    """
    if not weights:
        return rng.choice(pool)
    w = [weights.get(str(key(item)), 1.0) for item in pool]
    if not any(w):
        return rng.choice(pool)
    return rng.choices(pool, weights=w, k=1)[0]


def generate(
    channel: config.Channel,
    max_attempts: int = 200,
    rng: random.Random | None = None,
    weights: dict[str, dict[str, float]] | None = None,
) -> Premise:
    """Kullanılmamış bir bileşim üretir.

    Son 8 bölümde kullanılan mekân/karakter/şekil değerleri elenir — bu, varyasyon
    kapısına gitmeden önceki ilk filtredir.

    `weights` verilmezse yayın sonrası performanstan hesaplanır: iyi tutan
    mekân/misafir/şekil değerleri daha sık seçilir. Ağırlıklar sınırlıdır
    (bkz. `core.analytics`), çünkü buradaki asıl risk optimizasyonun az
    olması değil, fazla olması.
    """
    rng = rng or random.Random()
    topics, settings, characters = _pools(channel)
    used = _used_combos(channel.value)
    recent = _recent_axis_values(channel.value)

    if weights is None:
        # Tembel import: `analytics` → `publish` → `storyboard` → `ideation`
        # zinciri modül seviyesinde döngü yaratırdı.
        from core import analytics

        weights = analytics.axis_weights(channel)

    # Son 3 bölümün şekli tekrar seçilmez — "yapı" ekseninin kaynak önlemi.
    blocked_shapes = set(recent["shape"][:3])
    blocked_settings = set(recent["setting"][:4])
    blocked_chars = set(recent["character"][:4])

    fallback: Premise | None = None

    for attempt in range(max_attempts):
        # Son çeyrekte kısıtları gevşet — havuz tükendiyse kilitlenmemeli
        relaxed = attempt > max_attempts * 0.75

        shape_pool = [s for s in NARRATIVE_SHAPES if relaxed or s["name"] not in blocked_shapes]
        setting_pool = [s for s in settings if relaxed or s not in blocked_settings]
        char_pool = [c for c in characters if relaxed or c not in blocked_chars]

        if not (shape_pool and setting_pool and char_pool):
            continue

        premise = Premise(
            channel=channel.value,
            topic=rng.choice(topics),
            setting=_weighted_choice(rng, setting_pool, weights.get("setting")),
            character=_weighted_choice(rng, char_pool, weights.get("character")),
            shape=_weighted_choice(
                rng, shape_pool, weights.get("shape"), key=lambda s: s["name"]
            ),
        )

        if premise.combo_key not in used:
            return premise
        fallback = fallback or premise

    if fallback is not None:
        # Havuz tükendi: bileşim tekrarı var ama senaryo hâlâ farklı yazılacak
        # ve varyasyon kapısı son sözü söyleyecek.
        return fallback

    raise RuntimeError(
        f"{channel.value} için fikir üretilemedi — eksen havuzları çok dar. "
        f"core/ideation.py içindeki listeleri genişlet."
    )


def reserve(premise: Premise) -> None:
    """Bileşimi kullanıldı olarak işaretler.

    Senaryo yazımına GİRERKEN çağrılır, yayında değil — böylece aynı bileşim
    paralel işlerde iki kez seçilmez.
    """
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO topics (channel, topic, used_count, last_used, created_at) "
            "VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT(channel, topic) DO UPDATE SET "
            "  used_count = used_count + 1, last_used = excluded.last_used",
            (premise.channel, premise.combo_key, now, now),
        )


def pool_size(channel: config.Channel) -> int:
    """Teorik bileşim sayısı — havuzun ne kadar dayanacağını gösterir."""
    topics, settings, characters = _pools(channel)
    return len(topics) * len(settings) * len(characters) * len(NARRATIVE_SHAPES)


def exhaustion_report(channel: config.Channel) -> dict[str, Any]:
    total = pool_size(channel)
    used = len(_used_combos(channel.value))
    cadence = config.active_cadence()
    per_week = max(1, cadence.episodes_per_week_per_channel)
    return {
        "total_combinations": total,
        "used": used,
        "remaining": total - used,
        "weeks_of_runway": (total - used) // per_week,
    }
