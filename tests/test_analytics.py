"""Geri besleme testleri — YouTube Analytics API'sine hiç dokunmadan.

Kanıtlanan asıl şey, geri beslemenin çalıştığı değil: **fazla çalışmadığı**.
Bu hattın varlık sebebi varyasyon; "ne tuttuysa onu yap" döngüsü sınırsız
bırakılırsa her bölüm aynı mekânda geçer ve varyasyon kapısı hattı kilitler.
Aşağıdaki testlerin çoğu ağırlıklandırmanın üst sınırını koruyor.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from core import analytics, config, db, ideation


def _published(
    setting: str = "sessiz orman",
    character: str = "utangaç porsuk",
    shape: str = "yolculuk",
    retention: float = 40.0,
    views: int = 1000,
    days_ago: int = 30,
    channel: str = "bedtime",
    with_analytics: bool = True,
) -> int:
    """Yayınlanmış, ölçülmüş bir bölüm kurar."""
    job_id = db.create_job(channel, "episode")
    db.update_job(
        job_id,
        status=db.JobStatus.PUBLISHED.value,
        title=f"Fen and the {setting}",
        youtube_video_id=f"vid{job_id:04d}",
        published_at=(datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        storyboard_json=json.dumps(
            {
                "premise": {
                    "setting": setting,
                    "character": character,
                    "shape": shape,
                    "protagonist": "Fen",
                },
                "scenes": [],
            }
        ),
    )
    if with_analytics:
        db.record_analytics(
            job_id=job_id,
            youtube_video_id=f"vid{job_id:04d}",
            views=views,
            avg_view_duration_s=int(600 * retention / 100),
            retention_pct=retention,
        )
    return job_id


# --------------------------------------------------------------------------
# Ölçüm çekme
# --------------------------------------------------------------------------

def test_olcumler_dbye_yazilir():
    job_id = _published(with_analytics=False)

    def fetcher(channel, video_id, published_at):
        return {"views": 4200, "averageViewDuration": 310, "averageViewPercentage": 51.5}

    stats = analytics.refresh(config.Channel.BEDTIME, fetcher=fetcher)

    assert [s.job_id for s in stats] == [job_id]
    row = db.latest_analytics(job_id)
    assert row["views"] == 4200
    assert row["retention_pct"] == pytest.approx(51.5)


def test_taze_video_olculmez():
    """İlk günlerin verisi kanalın performansı değil, bildirim dalgası."""
    _published(days_ago=config.ANALYTICS_MIN_VIDEO_AGE_DAYS - 1, with_analytics=False)

    calls = []

    def fetcher(channel, video_id, published_at):
        calls.append(video_id)
        return {"views": 1, "averageViewDuration": 1, "averageViewPercentage": 1.0}

    assert analytics.refresh(config.Channel.BEDTIME, fetcher=fetcher) == []
    assert not calls


def test_tek_videonun_hatasi_digerlerini_durdurmaz():
    """Bir videonun API hatası kanalın tüm geri beslemesini durdurmamalı."""
    bozuk = _published(setting="sessiz orman", with_analytics=False)
    saglam = _published(setting="bambu korusu", with_analytics=False)

    def fetcher(channel, video_id, published_at):
        if video_id == f"vid{bozuk:04d}":
            raise RuntimeError("403 quotaExceeded")
        return {"views": 900, "averageViewDuration": 200, "averageViewPercentage": 33.0}

    stats = analytics.refresh(config.Channel.BEDTIME, fetcher=fetcher)

    assert [s.job_id for s in stats] == [saglam]
    assert db.latest_analytics(bozuk) is None


def test_olcumler_ustune_yazilmaz_birikir():
    """7. gündeki retention ile 90. gündeki farklı — ikisi de bilgi."""
    job_id = _published(retention=30.0)
    db.record_analytics(job_id, f"vid{job_id:04d}", 5000, 400, 44.0)

    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM analytics WHERE job_id = ?", (job_id,)
        ).fetchone()[0]

    assert n == 2
    # En yeni ölçüm kazanır
    assert db.latest_analytics(job_id)["retention_pct"] == pytest.approx(44.0)


# --------------------------------------------------------------------------
# Eksen ağırlıkları — asıl korunan sınırlar
# --------------------------------------------------------------------------

def test_veri_yetersizken_agirlik_notr():
    """Tek şanslı video havuzu domine edemez."""
    _published(setting="bambu korusu", retention=95.0)
    _published(setting="sisli bir tepe", retention=20.0)
    _published(setting="ılık bir çayır", retention=20.0)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert weights["setting"]["bambu korusu"] == 1.0


def test_yeterli_orneklemde_iyi_eksen_agirlik_kazanir():
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="bambu korusu", retention=60.0)
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="sisli bir tepe", retention=20.0)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert weights["setting"]["bambu korusu"] > 1.0
    assert weights["setting"]["sisli bir tepe"] < 1.0


def test_agirlik_tavani_asilmaz():
    """KRİTİK: sınırsız ağırlık havuzu tek değere çökertir ve varyasyon
    kapısı hattı kilitler. Uçuk bir fark bile tavanı geçmemeli."""
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="bambu korusu", retention=99.0)
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="sisli bir tepe", retention=1.0)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert weights["setting"]["bambu korusu"] <= config.ANALYTICS_MAX_WEIGHT
    assert weights["setting"]["sisli bir tepe"] >= config.ANALYTICS_MIN_WEIGHT


def test_hicbir_eksen_degeri_sifirlanmaz():
    """Ağırlık havuzu daraltmaz, yalnızca eğer. Sıfır ağırlık, o mekânı
    kalıcı olarak elemek demek olurdu — geri beslemenin yetkisi bu değil."""
    for _ in range(config.ANALYTICS_MIN_SAMPLES * 2):
        _published(setting="bambu korusu", retention=80.0)
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="sisli bir tepe", retention=2.0)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert all(w > 0 for w in weights["setting"].values())


def test_olculmemis_deger_notr_sayilir():
    """Havuza yeni eklenen bir mekân, ölçülmediği için cezalandırılmamalı."""
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="bambu korusu", retention=60.0)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert "kar altında çam ormanı" not in weights["setting"]
    # ideation bunu 1.0 olarak okur
    assert weights["setting"].get("kar altında çam ormanı", 1.0) == 1.0


def test_veri_yokken_agirlik_bos():
    assert analytics.axis_weights(config.Channel.BEDTIME) == {
        "setting": {}, "character": {}, "shape": {}
    }


def test_kahraman_agirliklandirilmaz():
    """Fen sabit — ölçmenin anlamı yok, ağırlıklandırmanın hiç yok."""
    assert "protagonist" not in analytics.WEIGHTED_AXES


def test_retention_views_uzerinden_degil_yuzde_uzerinden_olculur():
    """Yüksek izlenmeli ama kötü tutan bölüm ödüllendirilmemeli.

    Views abonelik sayısıyla ve o günkü dağıtımla ölçekleniyor; bölümün
    kendi başına ne kadar tuttuğunu söylemiyor.
    """
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="bambu korusu", retention=20.0, views=1_000_000)
    for _ in range(config.ANALYTICS_MIN_SAMPLES):
        _published(setting="sisli bir tepe", retention=60.0, views=100)

    weights = analytics.axis_weights(config.Channel.BEDTIME)

    assert weights["setting"]["sisli bir tepe"] > weights["setting"]["bambu korusu"]


# --------------------------------------------------------------------------
# ideation bağlantısı
# --------------------------------------------------------------------------

def test_agirlik_secim_oranini_beklenen_kadar_kaydirir():
    """Ağırlık 2.0 → o değer havuzdaki diğerlerine göre iki kat olası.

    Seçimin kendisi test ediliyor, `generate()` üzerinden değil: DB'ye
    dokunmadığı için büyük örneklemle çalışabiliyor ve oran istatistiksel
    gürültüye değil gerçek davranışa bakıyor.
    """
    rng = random.Random(20260816)
    pool = ideation.BEDTIME_SETTINGS
    weights = {"bambu korusu": 2.0}

    picks = [ideation._weighted_choice(rng, pool, weights) for _ in range(20_000)]

    pay = picks.count("bambu korusu") / len(picks)
    beklenen = 2 / (len(pool) - 1 + 2)
    assert pay == pytest.approx(beklenen, abs=0.015)


def test_ideation_agirliklari_dogru_eksenlere_dagitir(monkeypatch):
    """Plumbing testi: her eksen kendi ağırlık sözlüğünü almalı.

    `shape` havuzu sözlüklerden oluşuyor ama ağırlıklar şekil ADIYLA
    anahtarlanıyor — yanlış anahtar sessizce her ağırlığı 1.0 yapardı.
    """
    calls: list[tuple[dict | None, object]] = []

    def spy(rng, pool, weights, key=lambda item: item):
        calls.append((weights, key(pool[0])))
        return pool[0]

    monkeypatch.setattr(ideation, "_weighted_choice", spy)
    weights = {
        "setting": {"bambu korusu": 2.0},
        "character": {"utangaç porsuk": 0.5},
        "shape": {"yolculuk": 1.7},
    }

    ideation.generate(config.Channel.BEDTIME, rng=random.Random(1), weights=weights)

    assert [c[0] for c in calls] == [
        weights["setting"], weights["character"], weights["shape"]
    ]
    # Şekil ekseni sözlüğü değil adı anahtar olarak kullanmalı
    assert calls[2][1] in {s["name"] for s in ideation.NARRATIVE_SHAPES}


def test_agirlikli_secim_hala_tum_havuzu_dolasir():
    """KRİTİK: en iyi mekân iki kat olası olsa bile diğerleri seçilmeye devam
    etmeli. Aksi halde varyasyon kapısı birkaç bölüm sonra hattı durdurur."""
    rng = random.Random(20260816)
    weights = {"setting": {"bambu korusu": config.ANALYTICS_MAX_WEIGHT}}

    secimler = {
        ideation.generate(config.Channel.BEDTIME, rng=rng, weights=weights).setting
        for _ in range(300)
    }

    assert len(secimler) == len(ideation.BEDTIME_SETTINGS), (
        f"havuzun {len(ideation.BEDTIME_SETTINGS) - len(secimler)} değeri hiç seçilmedi"
    )


def test_agirliksiz_ideation_eskisi_gibi_calisir():
    rng = random.Random(7)
    premise = ideation.generate(config.Channel.BEDTIME, rng=rng, weights={})

    assert premise.setting in ideation.BEDTIME_SETTINGS
    assert premise.character in ideation.BEDTIME_COMPANIONS
    assert premise.protagonist == "Fen"


# --------------------------------------------------------------------------
# Özet
# --------------------------------------------------------------------------

def test_ozet_kanal_ortalamasini_verir():
    _published(retention=30.0, views=100)
    _published(retention=50.0, views=300)

    s = analytics.summary(config.Channel.BEDTIME)

    assert s["measured"] == 2
    assert s["mean_retention"] == pytest.approx(40.0)
    assert s["total_views"] == 400


def test_olcum_yokken_ozet_bos_ama_patlamaz():
    s = analytics.summary(config.Channel.BEDTIME)

    assert s["measured"] == 0
    assert s["mean_retention"] == 0.0


def test_yayinlanmamis_is_olcume_girmez():
    job_id = db.create_job("bedtime", "episode")
    db.update_job(job_id, status=db.JobStatus.APPROVED.value)

    assert db.published_awaiting_analytics("bedtime") == []
