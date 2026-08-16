"""Sahne planı — senaryoyu render edilebilir bir yapıya çevirir.

Senaryo "ne anlatılacağını" söyler; storyboard "ne gösterileceğini" söyler.
Asset seçimi burada yapılır ve varyasyon kapısının görsel ekseni bu seçimleri denetler.

Asset havuzu henüz boş (Faz 1'de doldurulacak). O yüzden seçim, asset kimliklerini
sahne özelliklerinden **türetir** — havuz geldiğinde aynı kimlikler gerçek dosyalara
karşılık gelecek, kod değişmeyecek.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core import ideation, script

# Sahne ruh hali → arka plan ışık/renk varyantı
MOOD_VARIANTS = {
    "calm": "soft",
    "curious": "bright",
    "warm": "golden",
    "gentle": "hazy",
    "resolved": "dusk",
}
DEFAULT_VARIANT = "soft"


# Türkçe karakterler ASCII'ye çevrilir. Doğrudan [^a-z0-9] filtrelemek
# "balıkçıl" → "bal_k_l" gibi bilgi kaybeden kimlikler üretiyordu; render tarafı
# tür adından siluet türettiği için bu kayıp doğrudan yanlış görsele yol açar.
_TR_MAP = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "I": "i",
    "İ": "i", "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
})


def _slug(text: str) -> str:
    """Serbest metni asset kimliğine çevirir. Türkçe karakterler korunur."""
    s = text.strip().translate(_TR_MAP).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40] or "unknown"


def _background_id(setting: str, mood: str) -> str:
    variant = MOOD_VARIANTS.get(mood.lower(), DEFAULT_VARIANT)
    return f"bg/{_slug(setting)}/{variant}"


def _character_id(character: str, action: str) -> str:
    """Karakter pozu eylemden türetilir.

    Poz havuzu sınırlıdır — asset pack'te her karakter için sabit bir poz seti
    dondurulur. Burada eylem, o setteki en yakın poza eşlenir.
    """
    action_l = action.lower()
    if any(w in action_l for w in ("walk", "run", "follow", "travel", "climb")):
        pose = "walking"
    elif any(w in action_l for w in ("sit", "rest", "settle", "curl", "sleep")):
        pose = "resting"
    elif any(w in action_l for w in ("look", "watch", "see", "notice", "find", "peer")):
        pose = "looking"
    # "carr" gövdesi hem "carry" hem "carries" yakalar — "carry" yalnızca ilkini yakalardı.
    elif any(w in action_l for w in ("carr", "hold", "give", "bring", "share")):
        pose = "carrying"
    else:
        pose = "standing"
    return f"char/{_slug(character)}/{pose}"


def build(premise: ideation.Premise, episode: script.Episode) -> dict[str, Any]:
    """Render'ın tüketeceği sahne planını üretir.

    `premise` alanı korunur — `ideation` bunu okuyarak son bölümlerin eksen
    değerlerini eler, yani tekrar önleme kaynağa kadar geri besleniyor.

    Her sahnede iki karakter yuvası var: sabit kahraman (Fen) ve o bölümün
    misafiri. Varyasyon kapısının görsel ekseni ikisini birden görür — kahraman
    her bölümde tekrar ettiği için tek başına örtüşme yaratmaz, ama misafir ve
    arka plan kombinasyonu ayırt edici kalır.
    """
    protagonist = ideation.PROTAGONIST["species"]

    scenes: list[dict[str, Any]] = []
    for i, scene in enumerate(episode.scenes):
        bg = _background_id(scene.setting, scene.mood)
        hero = _character_id(protagonist, scene.action)
        guest = _character_id(premise.character, scene.action)
        scenes.append(
            {
                "index": i,
                "narration": scene.narration,
                "setting": scene.setting,
                "action": scene.action,
                "mood": scene.mood,
                "duration_seconds": scene.duration_seconds,
                "transition": scene.transition,
                "assets": {"background": bg, "character": hero, "companion": guest},
            }
        )

    return {
        "premise": premise.to_dict(),
        "title": episode.title,
        "description": episode.description,
        "scenes": scenes,
    }


def _dedupe(ids: list[str]) -> list[str]:
    """Sırayı koruyarak tekilleştirir — Jaccard için sıra önemsiz, okunurluk için iyi."""
    seen: set[str] = set()
    return [a for a in ids if not (a in seen or seen.add(a))]


def asset_ids(storyboard: dict[str, Any]) -> list[str]:
    """Bölümün kullandığı TÜM asset kimlikleri. Render bunu tüketir."""
    ids: list[str] = []
    for scene in storyboard.get("scenes", []):
        ids.extend(v for v in scene.get("assets", {}).values() if v)
    return _dedupe(ids)


# Kahraman her bölümde tekrar eder — bu tasarım gereği, marka sürekliliğinin
# kendisi. Varyasyon kapısına dahil edilirse her bölümde ~5 ortak asset yaratır
# ve Jaccard örtüşmesi eşiği sürekli aşarak hattı kilitler.
VARIATION_ASSET_KEYS = ("background", "companion")


def variation_asset_ids(storyboard: dict[str, Any]) -> list[str]:
    """Varyasyon kapısının görsel ekseninin karşılaştırdığı liste.

    Kahraman hariç: tekrar etmesi beklenen bir varlığı "fazla benziyor" diye
    saymak, kapıyı kendi markamıza karşı çalıştırmak olurdu.
    """
    ids: list[str] = []
    for scene in storyboard.get("scenes", []):
        assets = scene.get("assets", {})
        ids.extend(assets[k] for k in VARIATION_ASSET_KEYS if assets.get(k))
    return _dedupe(ids)


def to_json(storyboard: dict[str, Any]) -> str:
    return json.dumps(storyboard, ensure_ascii=False)
