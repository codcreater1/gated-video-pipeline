"""VARYASYON KAPISI — projenin var olma sebebi.

YouTube 15 Temmuz 2025'te "repetitious content" politikasını "inauthentic content"
olarak yeniledi. Şablondan çıkmış, birbirinin neredeyse aynısı videolarla dolu
kanallar monetizasyondan çıkarılıyor: uyarı → 90 gün askı → YPP'den kalıcı çıkarma.
Aralık 2025'te Screen Culture ve KH Studio (2M+ abone, 1B+ izlenme) böyle kapandı.

Bu kapı, üretilen her videoyu son N yayına karşı beş eksende denetler. Reddedilen
iş SİLİNMEZ — yeniden üretim kuyruğuna düşer ve farklı parametrelerle tekrar dener.

Benzerlik hesabı tamamen yerel (TF-IDF + kosinüs). API çağrısı yok, maliyeti sıfır.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from core import config, db


@dataclass
class VariationCheck:
    """Tek bir eksenin sonucu."""

    axis: str
    passed: bool
    score: float
    threshold: float
    detail: str


@dataclass
class VariationVerdict:
    passed: bool
    checks: list[VariationCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[VariationCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def reason(self) -> str:
        if self.passed:
            return "Tüm varyasyon eksenleri geçti."
        return " | ".join(f"{c.axis}: {c.detail}" for c in self.failures)

    def __bool__(self) -> bool:
        return self.passed


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------

def structure_hash(storyboard: dict[str, Any]) -> str:
    """Anlatı yapısının parmak izi.

    İçeriği değil ŞEKLİ yakalar: sahne sayısı, sahne süre profili, geçiş tipleri.
    Farklı hikâyeler aynı iskeleti kullanıyorsa bu hash çakışır — istediğimiz de bu.
    """
    scenes = storyboard.get("scenes", [])
    # Süreleri 5 saniyelik kovalara yuvarla; birebir eşitlik aramıyoruz, profil arıyoruz.
    duration_profile = [int(s.get("duration_seconds", 0)) // 5 for s in scenes]
    transitions = [s.get("transition", "cut") for s in scenes]
    shape = {
        "scene_count": len(scenes),
        "durations": duration_profile,
        "transitions": transitions,
    }
    blob = json.dumps(shape, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def title_pattern(title: str) -> str:
    """Başlığın şablonunu çıkarır, içeriğini değil.

    "Luna and the Sleepy Moon"  → "X and the Y"
    "Milo and the Quiet River"  → "X and the Y"   (aynı şablon)
    """
    t = title.lower().strip()
    # Sayıları ve özel isimleri (büyük harfle başlayan sözcükler) yer tutucuya çevir
    t = re.sub(r"\d+", "#", t)
    tokens = []
    for word in re.findall(r"[a-zçğıöşü#]+", t):
        # Bağlaç/edat gibi yapı taşıyan kelimeler korunur, içerik kelimeleri maskelenir
        if word in {"and", "the", "a", "an", "of", "in", "with", "to", "for", "#"}:
            tokens.append(word)
        else:
            tokens.append("X")
    return " ".join(tokens)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# --------------------------------------------------------------------------
# Eksenler
# --------------------------------------------------------------------------

def _check_script_similarity(script: str, history: list[dict[str, Any]]) -> VariationCheck:
    """Senaryo metni son yayınlara çok benziyorsa reddet."""
    prior = [j["script"] for j in history if j.get("script")]
    threshold = config.VARIATION_MAX_SCRIPT_SIMILARITY

    if not prior:
        return VariationCheck(
            "senaryo", True, 0.0, threshold, "Karşılaştırılacak geçmiş yok."
        )

    corpus = [script, *prior]
    try:
        vectorizer = TfidfVectorizer(
            lowercase=True, stop_words="english", ngram_range=(1, 2), min_df=1
        )
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        # Metin çok kısa veya tamamen stop-word — vektörleştirilemedi
        return VariationCheck(
            "senaryo", True, 0.0, threshold, "Vektörleştirilemedi, atlandı."
        )

    sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    worst = float(sims.max())
    idx = int(sims.argmax())
    passed = worst <= threshold

    detail = (
        f"En yakın geçmiş video benzerliği {worst:.3f} (eşik {threshold:.2f})"
        if passed
        else f"Video #{prior and history[idx].get('id')} ile benzerlik {worst:.3f} "
        f"> eşik {threshold:.2f}. Senaryo fazla benzer."
    )
    return VariationCheck("senaryo", passed, worst, threshold, detail)


def _check_structure(struct_hash: str, fingerprints: list[dict[str, Any]]) -> VariationCheck:
    """Aynı anlatı iskeleti son 10 videoda kullanıldıysa reddet."""
    window = fingerprints[:10]
    prior = [f["structure_hash"] for f in window if f.get("structure_hash")]
    collisions = prior.count(struct_hash)
    passed = collisions == 0
    detail = (
        "Yapı iskeleti son 10 videoda kullanılmamış."
        if passed
        else f"Aynı yapı iskeleti son 10 videoda {collisions} kez kullanılmış."
    )
    return VariationCheck("yapı", passed, float(collisions), 0.0, detail)


def _check_title_pattern(pattern: str, fingerprints: list[dict[str, Any]]) -> VariationCheck:
    """Aynı başlık şablonu arka arkaya N kereden fazla kullanılamaz."""
    threshold = config.VARIATION_MAX_TITLE_PATTERN_STREAK
    streak = 0
    for fp in fingerprints:
        if fp.get("title_pattern") == pattern:
            streak += 1
        else:
            break
    passed = streak < threshold
    detail = (
        f"Başlık şablonu arka arkaya {streak} kez kullanılmış (sınır {threshold})."
        if passed
        else f"Başlık şablonu {streak} kez arka arkaya kullanılmış, "
        f"sınır {threshold}. Farklı şablon gerekli."
    )
    return VariationCheck("başlık", passed, float(streak), float(threshold), detail)


def _check_asset_overlap(
    asset_ids: list[str], fingerprints: list[dict[str, Any]]
) -> VariationCheck:
    """Görsel asset kombinasyonu geçmişle fazla örtüşüyorsa reddet."""
    threshold = config.VARIATION_MAX_ASSET_OVERLAP
    current = set(asset_ids)

    if not current:
        return VariationCheck("görsel", True, 0.0, threshold, "Asset listesi boş, atlandı.")

    worst = 0.0
    worst_job: int | None = None
    for fp in fingerprints[:20]:
        raw = fp.get("asset_ids_json")
        if not raw:
            continue
        overlap = _jaccard(current, set(json.loads(raw)))
        if overlap > worst:
            worst, worst_job = overlap, fp.get("job_id")

    passed = worst <= threshold
    detail = (
        f"En yüksek asset örtüşmesi {worst:.2f} (eşik {threshold:.2f})."
        if passed
        else f"Video #{worst_job} ile asset örtüşmesi {worst:.2f} > eşik {threshold:.2f}. "
        f"Farklı sahne/karakter kombinasyonu gerekli."
    )
    return VariationCheck("görsel", passed, worst, threshold, detail)


def _check_voice_streak(voice_id: str, fingerprints: list[dict[str, Any]]) -> VariationCheck:
    """Aynı ses arka arkaya N kereden fazla kullanılamaz."""
    threshold = config.VARIATION_MAX_VOICE_STREAK
    streak = 0
    for fp in fingerprints:
        if fp.get("voice_id") == voice_id:
            streak += 1
        else:
            break
    passed = streak < threshold
    detail = (
        f"Ses arka arkaya {streak} kez kullanılmış (sınır {threshold})."
        if passed
        else f"Ses {streak} kez arka arkaya kullanılmış, sınır {threshold}. "
        f"Farklı ses veya tempo gerekli."
    )
    return VariationCheck("ses", passed, float(streak), float(threshold), detail)


# --------------------------------------------------------------------------
# Ana giriş noktası
# --------------------------------------------------------------------------

def evaluate(
    channel: str,
    script: str,
    storyboard: dict[str, Any],
    title: str,
    asset_ids: list[str],
    voice_id: str,
) -> VariationVerdict:
    """Beş ekseni de denetler. Hepsi geçmeden video ilerleyemez."""
    history = db.recent_jobs(channel, limit=config.VARIATION_LOOKBACK)
    fingerprints = db.recent_fingerprints(channel, limit=config.VARIATION_LOOKBACK)

    struct = structure_hash(storyboard)
    pattern = title_pattern(title)

    checks = [
        _check_script_similarity(script, history),
        _check_structure(struct, fingerprints),
        _check_title_pattern(pattern, fingerprints),
        _check_asset_overlap(asset_ids, fingerprints),
        _check_voice_streak(voice_id, fingerprints),
    ]

    return VariationVerdict(passed=all(c.passed for c in checks), checks=checks)


def enforce(
    job_id: int,
    channel: str,
    script: str,
    storyboard: dict[str, Any],
    title: str,
    asset_ids: list[str],
    voice_id: str,
) -> VariationVerdict:
    """evaluate + reddedilirse işi yeniden üretim kuyruğuna düşürür.

    Geçerse parmak izi HENÜZ kaydedilmez — kayıt yayın anında `commit_fingerprint()`
    ile yapılır. Böylece yayınlanmamış denemeler geçmişi kirletmez.
    """
    verdict = evaluate(channel, script, storyboard, title, asset_ids, voice_id)
    if not verdict.passed:
        db.reject_job(job_id, f"VARYASYON: {verdict.reason}")
    return verdict


def commit_fingerprint(
    job_id: int,
    channel: str,
    storyboard: dict[str, Any],
    title: str,
    asset_ids: list[str],
    voice_id: str,
) -> None:
    """Yayınlanan videonun parmak izini geçmişe yazar."""
    db.record_fingerprint(
        job_id=job_id,
        channel=channel,
        script_vector=None,  # TF-IDF korpus bağımlı; benzerlik jobs.script'ten hesaplanır
        structure_hash=structure_hash(storyboard),
        title_pattern=title_pattern(title),
        asset_ids=asset_ids,
        voice_id=voice_id,
    )
